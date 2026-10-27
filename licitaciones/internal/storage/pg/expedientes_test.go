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
