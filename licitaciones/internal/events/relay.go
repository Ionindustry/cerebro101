// Package events publica los eventos del outbox en el bus (NATS JetStream) y los borra solo cuando el destino los confirma (ADR 0003).
// El relay es el único que lee el outbox; varios relays a la vez no se pisan porque Drain usa SKIP LOCKED.
package events

import (
	"context"
	"log/slog"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

// Publish publica un evento y vuelve cuando el destino lo ha confirmado.
type Publish = func(ctx context.Context, e ingest.Event) error

// Drainer es el outbox: publica hasta limit eventos con publish y borra los confirmados. Lo satisface *pg.Store.
type Drainer interface {
	Drain(ctx context.Context, limit int, publish func(context.Context, ingest.Event) error) (int, error)
}

// Options configura el relay.
type Options struct {
	Batch      int           // eventos por tanda; 0 = 500
	Interval   time.Duration // espera entre tandas cuando no queda nada; 0 = 1 s
	MaxBackoff time.Duration // espera máxima tras errores seguidos; 0 = 30 s
	Log        *slog.Logger
	Sleep      func(ctx context.Context, d time.Duration) error // solo pruebas
}

// Run publica el outbox hasta que se cancela ctx (devuelve entonces nil). Si el destino no está, reintenta con espera creciente sin perder
// nada: los eventos siguen en el outbox. Si una tanda llena sale otra a continuación, sin esperar.
func Run(ctx context.Context, d Drainer, publish Publish, o Options) error {
	if o.Batch <= 0 {
		o.Batch = 500
	}
	if o.Interval <= 0 {
		o.Interval = time.Second
	}
	if o.MaxBackoff <= 0 {
		o.MaxBackoff = 30 * time.Second
	}
	if o.Log == nil {
		o.Log = slog.New(slog.DiscardHandler)
	}
	sleep := o.Sleep
	if sleep == nil {
		sleep = pause
	}
	var backoff time.Duration
	for ctx.Err() == nil {
		n, err := d.Drain(ctx, o.Batch, publish)
		var wait time.Duration
		switch {
		case err != nil:
			backoff = min(max(backoff*2, o.Interval), o.MaxBackoff)
			wait = backoff
			o.Log.Warn("no se pudo publicar el outbox", "error", err, "publicados", n, "reintento_en", wait)
		case n >= o.Batch:
			continue // puede quedar más: otra tanda ya
		default:
			backoff, wait = 0, o.Interval
		}
		if err := sleep(ctx, wait); err != nil {
			return nil // cancelado
		}
	}
	return nil
}

func pause(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-t.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}
