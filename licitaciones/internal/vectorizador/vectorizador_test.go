package vectorizador

import (
	"context"
	"errors"
	"log/slog"
	"sync"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

type almacenFalso struct {
	mu        sync.Mutex
	pendiente []pg.PorVectorizar
	guardados map[string]bool
	hayVector bool
}

func (a *almacenFalso) PrepararVectores(context.Context) (bool, error) { return a.hayVector, nil }
func (a *almacenFalso) PorVectorizar(_ context.Context, n int) ([]pg.PorVectorizar, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if n > len(a.pendiente) {
		n = len(a.pendiente)
	}
	return append([]pg.PorVectorizar(nil), a.pendiente[:n]...), nil
}
func (a *almacenFalso) GuardarVectores(_ context.Context, _ string, ids []string, _ [][]float32) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	for _, id := range ids {
		a.guardados[id] = true
	}
	a.pendiente = a.pendiente[len(ids):]
	return nil
}

type embebedorFalso struct{ fallos int }

func (e *embebedorFalso) Vectores(_ context.Context, t []string) ([][]float32, error) {
	if e.fallos > 0 {
		e.fallos--
		return nil, errors.New("ollama caído")
	}
	return make([][]float32, len(t)), nil
}

func lanzar(t *testing.T, a *almacenFalso, e *embebedorFalso) (cancel func(), hecho chan struct{}) {
	ctx, cancel := context.WithCancel(context.Background())
	hecho = make(chan struct{})
	go func() {
		_ = Run(ctx, a, e, Opciones{Modelo: "m", Lote: 2, Reposo: 5 * time.Millisecond, Reintento: 5 * time.Millisecond}, slog.New(slog.DiscardHandler))
		close(hecho)
	}()
	return cancel, hecho
}

func TestVectorizaTodoYSeRecuperaDeUnError(t *testing.T) {
	a := &almacenFalso{hayVector: true, guardados: map[string]bool{}}
	for _, id := range []string{"1", "2", "3", "4", "5"} {
		a.pendiente = append(a.pendiente, pg.PorVectorizar{ID: id, Texto: "t" + id})
	}
	cancel, hecho := lanzar(t, a, &embebedorFalso{fallos: 2})
	defer cancel()
	for i := 0; i < 200; i++ {
		a.mu.Lock()
		n := len(a.guardados)
		a.mu.Unlock()
		if n == 5 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	cancel()
	<-hecho
	if len(a.guardados) != 5 {
		t.Fatalf("guardados = %d, esperaba 5", len(a.guardados))
	}
}

func TestSinPgvectorNoHaceNadaYSePuedeParar(t *testing.T) {
	a := &almacenFalso{hayVector: false, guardados: map[string]bool{}, pendiente: []pg.PorVectorizar{{ID: "1", Texto: "x"}}}
	cancel, hecho := lanzar(t, a, &embebedorFalso{})
	time.Sleep(50 * time.Millisecond)
	cancel()
	select {
	case <-hecho:
	case <-time.After(2 * time.Second):
		t.Fatal("no se detuvo al cancelar")
	}
	if len(a.guardados) != 0 {
		t.Fatal("sin pgvector no debe guardar nada")
	}
}
