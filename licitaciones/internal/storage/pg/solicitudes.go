package pg

import (
	"context"
	"fmt"
	"time"
)

// SolicitarIngesta anota una petición de «actualiza ya». No anota otra si ya hay una de hace menos de minHueco (muchas personas abriendo la aplicación a la vez, o un panel que
// pregunta a menudo, no deben machacar la fuente). Devuelve si ha anotado una nueva. Las peticiones de más de 7 días se borran.
func (s *Store) SolicitarIngesta(ctx context.Context, por string, minHueco time.Duration) (bool, error) {
	if len(por) > 200 {
		por = por[:200]
	}
	tag, err := s.pool.Exec(ctx, `
INSERT INTO ingest_solicitudes (por)
SELECT $1 WHERE NOT EXISTS (SELECT 1 FROM ingest_solicitudes WHERE pedido_en > now() - make_interval(secs => $2))`, por, minHueco.Seconds())
	if err != nil {
		return false, fmt.Errorf("pg: anotar la petición de ingesta: %w", err)
	}
	if _, err := s.pool.Exec(ctx, `DELETE FROM ingest_solicitudes WHERE pedido_en < now() - interval '7 days'`); err != nil {
		return tag.RowsAffected() > 0, nil // la limpieza no es lo importante
	}
	return tag.RowsAffected() > 0, nil
}

// IngestaSolicitadaDesde dice si alguien ha pedido una ingesta después de desde (el comienzo de la vuelta en curso del ingestor).
func (s *Store) IngestaSolicitadaDesde(ctx context.Context, desde time.Time) (bool, error) {
	var hay bool
	if err := s.pool.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM ingest_solicitudes WHERE pedido_en > $1)`, desde).Scan(&hay); err != nil {
		return false, fmt.Errorf("pg: leer las peticiones de ingesta: %w", err)
	}
	return hay, nil
}
