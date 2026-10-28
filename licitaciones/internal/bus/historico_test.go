package bus

import (
	"context"
	"sync/atomic"
	"testing"
	"time"

	"github.com/nats-io/nats.go/jetstream"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

func TestElAsuntoDelHistoricoEsOtro(t *testing.T) {
	e := evento("h1")
	e.Backfill = true
	got, err := Subject(e)
	if err != nil || got != "lichist.v1.nueva.placsp-643" {
		t.Fatalf("asunto = %q, %v", got, err)
	}
	vivo, _ := Subject(evento("v1"))
	if vivo != "licitacion.nueva.placsp-643" {
		t.Fatalf("el evento en vivo no cambia: %q", vivo)
	}
}

// El Cerebro consume el flujo LICITACIONES: un evento del histórico no puede aparecer ahí (y sí en LIC_HISTORICO, que solo leen los proyectores).
func TestElHistoricoNoLlegaAlFlujoEnVivo(t *testing.T) {
	nc, err := Connect(Config{URL: servidor(t)})
	if err != nil {
		t.Fatal(err)
	}
	defer nc.Close()
	p, _ := NewPublisher(nc)
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Second)
	defer cancel()
	if err := p.EnsureStream(ctx); err != nil {
		t.Fatal(err)
	}
	hist := evento("h1")
	hist.Backfill = true
	for _, e := range []ingest.Event{evento("v1"), hist} {
		if err := p.Publish(ctx, e); err != nil {
			t.Fatal(err)
		}
	}
	js, _ := jetstream.New(nc)
	for flujo, quiere := range map[string]uint64{StreamName: 1, StreamHistorico: 1} {
		s, err := js.Stream(ctx, flujo)
		if err != nil {
			t.Fatal(err)
		}
		info, _ := s.Info(ctx)
		if info.State.Msgs != quiere {
			t.Fatalf("%s tiene %d mensajes, quería %d", flujo, info.State.Msgs, quiere)
		}
		if flujo == StreamHistorico && info.Config.Discard != jetstream.DiscardNew {
			t.Fatalf("el flujo del histórico debe rechazar lo nuevo cuando se llena (así no se pierde nada), no descartar lo viejo")
		}
	}

	var vivos, historicos atomic.Int32
	var vistoHist atomic.Bool
	go func() {
		_ = Consume(ctx, nc, func(_ context.Context, e ingest.Event) error { vivos.Add(1); return nil }, ConsumerOptions{Durable: "prueba-vivo"})
	}()
	go func() {
		_ = Consume(ctx, nc, func(_ context.Context, e ingest.Event) error {
			historicos.Add(1)
			vistoHist.Store(e.Backfill)
			return nil
		}, ConsumerOptions{Durable: "prueba-hist", Stream: StreamHistorico})
	}()
	esperar(t, func() bool { return vivos.Load() == 1 && historicos.Load() == 1 }, "cada consumidor recibe solo lo suyo")
	time.Sleep(300 * time.Millisecond)
	if vivos.Load() != 1 || historicos.Load() != 1 || !vistoHist.Load() {
		t.Fatalf("vivos=%d historicos=%d, el evento histórico debe llevar Backfill", vivos.Load(), historicos.Load())
	}
}
