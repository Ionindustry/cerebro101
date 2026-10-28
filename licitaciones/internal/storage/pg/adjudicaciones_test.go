package pg

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/placsp"
	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

func eur(v string) *domain.Money { return &domain.Money{Value: v, Currency: "EUR"} }

// expedienteConResultados es un expediente con lotes y resultados para probar la proyección de las adjudicaciones.
func expedienteConResultados(id string, lotes []domain.Lot, presupuesto string, rs []domain.Result, comprador string) *domain.Licitacion {
	l := licitacion(id, "Servicio "+id, "ADJ", t0)
	l.Organism = domain.Organization{Name: comprador, NIF: "P1708500E"}
	l.BaseBudgetExclVAT = eur(presupuesto)
	l.Lots, l.Results = lotes, rs
	return l
}

func proyectar(t *testing.T, st *Store, id string, v int, l *domain.Licitacion) {
	t.Helper()
	ev := ingest.Event{Source: "placsp-643", SourceID: id, Version: v, RawSHA256: "sha", RawKey: "clave"}
	if ok, err := st.UpsertExpediente(context.Background(), ev, l); err != nil || !ok {
		t.Fatalf("proyectar %s v%d: %v %v", id, v, ok, err)
	}
}

func TestAdjudicacionesSeProyectanDesdeElExpediente(t *testing.T) {
	pool, st := conectar(t)
	ctx := context.Background()
	proyectar(t, st, "a/1", 1, expedienteConResultados("a/1",
		[]domain.Lot{{ID: "1", BaseBudgetExclVAT: eur("100000")}, {ID: "2", BaseBudgetExclVAT: eur("50000")}, {ID: "3"}},
		"150000", []domain.Result{
			{LotID: "1", Code: domain.ResultFormalized, WinnerName: "ACME SL", WinnerID: "b11111111", AwardedExclVAT: eur("90000"), AwardedInclVAT: eur("108900"),
				TendersReceived: ptr(4), AwardDate: "2026-03-01", FormalizedOn: "2026-04-01"},
			{LotID: "2", Code: domain.ResultAwarded, WinnerName: "ACME SL", WinnerID: "B11111111", AwardedExclVAT: eur("40000"), AwardDate: "2026-03-02"},
			{LotID: "3", Code: domain.ResultVoid},
			{LotID: "4", Code: domain.ResultWithdrawn}, // un desistimiento no es una adjudicación
		}, "Ayuntamiento de Girona"))
	type fila struct {
		lote, resultado, clave, nif string
		baja, presupuesto           *string
	}
	leer := func() map[string]fila {
		rows, err := pool.Query(ctx, `SELECT lote, resultado, adjudicatario_clave, adjudicatario_nif, baja::text, presupuesto_sin_iva::text FROM adjudicaciones`)
		if err != nil {
			t.Fatal(err)
		}
		defer rows.Close()
		out := map[string]fila{}
		for rows.Next() {
			var f fila
			if err := rows.Scan(&f.lote, &f.resultado, &f.clave, &f.nif, &f.baja, &f.presupuesto); err != nil {
				t.Fatal(err)
			}
			out[f.lote] = f
		}
		return out
	}
	got := leer()
	if len(got) != 3 {
		t.Fatalf("esperaba 3 adjudicaciones (lotes 1, 2 y 3), hay %d: %+v", len(got), got)
	}
	if f := got["1"]; f.resultado != "adjudicado" || f.clave != "B11111111" || f.nif != "B11111111" || f.baja == nil || *f.baja != "0.100000" {
		t.Fatalf("lote 1: %+v (baja esperada 0.1)", f)
	}
	if f := got["2"]; f.baja == nil || *f.baja != "0.200000" {
		t.Fatalf("lote 2: baja esperada 0.2, %+v", f)
	}
	if f := got["3"]; f.resultado != "desierto" || f.clave != "" || f.baja != nil {
		t.Fatalf("lote 3: %+v", f)
	}

	// Una versión nueva reemplaza las adjudicaciones; los identificadores son estables.
	var id1 string
	_ = pool.QueryRow(ctx, `SELECT id::text FROM adjudicaciones WHERE lote = '1'`).Scan(&id1)
	l := expedienteConResultados("a/1", nil, "150000", []domain.Result{{LotID: "1", Code: domain.ResultFormalized, WinnerName: "OTRA SA", WinnerID: "A22222222", AwardedExclVAT: eur("75000")}}, "Ayuntamiento de Girona")
	l.Updated = t0.Add(time.Hour)
	proyectar(t, st, "a/1", 2, l)
	got = leer()
	if len(got) != 1 || got["1"].clave != "A22222222" {
		t.Fatalf("tras la v2: %+v", got)
	}
	var id2 string
	_ = pool.QueryRow(ctx, `SELECT id::text FROM adjudicaciones WHERE lote = '1'`).Scan(&id2)
	if id1 != id2 {
		t.Fatalf("el identificador de la adjudicación debe ser estable: %s ≠ %s", id1, id2)
	}
	// Sin lotes, el presupuesto del expediente vale para la única adjudicación: baja = 1 − 75000/150000.
	if f := got["1"]; f.baja == nil || *f.baja != "0.500000" {
		t.Fatalf("sin lotes la baja debe salir del presupuesto del expediente: %+v", f)
	}

	// Anular el expediente retira sus adjudicaciones del análisis de mercado.
	ev := ingest.Event{Source: "placsp-643", SourceID: "a/1", Version: 3, RawSHA256: "sha", RawKey: "clave"}
	if ok, err := st.AnularExpediente(ctx, ev, &domain.Baja{Source: "placsp-643", Ref: "a/1", When: t0.Add(2 * time.Hour), Kind: "ANULADA"}); err != nil || !ok {
		t.Fatalf("anular: %v %v", ok, err)
	}
	if got = leer(); len(got) != 0 {
		t.Fatalf("un expediente anulado no deja adjudicaciones: %+v", got)
	}
}

func TestAdjudicacionesConVariosAdjudicatariosEnUnLoteNoCalculanBaja(t *testing.T) {
	pool, st := conectar(t)
	proyectar(t, st, "b/1", 1, expedienteConResultados("b/1", nil, "100000", []domain.Result{
		{Code: domain.ResultFormalized, WinnerName: "UNO SL", WinnerID: "B00000001", AwardedExclVAT: eur("30000")},
		{Code: domain.ResultFormalized, WinnerName: "DOS SL", WinnerID: "B00000002", AwardedExclVAT: eur("40000")},
		{Code: domain.ResultFormalized, WinnerName: "Ana Pérez", WinnerID: "****5768*", AwardedExclVAT: eur("1000")},
	}, "Ayuntamiento de Girona"))
	var n, conBaja int
	var claves []string
	if err := pool.QueryRow(context.Background(), `SELECT count(*), count(baja), array_agg(adjudicatario_clave ORDER BY n) FROM adjudicaciones`).Scan(&n, &conBaja, &claves); err != nil {
		t.Fatal(err)
	}
	if n != 3 || conBaja != 0 {
		t.Fatalf("n=%d conBaja=%d: con varios adjudicatarios en el mismo lote el presupuesto no se puede repartir", n, conBaja)
	}
	if claves[2] != "n:ana pérez" {
		t.Fatalf("una persona física con el NIF tapado se identifica por el nombre, no por el NIF tapado: %q", claves[2])
	}
}

func ptr[T any](v T) *T { return &v }

// Con las muestras reales de la fuente: cada resultado adjudicado, formalizado o desierto da una fila, y las que traen presupuesto del lote
// (o del expediente, si no hay lotes) calculan la baja, que nunca sale de [0, 1].
func TestAdjudicacionesConMuestrasReales(t *testing.T) {
	pool, st := conectar(t)
	ctx := context.Background()
	esperadas := 0
	for _, f := range []string{"placsp_643/licitacionesPerfilesContratanteCompleto3_20261026T103532Z.atom", "placsp_1044/extracto_PlataformasAgregadasSinMenores_20261026.atom"} {
		fh, err := os.Open("../../../testdata/" + f)
		if err != nil {
			t.Fatal(err)
		}
		fuente := "placsp-643"
		if strings.HasPrefix(f, "placsp_1044") {
			fuente = "placsp-1044"
		}
		_, err = placsp.ParseFeed(fh, placsp.Options{Source: fuente}, func(r placsp.Record) error {
			if r.Licitacion == nil {
				return nil
			}
			for _, x := range r.Licitacion.Results {
				if x.Code == domain.ResultAwarded || x.Code == domain.ResultFormalized || x.Code == domain.ResultVoid {
					esperadas++
				}
			}
			ev := ingest.Event{Source: fuente, SourceID: r.Licitacion.SourceID, Version: 1, RawSHA256: "ab", RawKey: "k"}
			_, err := st.UpsertExpediente(ctx, ev, r.Licitacion)
			return err
		})
		_ = fh.Close()
		if err != nil {
			t.Fatal(err)
		}
	}
	var n, conImporte, conBaja, fuera int
	if err := pool.QueryRow(ctx, `SELECT count(*), count(importe_sin_iva), count(baja), count(*) FILTER (WHERE baja < 0 OR baja > 1) FROM adjudicaciones`).Scan(&n, &conImporte, &conBaja, &fuera); err != nil {
		t.Fatal(err)
	}
	if esperadas == 0 || n != esperadas {
		t.Fatalf("adjudicaciones proyectadas = %d, resultados en las muestras = %d", n, esperadas)
	}
	t.Logf("%d adjudicaciones; %d con importe; %d con baja; %d con baja fuera de [0, 1]", n, conImporte, conBaja, fuera)
	if fuera != 0 {
		t.Fatalf("hay %d bajas fuera de [0, 1]", fuera)
	}
	if conImporte == 0 {
		t.Fatal("ninguna adjudicación con importe")
	}
}

func TestAdjudicacionPorEncimaDelPresupuestoNoTieneBaja(t *testing.T) {
	pool, st := conectar(t)
	proyectar(t, st, "c/1", 1, expedienteConResultados("c/1", nil, "85800", []domain.Result{
		{Code: domain.ResultFormalized, WinnerName: "UNO SL", WinnerID: "B00000001", AwardedExclVAT: eur("343200")},
	}, "Ayuntamiento de Girona"))
	var baja *string
	if err := pool.QueryRow(context.Background(), `SELECT baja::text FROM adjudicaciones`).Scan(&baja); err != nil || baja != nil {
		t.Fatalf("baja = %v, %v: adjudicar más que el presupuesto no es una baja", baja, err)
	}
}
