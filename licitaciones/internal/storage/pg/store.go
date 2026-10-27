package pg

import (
	"context"
	"errors"
	"fmt"
	"math"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

const uniqueViolation = "23505"

// Store es el estado de la ingesta en PostgreSQL. Cumple ingest.State.
type Store struct {
	pool *pgxpool.Pool
}

var _ ingest.State = (*Store)(nil)

// Connect abre un pool de conexiones. El nombre de aplicación ayuda a reconocer las conexiones del motor en pg_stat_activity.
func Connect(ctx context.Context, url string) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, fmt.Errorf("pg: dirección de la base no válida: %w", err)
	}
	if cfg.ConnConfig.RuntimeParams["application_name"] == "" {
		cfg.ConnConfig.RuntimeParams["application_name"] = "licitaciones"
	}
	if cfg.MaxConns > 8 {
		cfg.MaxConns = 8
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("pg: abrir el pool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("pg: la base no responde: %w", err)
	}
	return pool, nil
}

// New crea el almacén sobre un pool ya abierto (y con las migraciones aplicadas: ver Migrate).
func New(pool *pgxpool.Pool) *Store { return &Store{pool: pool} }

// Observe aplica ingest.Decide en una sola transacción: la vista del expediente y el evento del outbox se escriben juntos o no se escribe nada.
// Dos escritores simultáneos sobre el mismo expediente nuevo se serializan: el que pierde la carrera repite y lo ve ya existente.
func (s *Store) Observe(ctx context.Context, o ingest.Observation) (ingest.Outcome, error) {
	for attempt := 0; attempt < 3; attempt++ {
		out, err := s.observeOnce(ctx, o)
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == uniqueViolation {
			continue
		}
		return out, err
	}
	return ingest.Outcome{}, errors.New("pg: no se pudo registrar la observación tras varios intentos por conflicto")
}

func (s *Store) observeOnce(ctx context.Context, o ingest.Observation) (ingest.Outcome, error) {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return ingest.Outcome{}, err
	}
	defer func() { _ = tx.Rollback(context.WithoutCancel(ctx)) }()

	var prev *ingest.View
	var v ingest.View
	var flags int16
	err = tx.QueryRow(ctx, `SELECT version_entidad, hash_normalizado, actualizado_origen, banderas
		FROM vistas WHERE fuente = $1 AND id_origen = $2 FOR UPDATE`, o.Source, o.SourceID).Scan(&v.Version, &v.Hash, &v.Updated, &flags)
	switch {
	case err == nil:
		if flags < 0 || flags > math.MaxUint8 {
			return ingest.Outcome{}, fmt.Errorf("pg: banderas fuera de rango (%d) en la vista de %s", flags, o.SourceID)
		}
		v.Flags = ingest.Flags(flags)
		prev = &v
	case !errors.Is(err, pgx.ErrNoRows):
		return ingest.Outcome{}, fmt.Errorf("pg: leer la vista: %w", err)
	}

	d := ingest.Decide(prev, o)
	if d.Write {
		if prev == nil {
			_, err = tx.Exec(ctx, `INSERT INTO vistas (fuente, id_origen, version_entidad, hash_normalizado, actualizado_origen, banderas, sha256_original, clave_original)
				VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
				o.Source, o.SourceID, d.View.Version, d.View.Hash, d.View.Updated, int16(d.View.Flags), o.RawSHA256, o.RawKey)
		} else if d.Kind == ingest.KindUnchanged {
			_, err = tx.Exec(ctx, `UPDATE vistas SET actualizado_origen = $3, visto_ultima = clock_timestamp() WHERE fuente = $1 AND id_origen = $2`,
				o.Source, o.SourceID, d.View.Updated)
		} else {
			_, err = tx.Exec(ctx, `UPDATE vistas SET version_entidad = $3, hash_normalizado = $4, actualizado_origen = $5, banderas = $6,
				sha256_original = $7, clave_original = $8, visto_ultima = clock_timestamp() WHERE fuente = $1 AND id_origen = $2`,
				o.Source, o.SourceID, d.View.Version, d.View.Hash, d.View.Updated, int16(d.View.Flags), o.RawSHA256, o.RawKey)
		}
		if err != nil {
			return ingest.Outcome{}, fmt.Errorf("pg: escribir la vista: %w", err)
		}
	}
	out := d.Outcome(o)
	if d.Kind == ingest.KindStale && prev != nil {
		out.Version = prev.Version
	}
	if e := out.Event; e != nil {
		if _, err := tx.Exec(ctx, `INSERT INTO outbox (id, tipo, fuente, id_origen, version_entidad, sha256_original, clave_original)
			VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (id) DO NOTHING`,
			e.ID, e.Type, e.Source, e.SourceID, e.Version, e.RawSHA256, e.RawKey); err != nil {
			return ingest.Outcome{}, fmt.Errorf("pg: escribir el evento: %w", err)
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return ingest.Outcome{}, fmt.Errorf("pg: confirmar la observación: %w", err)
	}
	return out, nil
}

// Checkpoint devuelve el punto de control de una fuente (vacío si no hay).
func (s *Store) Checkpoint(ctx context.Context, source string) (ingest.Checkpoint, error) {
	var c ingest.Checkpoint
	err := s.pool.QueryRow(ctx, `SELECT ultima_ejecucion, etag, last_modified FROM puntos_control WHERE fuente = $1`, source).
		Scan(&c.LastRun, &c.Validators.ETag, &c.Validators.LastModified)
	if errors.Is(err, pgx.ErrNoRows) {
		return ingest.Checkpoint{}, nil
	}
	if err != nil {
		return ingest.Checkpoint{}, fmt.Errorf("pg: leer el punto de control: %w", err)
	}
	return c, nil
}

// SaveCheckpoint guarda (o sustituye) el punto de control de una fuente.
func (s *Store) SaveCheckpoint(ctx context.Context, source string, c ingest.Checkpoint) error {
	_, err := s.pool.Exec(ctx, `INSERT INTO puntos_control (fuente, ultima_ejecucion, etag, last_modified) VALUES ($1, $2, $3, $4)
		ON CONFLICT (fuente) DO UPDATE SET ultima_ejecucion = EXCLUDED.ultima_ejecucion, etag = EXCLUDED.etag,
			last_modified = EXCLUDED.last_modified, actualizado = clock_timestamp()`, source, c.LastRun, c.Validators.ETag, c.Validators.LastModified)
	if err != nil {
		return fmt.Errorf("pg: guardar el punto de control: %w", err)
	}
	return nil
}

// Drain publica hasta limit eventos pendientes (publish vuelve cuando el destino lo ha confirmado, p. ej. con el PubAck de NATS), en orden, y borra del outbox los confirmados (ADR 0003, paso 5). Varios Drain a la vez no se
// pisan (SKIP LOCKED). Si la publicación de un evento falla, se conservan él y los siguientes, se anota el intento y se devuelve el error junto
// con el número de eventos publicados antes del fallo.
func (s *Store) Drain(ctx context.Context, limit int, publish func(context.Context, ingest.Event) error) (int, error) {
	if limit <= 0 {
		limit = 500
	}
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback(context.WithoutCancel(ctx)) }()

	rows, err := tx.Query(ctx, `SELECT id, tipo, fuente, id_origen, version_entidad, sha256_original, clave_original
		FROM outbox ORDER BY seq LIMIT $1 FOR UPDATE SKIP LOCKED`, limit)
	if err != nil {
		return 0, fmt.Errorf("pg: leer el outbox: %w", err)
	}
	var pend []ingest.Event
	for rows.Next() {
		var e ingest.Event
		if err := rows.Scan(&e.ID, &e.Type, &e.Source, &e.SourceID, &e.Version, &e.RawSHA256, &e.RawKey); err != nil {
			rows.Close()
			return 0, err
		}
		pend = append(pend, e)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}

	var done []string
	var failed error
	var failedID string
	for _, e := range pend {
		if err := publish(ctx, e); err != nil {
			failed, failedID = err, e.ID
			break
		}
		done = append(done, e.ID)
	}
	if len(done) > 0 {
		if _, err := tx.Exec(ctx, `DELETE FROM outbox WHERE id = ANY($1)`, done); err != nil {
			return 0, fmt.Errorf("pg: borrar los eventos publicados: %w", err)
		}
	}
	if failed != nil {
		if _, err := tx.Exec(ctx, `UPDATE outbox SET intentos = intentos + 1 WHERE id = $1`, failedID); err != nil {
			return len(done), fmt.Errorf("pg: anotar el intento fallido: %w", err)
		}
	}
	// Se confirma también tras un fallo de publicación: lo ya publicado no debe volver a salir.
	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("pg: confirmar la publicación: %w", err)
	}
	if failed != nil {
		return len(done), fmt.Errorf("pg: publicar %s: %w", failedID, failed)
	}
	return len(done), nil
}

// Pending informa del estado del outbox para vigilarlo (alerta si > 10 000 filas o la más antigua > 15 min).
func (s *Store) Pending(ctx context.Context) (count int, oldest time.Duration, err error) {
	var secs float64
	err = s.pool.QueryRow(ctx, `SELECT count(*), COALESCE(EXTRACT(EPOCH FROM clock_timestamp() - min(creado)), 0) FROM outbox`).Scan(&count, &secs)
	return count, time.Duration(secs * float64(time.Second)), err
}
