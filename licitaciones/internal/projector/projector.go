// Package projector construye el modelo de lectura de los expedientes a partir de los eventos del bus: por cada evento lee el original del
// almacén (comprobando su SHA-256), lo normaliza con el parser y lo proyecta en PostgreSQL. Es idempotente y solo avanza de versión, así
// que reentregas y desórdenes no estropean nada, y se puede regenerar todo repitiendo los eventos (ADR 0003).
package projector

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"

	"github.com/ionindustry/cerebro101/licitaciones/internal/bus"
	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/placsp"
	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

// Raw lee originales; lo satisface *s3.Store.
type Raw interface {
	GetRaw(ctx context.Context, key string) ([]byte, error)
}

// Sink es el modelo de lectura; lo satisface *pg.Store.
type Sink interface {
	UpsertExpediente(ctx context.Context, ev ingest.Event, l *domain.Licitacion) (bool, error)
	AnularExpediente(ctx context.Context, ev ingest.Event, b *domain.Baja) (bool, error)
}

// Handle proyecta un evento. Los fallos del original (no coincide el SHA-256, no se lee) son permanentes: reintentar no los arregla. Los del
// almacén o la base son transitorios y se reintentan.
func Handle(ctx context.Context, raw Raw, sink Sink, ev ingest.Event) (applied bool, err error) {
	b, err := raw.GetRaw(ctx, ev.RawKey)
	if err != nil {
		return false, err
	}
	sum := sha256.Sum256(b)
	if got := hex.EncodeToString(sum[:]); got != ev.RawSHA256 {
		return false, fmt.Errorf("%w: el original %s no coincide con su SHA-256 (%s frente a %s)", bus.ErrPermanent, ev.RawKey, got, ev.RawSHA256)
	}
	rec, err := placsp.ParseFragment(b, placsp.Options{Source: ev.Source})
	if err != nil {
		return false, fmt.Errorf("%w: %w", bus.ErrPermanent, err)
	}
	switch {
	case rec.Licitacion != nil:
		return sink.UpsertExpediente(ctx, ev, rec.Licitacion)
	case rec.Baja != nil:
		return sink.AnularExpediente(ctx, ev, rec.Baja)
	}
	return false, fmt.Errorf("%w: el original %s no es una licitación ni una baja", bus.ErrPermanent, ev.RawKey)
}
