package projector

import (
	"context"
	"log/slog"
	"sync/atomic"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/nats-io/nats.go"

	"github.com/ionindustry/cerebro101/licitaciones/internal/bus"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingestor"
	"github.com/ionindustry/cerebro101/licitaciones/internal/startup"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/s3"
)

// Durable es el nombre del consumidor del proyector de lectura en el flujo en vivo; DurableHistorico, el del flujo de la carga histórica (no lo consume el Cerebro).
const (
	Durable          = "proyector-lectura"
	DurableHistorico = "proyector-lectura-hist"
)

// Run abre las conexiones y proyecta hasta que se cancela ctx. Usa la misma configuración de conexiones que el ingestor (ingestor.FromEnv);
// sus campos de ingesta no se utilizan.
func Run(ctx context.Context, c ingestor.Config, log *slog.Logger) error {
	pool, err := startup.Retry(ctx, log, "postgres", func() (*pgxpool.Pool, error) { return pg.Connect(ctx, c.PG) })
	if err != nil {
		return err
	}
	defer pool.Close()
	if err := pg.Migrate(ctx, pool); err != nil {
		return err
	}
	raw, err := s3.New(s3.Config{Endpoint: c.S3Endpoint, AccessKey: c.S3User, SecretKey: c.S3Pass, Secure: c.S3Secure})
	if err != nil {
		return err
	}
	nc, err := startup.Retry(ctx, log, "bus NATS", func() (*nats.Conn, error) {
		nc, err := bus.Connect(bus.Config{URL: c.NATS, User: c.NATSUser, Password: c.NATSPass})
		if err != nil {
			return nil, err
		}
		p, err := bus.NewPublisher(nc)
		if err == nil {
			err = p.EnsureStream(ctx) // el flujo es de todos: quien llega primero lo crea, igual que el ingestor
		}
		if err != nil {
			nc.Close()
			return nil, err
		}
		return nc, nil
	})
	if err != nil {
		return err
	}
	defer nc.Close()

	st := pg.New(pool)
	var applied, skipped atomic.Int64
	log.Info("proyector listo", "consumidores", []string{Durable, DurableHistorico})
	handler := func(ctx context.Context, ev ingest.Event) error {
		ok, err := Handle(ctx, raw, st, ev)
		if err != nil {
			return err
		}
		if ok {
			if n := applied.Add(1); n%500 == 0 {
				log.Info("expedientes proyectados", "total", n, "omitidos", skipped.Load())
			}
		} else {
			skipped.Add(1)
		}
		return nil
	}
	// Dos flujos, dos consumidores: el de la sindicación en vivo y el de la carga histórica. Si uno cae, el otro sigue y se devuelve el primer error.
	errs := make(chan error, 2)
	ctx2, stop := context.WithCancel(ctx)
	defer stop()
	go func() { errs <- bus.Consume(ctx2, nc, handler, bus.ConsumerOptions{Durable: Durable, Log: log}) }()
	go func() {
		errs <- bus.Consume(ctx2, nc, handler, bus.ConsumerOptions{Durable: DurableHistorico, Stream: bus.StreamHistorico, Log: log})
	}()
	err = <-errs
	stop()
	<-errs
	return err
}

// ReproyectarTodo abre las conexiones (la base y el almacén; no hace falta el bus) y rehace el modelo de lectura de los expedientes ya proyectados releyendo sus originales
// (ver projector.Reproyectar). Es una tarea de una sola vez, no un servicio: `proyector reproyectar`.
func ReproyectarTodo(ctx context.Context, c ingestor.Config, opt OpcionesReproyeccion, log *slog.Logger) (ResumenReproyeccion, error) {
	pool, err := startup.Retry(ctx, log, "postgres", func() (*pgxpool.Pool, error) { return pg.Connect(ctx, c.PG) })
	if err != nil {
		return ResumenReproyeccion{}, err
	}
	defer pool.Close()
	if err := pg.Migrate(ctx, pool); err != nil {
		return ResumenReproyeccion{}, err
	}
	raw, err := s3.New(s3.Config{Endpoint: c.S3Endpoint, AccessKey: c.S3User, SecretKey: c.S3Pass, Secure: c.S3Secure})
	if err != nil {
		return ResumenReproyeccion{}, err
	}
	return Reproyectar(ctx, raw, pg.New(pool), opt, log)
}
