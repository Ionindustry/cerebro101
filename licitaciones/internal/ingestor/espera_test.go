package ingestor

import (
	"context"
	"errors"
	"log/slog"
	"sync/atomic"
	"testing"
	"time"
)

type peticionesFalsas struct {
	llamadas atomic.Int32
	hayDesde int32 // a partir de qué llamada hay petición (0 = nunca)
	err      error
}

func (p *peticionesFalsas) IngestaSolicitadaDesde(context.Context, time.Time) (bool, error) {
	n := p.llamadas.Add(1)
	if p.err != nil {
		return false, p.err
	}
	return p.hayDesde > 0 && n >= p.hayDesde, nil
}

func TestEsperarSeDespiertaSiHayPeticion(t *testing.T) {
	p := &peticionesFalsas{hayDesde: 1}
	t0 := time.Now()
	if err := esperar(context.Background(), p, t0, time.Hour, slog.New(slog.DiscardHandler)); err != nil {
		t.Fatal(err)
	}
	if time.Since(t0) > 2*time.Second {
		t.Fatal("con una petición pendiente no debe esperar el intervalo")
	}
}

func TestEsperarSinPeticionesDuermeElIntervaloYSeCancela(t *testing.T) {
	t0 := time.Now()
	if err := esperar(context.Background(), nil, t0, 50*time.Millisecond, slog.New(slog.DiscardHandler)); err != nil {
		t.Fatal(err)
	}
	if time.Since(t0) < 45*time.Millisecond {
		t.Fatal("sin fuente de peticiones debe dormir el intervalo")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := esperar(ctx, &peticionesFalsas{}, t0, time.Hour, slog.New(slog.DiscardHandler)); !errors.Is(err, context.Canceled) {
		t.Fatalf("debe devolver la cancelación: %v", err)
	}
}

func TestEsperarSiLaBaseFallaSigueConElIntervalo(t *testing.T) {
	p := &peticionesFalsas{err: errors.New("la base no responde")}
	t0 := time.Now()
	if err := esperar(context.Background(), p, t0, 80*time.Millisecond, slog.New(slog.DiscardHandler)); err != nil {
		t.Fatal(err)
	}
	if p.llamadas.Load() < 1 || time.Since(t0) < 70*time.Millisecond {
		t.Fatal("un fallo al leer las peticiones no debe cortar la espera ni tumbar el ingestor")
	}
}
