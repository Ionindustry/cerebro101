package pg

import (
	"context"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

func licitacion(id, titulo, estado string, updated time.Time) *domain.Licitacion {
	return &domain.Licitacion{
		Source: "placsp-643", SourceID: id, NumericID: "42", Updated: updated, Expediente: "EXP-1", Status: estado, Title: titulo,
		Organism: domain.Organization{Name: "Ayuntamiento de Girona", NIF: "P1708500E"}, Procedure: "1",
		CPV: []string{"72000000"}, NUTS: []string{"ES512"}, TenderDeadline: &updated,
		EstimatedValue: &domain.Money{Value: "125000.50", Currency: "EUR"}, BaseBudgetExclVAT: &domain.Money{Value: "no-es-un-numero", Currency: "EUR"},
	}
}

func TestUpsertExpedienteProyectaYSoloAvanza(t *testing.T) {
	pool, st := conectar(t)
	ctx := context.Background()
	ev := func(v int) ingest.Event {
		return ingest.Event{Source: "placsp-643", SourceID: "x/42", Version: v, RawSHA256: "sha", RawKey: "clave"}
	}
	ok, err := st.UpsertExpediente(ctx, ev(1), licitacion("x/42", "Servicio de mantenimiento de software", "PUB", t0))
	if err != nil || !ok {
		t.Fatalf("alta: %v %v", ok, err)
	}
	// Una versión anterior o repetida no toca nada.
	for _, v := range []int{1, 0} {
		if v == 0 {
			continue
		}
		if ok, err := st.UpsertExpediente(ctx, ev(v), licitacion("x/42", "otro título", "PUB", t0)); err != nil || ok {
			t.Fatalf("reentrega v%d: %v %v", v, ok, err)
		}
	}
	// La versión siguiente actualiza.
	if ok, err := st.UpsertExpediente(ctx, ev(2), licitacion("x/42", "Servicio de mantenimiento de software y soporte", "ADJ", t0.Add(time.Hour))); err != nil || !ok {
		t.Fatalf("v2: %v %v", ok, err)
	}
	var titulo, estado, proc, moneda string
	var valor string
	var sinIVA *string
	var n int
	if err := pool.QueryRow(ctx, `SELECT titulo, estado, procedimiento, moneda, valor_estimado::text, presupuesto_sin_iva::text, version_entidad,
		(SELECT count(*) FROM expedientes) FROM expedientes WHERE id_origen = 'x/42'`).Scan(&titulo, &estado, &proc, &moneda, &valor, &sinIVA, new(int), &n); err != nil {
		t.Fatal(err)
	}
	if titulo != "Servicio de mantenimiento de software y soporte" || estado != "adjudicada" || proc != "abierto" || moneda != "EUR" || valor != "125000.5000" || n != 1 {
		t.Fatalf("fila inesperada: %q %q %q %q %q n=%d", titulo, estado, proc, moneda, valor, n)
	}
	if sinIVA != nil {
		t.Fatalf("un importe ilegible debe quedar en NULL, no %q", *sinIVA)
	}
}

func TestBusquedaDeTextoEnCastellanoYCatalan(t *testing.T) {
	pool, st := conectar(t)
	ctx := context.Background()
	for i, titulo := range []string{"Servicio de mantenimiento de sistemas de videovigilancia", "Subministrament de càmeres de vigilància"} {
		id := string(rune('a' + i))
		if _, err := st.UpsertExpediente(ctx, ingest.Event{Source: "placsp-643", SourceID: id, Version: 1, RawSHA256: "s", RawKey: "k"}, licitacion(id, titulo, "PUB", t0)); err != nil {
			t.Fatal(err)
		}
	}
	cuenta := func(q string) int {
		var n int
		if err := pool.QueryRow(ctx, `SELECT count(*) FROM expedientes WHERE busqueda @@ websearch_to_tsquery('spanish', $1) OR busqueda @@ websearch_to_tsquery('catalan', $1)`, q).Scan(&n); err != nil {
			t.Fatal(err)
		}
		return n
	}
	if cuenta("mantenimiento videovigilancia") != 1 || cuenta("càmeres") != 1 || cuenta("Girona") != 2 || cuenta("inexistente") != 0 {
		t.Fatalf("búsqueda inesperada: %d %d %d %d", cuenta("mantenimiento videovigilancia"), cuenta("càmeres"), cuenta("Girona"), cuenta("inexistente"))
	}
}

func TestAnularExpediente(t *testing.T) {
	pool, st := conectar(t)
	ctx := context.Background()
	ev := func(v int) ingest.Event {
		return ingest.Event{Source: "placsp-643", SourceID: "r/1", Version: v, RawSHA256: "s", RawKey: "k"}
	}
	baja := &domain.Baja{Source: "placsp-643", Ref: "r/1", When: t0.Add(time.Hour), Kind: "ANULADA"}
	// De algo que nunca se vio no hay nada que anular.
	if ok, err := st.AnularExpediente(ctx, ev(2), baja); err != nil || ok {
		t.Fatalf("baja sin expediente: %v %v", ok, err)
	}
	if _, err := st.UpsertExpediente(ctx, ev(1), licitacion("r/1", "Algo", "PUB", t0)); err != nil {
		t.Fatal(err)
	}
	if ok, err := st.AnularExpediente(ctx, ev(2), baja); err != nil || !ok {
		t.Fatalf("baja: %v %v", ok, err)
	}
	var estado, status string
	if err := pool.QueryRow(ctx, `SELECT estado, documento->>'status' FROM expedientes WHERE id_origen = 'r/1'`).Scan(&estado, &status); err != nil || estado != "anulada" || status != "ANUL" {
		t.Fatalf("estado = %q, status = %q, %v", estado, status, err)
	}
	if n, err := st.ContarExpedientes(ctx); err != nil || n != 1 {
		t.Fatalf("contar = %d, %v", n, err)
	}
}

// Una licitación «publicada» sigue así en la plataforma mucho después de acabar el plazo: al leer, con el plazo vencido es «cerrada» (se muestra y se filtra
// como tal); sin plazo o con el plazo por delante sigue «abierta». Una adjudicada o anulada no cambia aunque su plazo sea antiguo.
func TestAbiertaConElPlazoVencidoSeLeeComoCerrada(t *testing.T) {
	_, st := conectar(t)
	ctx := context.Background()
	ahora := time.Now().UTC()
	casos := []struct {
		id, status string
		plazo      *time.Time
		quiero     string
	}{
		{"p/vencida", "PUB", ptr(ahora.Add(-48 * time.Hour)), "cerrada"},
		{"p/vigente", "PUB", ptr(ahora.Add(72 * time.Hour)), "abierta"},
		{"p/sinplazo", "PUB", nil, "abierta"},
		{"p/adjudicada", "ADJ", ptr(ahora.Add(-48 * time.Hour)), "adjudicada"},
		{"p/previa", "PRE", ptr(ahora.Add(-48 * time.Hour)), "anuncio_previo"},
	}
	for _, c := range casos {
		l := licitacion(c.id, "Servicio "+c.id, c.status, ahora)
		l.TenderDeadline = c.plazo
		if _, err := st.UpsertExpediente(ctx, ingest.Event{Source: "placsp-643", SourceID: c.id, Version: 1, RawSHA256: "s", RawKey: "k"}, l); err != nil {
			t.Fatal(err)
		}
	}
	filas, _, _, err := st.Buscar(ctx, Filtro{Limit: 50, Orden: OrdenActualizacion})
	if err != nil {
		t.Fatal(err)
	}
	vistos := map[string]string{}
	for _, f := range filas {
		vistos[f.IDOrigen] = f.Estado
	}
	for _, c := range casos {
		if vistos[c.id] != c.quiero {
			t.Errorf("%s: estado %q, quiero %q", c.id, vistos[c.id], c.quiero)
		}
	}
	ids := func(estado string) map[string]bool {
		fs, _, _, err := st.Buscar(ctx, Filtro{Estados: []string{estado}, Limit: 50, Orden: OrdenActualizacion})
		if err != nil {
			t.Fatal(err)
		}
		m := map[string]bool{}
		for _, f := range fs {
			m[f.IDOrigen] = true
		}
		return m
	}
	if a := ids("abierta"); a["p/vencida"] || !a["p/vigente"] || !a["p/sinplazo"] {
		t.Errorf("filtro abierta: %v", a)
	}
	if c := ids("cerrada"); !c["p/vencida"] || c["p/vigente"] || c["p/adjudicada"] {
		t.Errorf("filtro cerrada: %v", c)
	}
}
