// Package pg implementa el estado operativo de la ingesta sobre PostgreSQL (base `licitaciones`): vistas de expedientes, outbox
// transaccional y puntos de control (ADR 0003). La lógica de decisión no está aquí sino en ingest.Decide, compartida con la versión en memoria.
package pg

import (
	"context"
	"embed"
	"fmt"
	"path"
	"sort"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

//go:embed migrations/*.sql
var migrationsFS embed.FS

const lockName = "licitaciones.migraciones"

// Migrate aplica en orden las migraciones que falten. Es idempotente y segura frente a ejecuciones simultáneas (cerrojo de sesión).
func Migrate(ctx context.Context, pool *pgxpool.Pool) error {
	conn, err := pool.Acquire(ctx)
	if err != nil {
		return fmt.Errorf("pg: conexión para migrar: %w", err)
	}
	defer conn.Release()

	if _, err := conn.Exec(ctx, `SELECT pg_advisory_lock(hashtext($1))`, lockName); err != nil {
		return fmt.Errorf("pg: cerrojo de migraciones: %w", err)
	}
	defer func() {
		_, _ = conn.Exec(context.WithoutCancel(ctx), `SELECT pg_advisory_unlock(hashtext($1))`, lockName)
	}()

	if _, err := conn.Exec(ctx, `CREATE TABLE IF NOT EXISTS schema_migraciones (
		version integer PRIMARY KEY, nombre text NOT NULL, aplicada timestamptz NOT NULL DEFAULT clock_timestamp())`); err != nil {
		return fmt.Errorf("pg: tabla de migraciones: %w", err)
	}
	entries, err := migrationsFS.ReadDir("migrations")
	if err != nil {
		return err
	}
	names := make([]string, 0, len(entries))
	for _, e := range entries {
		names = append(names, e.Name())
	}
	sort.Strings(names)
	for _, name := range names {
		version, err := strconv.Atoi(strings.SplitN(name, "_", 2)[0])
		if err != nil {
			return fmt.Errorf("pg: nombre de migración no válido %q: debe empezar por un número", name)
		}
		var done bool
		if err := conn.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM schema_migraciones WHERE version = $1)`, version).Scan(&done); err != nil {
			return fmt.Errorf("pg: consultar migraciones: %w", err)
		}
		if done {
			continue
		}
		sqlText, err := migrationsFS.ReadFile(path.Join("migrations", name))
		if err != nil {
			return err
		}
		if err := applyMigration(ctx, conn, version, name, string(sqlText)); err != nil {
			return err
		}
	}
	return nil
}

func applyMigration(ctx context.Context, conn *pgxpool.Conn, version int, name, sqlText string) error {
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(context.WithoutCancel(ctx)) }()
	if _, err := tx.Exec(ctx, sqlText); err != nil {
		return fmt.Errorf("pg: migración %s: %w", name, err)
	}
	if _, err := tx.Exec(ctx, `INSERT INTO schema_migraciones (version, nombre) VALUES ($1, $2)`, version, name); err != nil {
		return fmt.Errorf("pg: registrar la migración %s: %w", name, err)
	}
	return tx.Commit(ctx)
}
