// Package startup reúne lo que comparten los servicios del motor al arrancar: esperar a las dependencias (base, almacén, bus) con reintentos.
package startup

import (
	"context"
	"fmt"
	"log/slog"
	"time"
)

// Sleep espera d o hasta que se cancela ctx (en cuyo caso devuelve su error).
func Sleep(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-t.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// Retry repite op con espera creciente (hasta 6 intentos, ~1 min) para tolerar el arranque simultáneo de los servicios del compose.
func Retry[T any](ctx context.Context, log *slog.Logger, what string, op func() (T, error)) (T, error) {
	var zero T
	wait := time.Second
	var last error
	for attempt := 1; attempt <= 6; attempt++ {
		v, err := op()
		if err == nil {
			return v, nil
		}
		last = err
		log.Warn("servicio no disponible, se reintenta", "servicio", what, "intento", attempt, "error", err, "espera", wait.String())
		if err := Sleep(ctx, wait); err != nil {
			return zero, err
		}
		wait = min(wait*2, 20*time.Second)
	}
	return zero, fmt.Errorf("%s no responde: %w", what, last)
}
