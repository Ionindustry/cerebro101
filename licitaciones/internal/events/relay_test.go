package events

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

// fakeDrainer entrega las tandas y errores preparados, en orden, y cancela el contexto cuando se acaban.
type fakeDrainer struct {
	pasos  []paso
	i      int
	cancel context.CancelFunc
	vistos []int
}

type paso struct {
	n   int
	err error
}

func (f *fakeDrainer) Drain(_ context.Context, limit int, _ func(context.Context, ingest.Event) error) (int, error) {
	f.vistos = append(f.vistos, limit)
	if f.i >= len(f.pasos) {
		f.cancel()
		return 0, nil
	}
	p := f.pasos[f.i]
	f.i++
	return p.n, p.err
}

func ejecutar(t *testing.T, pasos []paso, o Options) (*fakeDrainer, []time.Duration) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	d := &fakeDrainer{pasos: pasos, cancel: cancel}
	var esperas []time.Duration
	o.Sleep = func(_ context.Context, w time.Duration) error { esperas = append(esperas, w); return nil }
	if err := Run(ctx, d, func(context.Context, ingest.Event) error { return nil }, o); err != nil {
		t.Fatal(err)
	}
	return d, esperas
}

func TestUnaTandaLlenaSigueSinEsperar(t *testing.T) {
	d, esperas := ejecutar(t, []paso{{n: 3}, {n: 3}, {n: 1}}, Options{Batch: 3, Interval: time.Second})
	if len(esperas) != 2 || esperas[0] != time.Second { // tras la tanda de 1 y tras la vacía que cancela
		t.Fatalf("esperas = %v", esperas)
	}
	if d.vistos[0] != 3 {
		t.Fatalf("tamaño de tanda = %d", d.vistos[0])
	}
}

func TestLosErroresSeReintentanConEsperaCrecienteYTope(t *testing.T) {
	caida := errors.New("caído")
	_, esperas := ejecutar(t, []paso{{err: caida}, {err: caida}, {err: caida}, {err: caida}, {n: 0}}, Options{Interval: time.Second, MaxBackoff: 5 * time.Second})
	want := []time.Duration{time.Second, 2 * time.Second, 4 * time.Second, 5 * time.Second, time.Second}
	if len(esperas) < len(want) {
		t.Fatalf("esperas = %v", esperas)
	}
	for i, w := range want {
		if esperas[i] != w {
			t.Fatalf("espera %d = %v, quería %v (todas: %v)", i, esperas[i], w, esperas)
		}
	}
}

func TestTrasRecuperarseLaEsperaVuelveAlIntervalo(t *testing.T) {
	_, esperas := ejecutar(t, []paso{{err: errors.New("x")}, {err: errors.New("x")}, {n: 0}}, Options{Interval: time.Second})
	if esperas[2] != time.Second {
		t.Fatalf("esperas = %v", esperas)
	}
}

func TestCancelarDevuelveNil(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := Run(ctx, &fakeDrainer{cancel: cancel}, nil, Options{}); err != nil {
		t.Fatalf("error = %v", err)
	}
}

func TestPausaSeInterrumpeConElContexto(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := pause(ctx, time.Hour); !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v", err)
	}
	if err := pause(context.Background(), time.Millisecond); err != nil {
		t.Fatal(err)
	}
}
