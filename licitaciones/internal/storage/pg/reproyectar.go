package pg

import (
	"context"
	"fmt"

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
)

// FilaReproyeccion identifica un expediente ya proyectado y el original del que salió. Version y SHA256 sirven para no pisar un cambio que llegue mientras
// se reproyecta (ver ReproyectarExpediente).
type FilaReproyeccion struct {
	ID, Fuente, IDOrigen string
	Version              int
	SHA256, ClaveRaw     string
}

// ExpedientesParaReproyectar devuelve hasta limite expedientes con id posterior a `despues` (orden por id: se puede seguir por donde se quedó), de una fuente o de todas.
func (s *Store) ExpedientesParaReproyectar(ctx context.Context, fuente, despues string, limite int) ([]FilaReproyeccion, error) {
	rows, err := s.pool.Query(ctx, `
SELECT id::text, fuente, id_origen, version_entidad, sha256_original, clave_original
FROM expedientes
WHERE ($1 = '' OR fuente = $1) AND ($2 = '' OR id > $2::uuid)
ORDER BY id LIMIT $3`, fuente, despues, limite)
	if err != nil {
		return nil, fmt.Errorf("pg: listar expedientes para reproyectar: %w", err)
	}
	defer rows.Close()
	var out []FilaReproyeccion
	for rows.Next() {
		var f FilaReproyeccion
		if err := rows.Scan(&f.ID, &f.Fuente, &f.IDOrigen, &f.Version, &f.SHA256, &f.ClaveRaw); err != nil {
			return nil, fmt.Errorf("pg: leer un expediente para reproyectar: %w", err)
		}
		out = append(out, f)
	}
	return out, rows.Err()
}

// ResultadoReproyeccion dice qué pasó con un expediente.
type ResultadoReproyeccion int

const (
	ReproyIgual    ResultadoReproyeccion = iota // el original releído da el mismo registro que el guardado
	ReproyCambiado                              // distinto: se ha reescrito (o, en simulación, se reescribiría)
	ReproyMovido                                // ya no está en la versión ni con el original que se leyeron (o está anulado): no se pisa
)

// ReproyectarExpediente vuelve a escribir las columnas derivadas de un expediente con lo que dice su original releído (por ejemplo, tras mejorar el parser). No cambia la
// versión, ni la fecha de actualización, ni el original: es el mismo expediente leído mejor. Solo escribe si el registro normalizado es distinto del guardado (si no, devuelve
// ReproyIgual y no toca nada), y solo si el expediente sigue en la versión y con el original que se leyeron: si mientras tanto llegó una versión nueva o una baja, no se pisa.
// Con simular no escribe, solo dice si cambiaría. Las adjudicaciones se rehacen solas: las recalcula el disparador de la base.
func (s *Store) ReproyectarExpediente(ctx context.Context, f FilaReproyeccion, l *domain.Licitacion, simular bool) (ResultadoReproyeccion, error) {
	v, err := valoresDe(l)
	if err != nil {
		return ReproyIgual, err
	}
	vigente := `SELECT EXISTS (SELECT 1 FROM expedientes WHERE id = $1::uuid AND version_entidad = $2 AND sha256_original = $3 AND estado <> 'anulada')`
	if simular {
		var cambiado bool
		err = s.pool.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM expedientes WHERE id = $1::uuid AND version_entidad = $2 AND sha256_original = $3 AND estado <> 'anulada'
			AND documento IS DISTINCT FROM $4::jsonb)`, f.ID, f.Version, f.SHA256, v.doc).Scan(&cambiado)
		if err != nil {
			return ReproyIgual, fmt.Errorf("pg: comprobar el expediente %s: %w", f.IDOrigen, err)
		}
		if cambiado {
			return ReproyCambiado, nil
		}
		return s.igualOMovido(ctx, vigente, f)
	}
	tag, err := s.pool.Exec(ctx, `
UPDATE expedientes SET
    id_numerico = $5, expediente = $6, estado_origen = $7, estado = $8, titulo = $9,
    comprador_nombre = $10, comprador_nif = $11, comprador_dir3 = $12, procedimiento = $13, procedimiento_origen = $14, tipo_contrato = $15, cpv = $16, nuts = $17,
    valor_estimado = $18::numeric, presupuesto_sin_iva = $19::numeric, presupuesto_con_iva = $20::numeric, moneda = $21, plazo_presentacion = $22, enlace = $23,
    documento = $24::jsonb, proyectada = clock_timestamp()
WHERE id = $1::uuid AND version_entidad = $2 AND sha256_original = $3 AND estado <> 'anulada' AND documento IS DISTINCT FROM $4::jsonb`,
		f.ID, f.Version, f.SHA256, v.doc,
		l.NumericID, l.Expediente, l.Status, l.Estado(), l.Title,
		l.Organism.Name, l.Organism.NIF, l.Organism.DIR3, domain.ProcedimientoNormalizado(l.Procedure), l.Procedure, l.ContractType, v.cpv, v.nuts,
		importe(l.EstimatedValue), importe(l.BaseBudgetExclVAT), importe(l.BaseBudgetInclVAT), v.moneda, v.plazo, l.Link, v.doc)
	if err != nil {
		return ReproyIgual, fmt.Errorf("pg: reproyectar el expediente %s: %w", f.IDOrigen, err)
	}
	if tag.RowsAffected() > 0 {
		return ReproyCambiado, nil
	}
	return s.igualOMovido(ctx, vigente, f)
}

// igualOMovido distingue, cuando no se ha escrito nada, un expediente que sigue igual (versión y original los mismos) de uno que se ha movido.
func (s *Store) igualOMovido(ctx context.Context, consulta string, f FilaReproyeccion) (ResultadoReproyeccion, error) {
	var vigente bool
	if err := s.pool.QueryRow(ctx, consulta, f.ID, f.Version, f.SHA256).Scan(&vigente); err != nil {
		return ReproyIgual, fmt.Errorf("pg: comprobar el expediente %s: %w", f.IDOrigen, err)
	}
	if vigente {
		return ReproyIgual, nil
	}
	return ReproyMovido, nil
}
