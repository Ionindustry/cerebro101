package api

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

type pagina struct {
	Items []Resumen `json:"items"`
	Sig   *string   `json:"siguiente_cursor"`
	Total struct {
		Valor    int    `json:"valor"`
		Relacion string `json:"relacion"`
	} `json:"total"`
}

// conPostgres monta la API sobre una base real (esquema propio) con unos expedientes de prueba. Sin LICITACIONES_TEST_PG se omite.
func conPostgres(t *testing.T) (*httptest.Server, *pg.Store, *pgxpool.Pool) {
	t.Helper()
	dsn := os.Getenv("LICITACIONES_TEST_PG")
	if dsn == "" {
		t.Skip("sin LICITACIONES_TEST_PG")
	}
	ctx := context.Background()
	admin, err := pg.Connect(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	schema := fmt.Sprintf("lic_api_%d", time.Now().UnixNano())
	if _, err := admin.Exec(ctx, "CREATE SCHEMA "+schema); err != nil {
		t.Fatal(err)
	}
	cfg, _ := pgxpool.ParseConfig(dsn)
	cfg.ConnConfig.RuntimeParams["search_path"] = schema
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		pool.Close()
		_, _ = admin.Exec(context.Background(), "DROP SCHEMA "+schema+" CASCADE")
		admin.Close()
	})
	if err := pg.Migrate(ctx, pool); err != nil {
		t.Fatal(err)
	}
	st := pg.New(pool)
	siembra(t, st)
	_, ts := servidor(t, st)
	return ts, st, pool
}

func siembra(t *testing.T, st *pg.Store) {
	t.Helper()
	base := time.Date(2026, 10, 1, 10, 0, 0, 0, time.UTC)
	datos := []struct {
		titulo, estado, cpv, nuts, valor string
		plazo                            int // días desde base; 0 = sin plazo
	}{
		{"Mantenimiento de sistemas de videovigilancia", "PUB", "35125300", "ES512", "100000", 10},
		{"Subministrament de càmeres de vigilància", "PUB", "35125300", "ES511", "250000", 5},
		{"Desarrollo de software de gestión", "PUB", "72262000", "ES512", "75000.50", 0},
		{"Servicios de mantenimiento de software", "EV", "72267000", "ES300", "", 20},
		{"Obras de reforma del edificio municipal", "ADJ", "45000000", "ES512", "900000", 0},
		{"Suministro de mobiliario", "PUB", "39100000", "ES613", "30000", 15},
		{"Soporte de infraestructura de red", "PUB", "72000000", "ES512", "100000", 7},
	}
	for i, d := range datos {
		l := &domain.Licitacion{
			Source: "placsp-643", SourceID: fmt.Sprintf("https://x.test/%d", i), NumericID: fmt.Sprint(i), Updated: base.Add(time.Duration(i) * time.Hour),
			Expediente: fmt.Sprintf("EXP-%d", i), Status: d.estado, Title: d.titulo, Organism: domain.Organization{Name: "Ayuntamiento de Girona", NIF: "P1708500E"},
			Procedure: "1", CPV: []string{d.cpv}, NUTS: []string{d.nuts}, Link: fmt.Sprintf("https://x.test/%d", i),
		}
		if d.valor != "" {
			l.EstimatedValue = &domain.Money{Value: d.valor, Currency: "EUR"}
		}
		if d.plazo > 0 {
			p := base.AddDate(0, 0, d.plazo)
			l.TenderDeadline = &p
		}
		if d.estado == "ADJ" {
			l.Lots = []domain.Lot{{ID: "1", Name: "Lote único", BaseBudgetExclVAT: &domain.Money{Value: "1000000", Currency: "EUR"}}}
			l.Results = []domain.Result{{LotID: "1", Code: domain.ResultAwarded, WinnerName: "Constructora SA", WinnerID: "A12345678", WinnerScheme: "NIF",
				AwardedExclVAT: &domain.Money{Value: "900000", Currency: "EUR"}}}
		}
		ev := ingest.Event{Source: "placsp-643", SourceID: l.SourceID, Version: 1, RawSHA256: "ab", RawKey: "k"}
		if _, err := st.UpsertExpediente(context.Background(), ev, l); err != nil {
			t.Fatal(err)
		}
	}
}

// recorrer lee todas las páginas de una consulta con el límite dado: devuelve los elementos en el orden servido y el total. Falla si algún
// elemento se repite entre páginas o si el total cambia.
func recorrer(t *testing.T, ts *httptest.Server, query string, limit int) ([]Resumen, int) {
	t.Helper()
	var out []Resumen
	vistos := map[string]bool{}
	cursor, total := "", -1
	for paginas := 0; paginas < 50; paginas++ {
		q := query
		if q != "" {
			q += "&"
		}
		q += fmt.Sprintf("limit=%d", limit)
		if cursor != "" {
			q += "&cursor=" + url.QueryEscape(cursor)
		}
		res := get(t, ts, "/api/v1/tenders?"+q, token)
		if res.StatusCode != http.StatusOK {
			t.Fatalf("%s: %d", q, res.StatusCode)
		}
		var p pagina
		decode(t, res, &p)
		if total >= 0 && p.Total.Valor != total {
			t.Fatalf("el total cambió entre páginas: %d → %d", total, p.Total.Valor)
		}
		total = p.Total.Valor
		for _, it := range p.Items {
			if vistos[it.ID] {
				t.Fatalf("%s: elemento repetido entre páginas: %s", query, it.Titulo)
			}
			vistos[it.ID] = true
			out = append(out, it)
		}
		if p.Sig == nil {
			return out, total
		}
		cursor = *p.Sig
	}
	t.Fatal("demasiadas páginas")
	return nil, 0
}

func titulos(rs []Resumen) []string {
	var out []string
	for _, r := range rs {
		out = append(out, r.Titulo)
	}
	return out
}

func TestPaginacionPorCursorEnTodosLosOrdenes(t *testing.T) {
	ts, _, _ := conPostgres(t)
	for _, orden := range []string{"actualizacion", "plazo", "importe"} {
		for _, limit := range []int{1, 2, 3, 100} {
			got, total := recorrer(t, ts, "orden="+orden, limit)
			if len(got) != 7 || total != 7 {
				t.Fatalf("orden %s limit %d: %d elementos, total %d (quería 7)", orden, limit, len(got), total)
			}
		}
	}
	// El orden en sí: más recientes primero, plazo más próximo primero (los sin plazo al final), mayor importe primero (sin importe al final).
	got, _ := recorrer(t, ts, "orden=actualizacion", 2)
	for i := 1; i < len(got); i++ {
		if got[i].ActualizadaEn.After(got[i-1].ActualizadaEn) {
			t.Fatalf("actualizacion fuera de orden en %d", i)
		}
	}
	got, _ = recorrer(t, ts, "orden=plazo", 2)
	if got[0].Titulo != "Subministrament de càmeres de vigilància" || got[len(got)-1].PlazoPresentacion != nil {
		t.Fatalf("plazo: %v", titulos(got))
	}
	got, _ = recorrer(t, ts, "orden=importe", 2)
	if got[0].Titulo != "Obras de reforma del edificio municipal" || got[len(got)-1].Importe != nil {
		t.Fatalf("importe: %v", titulos(got))
	}
}

func TestBusquedaPorTextoYRelevancia(t *testing.T) {
	ts, _, _ := conPostgres(t)
	got, total := recorrer(t, ts, "q="+url.QueryEscape("mantenimiento software"), 1)
	if total == 0 || got[0].Titulo != "Servicios de mantenimiento de software" {
		t.Fatalf("relevancia: %v (total %d)", titulos(got), total)
	}
	// Catalán y castellano a la vez; paginando de uno en uno no se pierde nada.
	got, _ = recorrer(t, ts, "q="+url.QueryEscape("vigilància"), 1)
	if len(got) != 1 || !strings.Contains(got[0].Titulo, "càmeres") {
		t.Fatalf("catalán: %v", titulos(got))
	}
	if got, _ := recorrer(t, ts, "q=inexistente", 5); len(got) != 0 {
		t.Fatalf("sin coincidencias: %v", titulos(got))
	}
}

func TestFiltros(t *testing.T) {
	ts, _, _ := conPostgres(t)
	cuenta := func(q string) int { _, n := recorrer(t, ts, q, 3); return n }
	casos := map[string]int{
		"cpv=72":                                3, // prefijo de 2 cifras: 72262000, 72267000, 72000000
		"cpv=35125300":                          2,
		"cpv=35,45":                             3,
		"nuts=ES51":                             5, // ES512 ×4 y ES511
		"nuts=ES511":                            1,
		"estado=adjudicada":                     1,
		"estado=abierta&estado=cerrada":         6,
		"importe_min=100000":                    4, // 100000, 250000, 900000, 100000
		"importe_min=100000&importe_max=250000": 3,
		"comprador=nif:P1708500E":               7,
		"comprador=nif:A00000000":               0,
		"fuente=placsp":                         7,
		"fuente=ted":                            0,
		"fuente=placsp&id_origen=https://x.test/3":  1, // el identificador de origen de un expediente concreto
		"fuente=placsp&id_origen=https://x.test/99": 0,
		"fuente=ted&id_origen=https://x.test/3":     0, // otra fuente no lo ve: el identificador solo es único dentro de la suya
		"procedimiento=abierto":                     7,
		"actualizada_desde=2026-10-01T14:00:00Z":    3, // las de las 14:00, 15:00 y 16:00
		"plazo_hasta=2026-10-09T00:00:00Z":          2, // los plazos del 6 y del 8
	}
	for q, want := range casos {
		if got := cuenta(q); got != want {
			t.Errorf("%s: %d resultados, quería %d", q, got, want)
		}
	}
	// Los valores van como parámetros: un intento de inyección es texto inocuo o un 400, nunca SQL.
	for _, q := range []string{"q=" + url.QueryEscape("'; DROP TABLE expedientes; --"), "cpv=" + url.QueryEscape("72%' OR '1'='1")} {
		res := get(t, ts, "/api/v1/tenders?"+q, token)
		if res.StatusCode != 200 && res.StatusCode != 400 {
			t.Errorf("%s: %d", q, res.StatusCode)
		}
	}
	if n := cuenta(""); n != 7 {
		t.Fatalf("la tabla debe seguir intacta: %d", n)
	}
}

func TestFichaConEtagYAdjudicacion(t *testing.T) {
	ts, _, _ := conPostgres(t)
	got, _ := recorrer(t, ts, "estado=adjudicada", 5)
	if len(got) != 1 {
		t.Fatal("falta el expediente adjudicado")
	}
	res := get(t, ts, "/api/v1/tenders/"+got[0].ID, token)
	if res.StatusCode != 200 || res.Header.Get("ETag") == "" {
		t.Fatalf("ficha: %d etag=%q", res.StatusCode, res.Header.Get("ETag"))
	}
	var f Ficha
	decode(t, res, &f)
	if f.Estado != "adjudicada" || len(f.Lotes) != 1 || len(f.Adjudicacion) != 1 || f.Evidencia.ClaveRaw != "k" || f.Evidencia.SHA256 != "ab" {
		t.Fatalf("ficha inesperada: %+v", f)
	}
	a := f.Adjudicacion[0]
	if a.Resultado != "adjudicado" || a.Adjudicatario == nil || a.Adjudicatario.NIF == nil || *a.Adjudicatario.NIF != "A12345678" ||
		a.Baja == nil || *a.Baja < 0.0999 || *a.Baja > 0.1001 {
		t.Fatalf("adjudicación inesperada: %+v baja=%v", a, a.Baja)
	}
	if !slices.ContainsFunc(f.Importes, func(i Importe) bool {
		return i.Significado == "valor_estimado" && i.Valor == "900000.0000" || i.Valor == "900000"
	}) {
		t.Fatalf("importes: %+v", f.Importes)
	}
	// Con el ETag actual, 304 sin cuerpo.
	if res := get(t, ts, "/api/v1/tenders/"+got[0].ID, token, "If-None-Match", res.Header.Get("ETag")); res.StatusCode != http.StatusNotModified {
		t.Fatalf("If-None-Match: %d", res.StatusCode)
	}
	// Mayúsculas en el id también valen.
	if res := get(t, ts, "/api/v1/tenders/"+strings.ToUpper(got[0].ID), token); res.StatusCode != 200 {
		t.Fatalf("id en mayúsculas: %d", res.StatusCode)
	}
}

func TestEstadoDelMotorConPuntoDeControl(t *testing.T) {
	ts, st, _ := conPostgres(t)
	ahora := time.Now().UTC()
	for _, c := range []struct {
		edad time.Duration
		want string
	}{{30 * time.Minute, "ok"}, {3 * time.Hour, "degradado"}, {8 * time.Hour, "caido"}} {
		if err := st.SaveCheckpoint(context.Background(), "placsp-643", ingest.Checkpoint{LastRun: ahora.Add(-c.edad)}); err != nil {
			t.Fatal(err)
		}
		res := get(t, ts, "/api/v1/ops/status", token)
		var out struct {
			Estado  string         `json:"estado"`
			Fuentes []estadoFuente `json:"fuentes"`
			Motivos []motivo       `json:"motivos"`
		}
		decode(t, res, &out)
		if res.StatusCode != 200 || out.Estado != c.want || len(out.Fuentes) != 1 || out.Fuentes[0].Fuente != "placsp" || out.Fuentes[0].Documentos != 7 {
			t.Fatalf("edad %s: %d %+v", c.edad, res.StatusCode, out)
		}
	}
	// Un punto de control vacío (la última ejecución no terminó) es «sin ingesta completa», no una fecha del año 1.
	if err := st.SaveCheckpoint(context.Background(), "placsp-643", ingest.Checkpoint{}); err != nil {
		t.Fatal(err)
	}
	res := get(t, ts, "/api/v1/ops/status", token)
	var out struct {
		Estado  string         `json:"estado"`
		Fuentes []estadoFuente `json:"fuentes"`
	}
	decode(t, res, &out)
	if out.Estado != "degradado" || out.Fuentes[0].UltimaIngestaCorrecta != nil {
		t.Fatalf("punto de control vacío: %+v", out)
	}
}
