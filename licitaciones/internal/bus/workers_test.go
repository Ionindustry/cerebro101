package bus

import (
	"context"
	"fmt"
	"sync/atomic"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

// Con Workers = 4 el consumidor procesa varios eventos a la vez, nunca más de 4, y no pierde ninguno.
func TestConsumirEnParaleloConTope(t *testing.T) {
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
	const n = 24
	for i := 0; i < n; i++ {
		e := evento(fmt.Sprint("e", i))
		e.SourceID = fmt.Sprint("X", i)
		if err := p.Publish(ctx, e); err != nil {
			t.Fatal(err)
		}
	}
	var enMarcha, maximo, hechos atomic.Int32
	vistos := make(chan string, n)
	done := make(chan error, 1)
	inicio := time.Now()
	go func() {
		done <- Consume(ctx, nc, func(_ context.Context, e ingest.Event) error {
			cur := enMarcha.Add(1)
			for {
				m := maximo.Load()
				if cur <= m || maximo.CompareAndSwap(m, cur) {
					break
				}
			}
			time.Sleep(150 * time.Millisecond)
			enMarcha.Add(-1)
			vistos <- e.ID
			hechos.Add(1)
			return nil
		}, ConsumerOptions{Durable: "paralelo", Workers: 4})
	}()
	esperar(t, func() bool { return hechos.Load() == n }, "procesar los 24 eventos")
	dur := time.Since(inicio)
	cancel()
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if m := maximo.Load(); m < 2 || m > 4 {
		t.Fatalf("a la vez: máximo %d, quería entre 2 y 4", m)
	}
	if dur > 24*150*time.Millisecond*3/4 { // en serie serían 3,6 s; con 4 a la vez, bastante menos
		t.Fatalf("no ha ido más rápido que en serie: %v", dur)
	}
	distintos := map[string]bool{}
	for len(vistos) > 0 {
		distintos[<-vistos] = true
	}
	if len(distintos) != n {
		t.Fatalf("eventos distintos procesados = %d, quería %d", len(distintos), n)
	}
}
