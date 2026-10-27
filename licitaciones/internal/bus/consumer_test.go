package bus

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

func esperar(t *testing.T, cond func() bool, qué string) {
	t.Helper()
	for fin := time.Now().Add(20 * time.Second); time.Now().Before(fin); time.Sleep(50 * time.Millisecond) {
		if cond() {
			return
		}
	}
	t.Fatalf("no ocurrió a tiempo: %s", qué)
}

func TestConsumirReintentaLoTransitorioYDescartaLoPermanente(t *testing.T) {
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
	var ok, flaky, perm atomic.Int32
	var transitorios atomic.Int32
	done := make(chan error, 1)
	go func() {
		done <- Consume(ctx, nc, func(_ context.Context, e ingest.Event) error {
			switch e.ID {
			case "bueno":
				ok.Add(1)
				return nil
			case "flaky": // falla la primera vez
				flaky.Add(1)
				if transitorios.Add(1) == 1 {
					return errors.New("base caída")
				}
				return nil
			default: // permanente: no se reintenta
				perm.Add(1)
				return ErrPermanent
			}
		}, ConsumerOptions{Durable: "prueba", AckWait: 5 * time.Second})
	}()
	for _, id := range []string{"bueno", "flaky", "malo"} {
		if err := p.Publish(ctx, evento(id)); err != nil {
			t.Fatal(err)
		}
	}
	esperar(t, func() bool { return ok.Load() == 1 && flaky.Load() == 2 && perm.Load() >= 1 }, "bueno, flaky reintentado y malo visto")
	time.Sleep(3 * time.Second) // si el permanente se reintentara, volvería a verse
	if perm.Load() != 1 {
		t.Fatalf("un fallo permanente no debe reintentarse (visto %d veces)", perm.Load())
	}
	cancel()
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

func TestDecodeRechazaMensajesIncompletos(t *testing.T) {
	for nombre, data := range map[string]string{"no json": `{`, "sin id": `{"tipo":"licitacion.nueva","fuente":"a","clave_original":"k","version":1}`, "versión 0": `{"id":"x","tipo":"t","fuente":"a","clave_original":"k","version":0}`} {
		if _, err := Decode([]byte(data)); !errors.Is(err, ErrPermanent) {
			t.Errorf("%s: error = %v", nombre, err)
		}
	}
	got, err := Decode([]byte(`{"id":"x","tipo":"licitacion.nueva","fuente":"a","id_origen":"i","version":2,"sha256_original":"s","clave_original":"k"}`))
	if err != nil || got.ID != "x" || got.Version != 2 || got.RawKey != "k" {
		t.Fatalf("decode = %+v, %v", got, err)
	}
}
