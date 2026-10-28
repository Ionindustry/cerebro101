package pg

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

var decimal = regexp.MustCompile(`^-?[0-9]{1,14}(\.[0-9]{1,4})?$`)

// importe devuelve el valor decimal de un importe para la columna numeric, o nil si no hay o no es un decimal válido.
func importe(m *domain.Money) *string {
	if m == nil || !decimal.MatchString(m.Value) {
		return nil
	}
	return &m.Value
}

// valoresExpediente son las columnas derivadas de una licitación normalizada. Las usan la proyección normal (UpsertExpediente) y la reproyección de los
// expedientes ya guardados (ReproyectarExpediente), para que las dos escriban exactamente lo mismo.
type valoresExpediente struct {
	doc       []byte
	moneda    string
	plazo     *time.Time
	cpv, nuts []string
}

func valoresDe(l *domain.Licitacion) (valoresExpediente, error) {
	doc, err := json.Marshal(l)
	if err != nil {
		return valoresExpediente{}, fmt.Errorf("pg: serializar el expediente: %w", err)
	}
	v := valoresExpediente{doc: doc, moneda: "EUR", cpv: nonNil(l.CPV), nuts: nonNil(l.NUTS)}
	for _, m := range []*domain.Money{l.EstimatedValue, l.BaseBudgetExclVAT, l.BaseBudgetInclVAT} {
		if m != nil && len(m.Currency) == 3 {
			v.moneda = m.Currency
			break
		}
	}
	if l.TenderDeadline != nil && !l.TenderDeadline.IsZero() {
		v.plazo = l.TenderDeadline
	}
	return v, nil
}

// UpsertExpediente proyecta una licitación en el modelo de lectura. Solo avanza: si ya hay una versión igual o posterior (reentrega, orden
// distinto) no toca nada y devuelve applied=false.
func (s *Store) UpsertExpediente(ctx context.Context, ev ingest.Event, l *domain.Licitacion) (applied bool, err error) {
	v, err := valoresDe(l)
	if err != nil {
		return false, err
	}
	tag, err := s.pool.Exec(ctx, `
INSERT INTO expedientes (fuente, id_origen, id_numerico, version_entidad, actualizada, expediente, estado_origen, estado, titulo,
    comprador_nombre, comprador_nif, comprador_dir3, procedimiento, procedimiento_origen, tipo_contrato, cpv, nuts,
    valor_estimado, presupuesto_sin_iva, presupuesto_con_iva, moneda, plazo_presentacion, enlace, sha256_original, clave_original, documento)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::numeric,$19::numeric,$20::numeric,$21,$22,$23,$24,$25,$26)
ON CONFLICT (fuente, id_origen) DO UPDATE SET
    id_numerico = EXCLUDED.id_numerico, version_entidad = EXCLUDED.version_entidad, actualizada = EXCLUDED.actualizada,
    expediente = EXCLUDED.expediente, estado_origen = EXCLUDED.estado_origen, estado = EXCLUDED.estado, titulo = EXCLUDED.titulo,
    comprador_nombre = EXCLUDED.comprador_nombre, comprador_nif = EXCLUDED.comprador_nif, comprador_dir3 = EXCLUDED.comprador_dir3,
    procedimiento = EXCLUDED.procedimiento, procedimiento_origen = EXCLUDED.procedimiento_origen, tipo_contrato = EXCLUDED.tipo_contrato,
    cpv = EXCLUDED.cpv, nuts = EXCLUDED.nuts, valor_estimado = EXCLUDED.valor_estimado, presupuesto_sin_iva = EXCLUDED.presupuesto_sin_iva,
    presupuesto_con_iva = EXCLUDED.presupuesto_con_iva, moneda = EXCLUDED.moneda, plazo_presentacion = EXCLUDED.plazo_presentacion,
    enlace = EXCLUDED.enlace, sha256_original = EXCLUDED.sha256_original, clave_original = EXCLUDED.clave_original,
    documento = EXCLUDED.documento, proyectada = clock_timestamp()
WHERE expedientes.version_entidad < EXCLUDED.version_entidad`,
		l.Source, l.SourceID, l.NumericID, ev.Version, l.Updated, l.Expediente, l.Status, l.Estado(), l.Title,
		l.Organism.Name, l.Organism.NIF, l.Organism.DIR3, domain.ProcedimientoNormalizado(l.Procedure), l.Procedure, l.ContractType, v.cpv, v.nuts,
		importe(l.EstimatedValue), importe(l.BaseBudgetExclVAT), importe(l.BaseBudgetInclVAT), v.moneda, v.plazo, l.Link,
		ev.RawSHA256, ev.RawKey, v.doc)
	if err != nil {
		return false, fmt.Errorf("pg: proyectar el expediente %s: %w", l.SourceID, err)
	}
	return tag.RowsAffected() > 0, nil
}

// AnularExpediente marca como anulado un expediente que ya estaba proyectado (una baja de la sindicación). Si todavía no está, no hace
// nada: la baja de algo que nunca se vio no tiene qué anular. Solo avanza de versión, como UpsertExpediente.
func (s *Store) AnularExpediente(ctx context.Context, ev ingest.Event, b *domain.Baja) (applied bool, err error) {
	tag, err := s.pool.Exec(ctx, `
UPDATE expedientes SET estado = 'anulada', version_entidad = $3, actualizada = $4, sha256_original = $5, clave_original = $6,
    documento = jsonb_set(documento, '{status}', '"ANUL"'), proyectada = clock_timestamp()
WHERE fuente = $1 AND id_origen = $2 AND version_entidad < $3`, ev.Source, b.Ref, ev.Version, b.When, ev.RawSHA256, ev.RawKey)
	if err != nil {
		return false, fmt.Errorf("pg: anular el expediente %s: %w", b.Ref, err)
	}
	return tag.RowsAffected() > 0, nil
}

// ContarExpedientes devuelve cuántos expedientes hay proyectados.
func (s *Store) ContarExpedientes(ctx context.Context) (int, error) {
	var n int
	if err := s.pool.QueryRow(ctx, `SELECT count(*) FROM expedientes`).Scan(&n); err != nil {
		return 0, fmt.Errorf("pg: contar expedientes: %w", err)
	}
	return n, nil
}

func nonNil(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}
