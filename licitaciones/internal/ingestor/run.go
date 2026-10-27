package ingestor

import (
	"context"
	"errors"
	"fmt"
	"hash/fnv"
	"log/slog"
	"sync"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ionindustry/cerebro101/licitaciones/internal/bus"
	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
	"github.com/ionindustry/cerebro101/licitaciones/internal/events"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/s3"
)

// Run abre las conexiones, espera el cerrojo de líder y trabaja hasta que se cancela ctx (devuelve entonces nil). Un fallo de arranque (base,
// almacén o bus que no responden tras los reintentos) se devuelve como error: el orquestador reinicia el contenedor.
func Run(ctx context.Context, c Config, log *slog.Logger) error {
	pool, err := retry(ctx, log, "postgres", func() (*pgxpool.Pool, error) { return pg.Connect(ctx, c.PG) })
	if err != nil {
		return err
	}
	defer pool.Close()
	if err := pg.Migrate(ctx, pool); err != nil {
		return err
	}

	raw, err := retry(ctx, log, "almacén S3", func() (*s3.Store, error) {
		s, err := s3.New(s3.Config{Endpoint: c.S3Endpoint, AccessKey: c.S3User, SecretKey: c.S3Pass, Secure: c.S3Secure})
		if err != nil {
			return nil, err
		}
		return s, s.EnsureBuckets(ctx)
	})
	if err != nil {
		return err
	}

	pub, closeBus, err := openBus(ctx, log, c)
	if err != nil {
		return err
	}
	defer closeBus()

	fc, err := fetch.New(fetch.Options{AllowedHosts: []string{sourceHost}, UserAgent: userAgent(c.Contact)})
	if err != nil {
		return err
	}

	release, err := acquireLeader(ctx, pool, log)
	if err != nil {
		return err
	}
	if release == nil { // cancelado mientras se esperaba
		return nil
	}
	defer release()

	st := pg.New(pool)
	deps := ingest.Deps{Fetcher: fc, Raw: raw, State: st, Log: log}
	return Work(ctx, deps, st, pub.Publish, c, log)
}

// Work es el trabajo en régimen: el relay publica el outbox en segundo plano y cada fuente se ingiere de inmediato y luego cada Interval.
// Un error de una ingesta se registra y se reintenta en la siguiente vuelta: no tumba el servicio.
func Work(ctx context.Context, deps ingest.Deps, d events.Drainer, publish events.Publish, c Config, log *slog.Logger) error {
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		_ = events.Run(ctx, d, publish, events.Options{Log: log})
	}()
	defer wg.Wait()

	for ctx.Err() == nil {
		for _, source := range c.Sources {
			if ctx.Err() != nil {
				break
			}
			start := time.Now()
			stats, err := ingest.Run(ctx, deps, source, Catalog[source], ingest.RunOptions{MaxPages: c.MaxPages})
			if err != nil {
				log.Error("ingesta fallida", "fuente", source, "error", err, "paginas", stats.Pages)
				continue
			}
			log.Info("ingesta completada", "fuente", source, "duracion", time.Since(start).Round(time.Millisecond).String(),
				"nuevas", stats.New, "modificadas", stats.Modified, "sin_cambios", stats.Unchanged, "bajas", stats.Removed,
				"originales_nuevos", stats.RawCreated, "sin_cambios_en_origen", stats.NotModified)
		}
		if err := sleep(ctx, c.Interval); err != nil {
			break
		}
	}
	return nil
}

func openBus(ctx context.Context, log *slog.Logger, c Config) (*bus.Publisher, func(), error) {
	type opened struct {
		p     *bus.Publisher
		close func()
	}
	o, err := retry(ctx, log, "bus NATS", func() (opened, error) {
		nc, err := bus.Connect(bus.Config{URL: c.NATS, User: c.NATSUser, Password: c.NATSPass})
		if err != nil {
			return opened{}, err
		}
		p, err := bus.NewPublisher(nc)
		if err == nil {
			err = p.EnsureStream(ctx)
		}
		if err != nil {
			nc.Close()
			return opened{}, err
		}
		return opened{p, nc.Close}, nil
	})
	return o.p, o.close, err
}

func userAgent(contact string) string {
	ua := "cerebro101-licitaciones/0.1 (+https://101.cat"
	if contact != "" {
		ua += "; " + contact
	}
	return ua + ")"
}

// retry repite op con espera creciente (hasta 6 intentos, ~1 min) para tolerar el arranque simultáneo de los servicios del compose.
func retry[T any](ctx context.Context, log *slog.Logger, what string, op func() (T, error)) (T, error) {
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
		if err := sleep(ctx, wait); err != nil {
			return zero, err
		}
		wait = min(wait*2, 20*time.Second)
	}
	return zero, fmt.Errorf("%s no responde: %w", what, last)
}

// acquireLeader toma el cerrojo de sesión de Postgres que garantiza un único escritor (ADR 0003). Espera si otro ingestor lo tiene.
// Devuelve la función que lo libera, o nil si se cancela ctx mientras espera.
func acquireLeader(ctx context.Context, pool *pgxpool.Pool, log *slog.Logger) (func(), error) {
	h := fnv.New64a()
	_, _ = h.Write([]byte("licitaciones.lider.ingestor"))
	key := int64(h.Sum64() >> 1)
	conn, err := pool.Acquire(ctx)
	if err != nil {
		return nil, fmt.Errorf("cerrojo de líder: %w", err)
	}
	for {
		var ok bool
		if err := conn.QueryRow(ctx, `SELECT pg_try_advisory_lock($1)`, key).Scan(&ok); err != nil {
			conn.Release()
			if errors.Is(err, context.Canceled) || ctx.Err() != nil {
				return nil, nil
			}
			return nil, fmt.Errorf("cerrojo de líder: %w", err)
		}
		if ok {
			log.Info("cerrojo de líder tomado")
			return func() {
				_, _ = conn.Exec(context.WithoutCancel(ctx), `SELECT pg_advisory_unlock($1)`, key)
				conn.Release()
			}, nil
		}
		log.Info("otro ingestor es el líder: se espera")
		if err := sleep(ctx, 15*time.Second); err != nil {
			conn.Release()
			return nil, nil
		}
	}
}

func sleep(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-t.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}
