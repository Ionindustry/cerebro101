package bus

import (
	"context"
	"testing"
	"time"

	"github.com/nats-io/nats-server/v2/server"
	"github.com/nats-io/nats.go/jetstream"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

func servidor(t *testing.T) string {
	t.Helper()
	s, err := server.NewServer(&server.Options{Port: -1, JetStream: true, JetStreamMaxStore: 8 << 30, StoreDir: t.TempDir(), NoLog: true, NoSigs: true})
	if err != nil {
		t.Fatal(err)
	}
	go s.Start()
	if !s.ReadyForConnections(10 * time.Second) {
		t.Fatal("el servidor NATS no arrancó")
	}
	t.Cleanup(s.Shutdown)
	return s.ClientURL()
}

func evento(id string) ingest.Event {
	return ingest.Event{ID: id, Type: "licitacion.nueva", Source: "placsp-643", SourceID: "X1", Version: 1, RawSHA256: "ab", RawKey: "k"}
}

func TestSubject(t *testing.T) {
	got, err := Subject(evento("e1"))
	if err != nil || got != "licitacion.nueva.placsp-643" {
		t.Fatalf("asunto = %q, %v", got, err)
	}
	for _, e := range []ingest.Event{{Type: "licitacion.a b", Source: "s"}, {Type: "licitacion.nueva", Source: "a.b"}, {Type: "licitacion.nueva"}} {
		if _, err := Subject(e); err == nil {
			t.Errorf("debía rechazar %+v", e)
		}
	}
}

func TestPublicaYDeduplica(t *testing.T) {
	nc, err := Connect(Config{URL: servidor(t)})
	if err != nil {
		t.Fatal(err)
	}
	defer nc.Close()
	p, err := NewPublisher(nc)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := p.EnsureStream(ctx); err != nil {
		t.Fatal(err)
	}
	if err := p.EnsureStream(ctx); err != nil {
		t.Fatalf("EnsureStream debe ser idempotente: %v", err)
	}
	for i := 0; i < 2; i++ { // el mismo evento dos veces: un solo mensaje
		if err := p.Publish(ctx, evento("e1")); err != nil {
			t.Fatal(err)
		}
	}
	if err := p.Publish(ctx, evento("e2")); err != nil {
		t.Fatal(err)
	}
	js, _ := jetstream.New(nc)
	st, err := js.Stream(ctx, StreamName)
	if err != nil {
		t.Fatal(err)
	}
	info, err := st.Info(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if info.State.Msgs != 2 {
		t.Fatalf("mensajes = %d, quería 2", info.State.Msgs)
	}
}

func TestPublicarSinFlujoFalla(t *testing.T) {
	nc, err := Connect(Config{URL: servidor(t)})
	if err != nil {
		t.Fatal(err)
	}
	defer nc.Close()
	p, _ := NewPublisher(nc)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := p.Publish(ctx, evento("e1")); err == nil {
		t.Fatal("sin flujo no hay PubAck: debía fallar para que el outbox conserve el evento")
	}
}

func TestConnectSinURL(t *testing.T) {
	if _, err := Connect(Config{}); err == nil {
		t.Fatal("debía exigir URL")
	}
}
