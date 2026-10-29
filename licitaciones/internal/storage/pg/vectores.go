package pg

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// Búsqueda por significado y por cercanía. Los vectores viven en una tabla aparte (expedientes_vectores) que NO crea una migración: la crea el
// vectorizador al arrancar (PrepararVectores), porque necesita la extensión pgvector. Así, si la base no la tiene, el motor sigue funcionando entero y
// solo la búsqueda por significado queda desactivada (VectoresDisponibles = false).

// DimensionesVector es el tamaño de los vectores (bge-m3). Si el modelo cambia, hay que cambiarlo aquí y revectorizar.
const DimensionesVector = 1024

// VersionTextoVector sube cuando cambia el texto que se vectoriza: los expedientes con una versión anterior se vuelven a vectorizar.
const VersionTextoVector = 1

// ErrSinVector se devuelve cuando un expediente todavía no tiene vector (el vectorizador no ha llegado a él).
var ErrSinVector = errors.New("pg: el expediente todavía no está vectorizado")

// ErrSinVectores se devuelve cuando la base no tiene la extensión o la tabla de vectores.
var ErrSinVectores = errors.New("pg: la búsqueda por significado no está disponible (falta pgvector o aún no se ha preparado)")

// PrepararVectores crea la extensión, la tabla y el índice si faltan. Devuelve false (sin error) si la base no trae pgvector.
func (s *Store) PrepararVectores(ctx context.Context) (bool, error) {
	if _, err := s.pool.Exec(ctx, `CREATE EXTENSION IF NOT EXISTS vector`); err != nil {
		var pe *pgconn.PgError
		// 0A000 = «no se puede abrir el fichero de control de la extensión»: la imagen de Postgres no trae pgvector.
		if errors.As(err, &pe) && (pe.Code == "0A000" || pe.Code == "58P01" || pe.Code == "42501") {
			return false, nil
		}
		return false, fmt.Errorf("pg: crear la extensión vector: %w", err)
	}
	ddl := fmt.Sprintf(`
CREATE TABLE IF NOT EXISTS expedientes_vectores (
    expediente_id uuid PRIMARY KEY REFERENCES expedientes(id) ON DELETE CASCADE,
    version_texto integer     NOT NULL,
    modelo        text        NOT NULL,
    embedding     vector(%d)  NOT NULL,
    creado        timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS expedientes_vectores_hnsw ON expedientes_vectores USING hnsw (embedding vector_cosine_ops)`, DimensionesVector)
	if _, err := s.pool.Exec(ctx, ddl); err != nil {
		return false, fmt.Errorf("pg: crear la tabla de vectores: %w", err)
	}
	return true, nil
}

// VectoresDisponibles dice si la tabla de vectores existe (y por tanto se puede buscar por significado).
func (s *Store) VectoresDisponibles(ctx context.Context) bool {
	var ok bool
	err := s.pool.QueryRow(ctx, `SELECT to_regclass('expedientes_vectores') IS NOT NULL AND EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')`).Scan(&ok)
	return err == nil && ok
}

// PorVectorizar es un expediente al que le falta el vector (o lo tiene de un texto antiguo).
type PorVectorizar struct {
	ID    string
	Texto string
}

// textoVectorSQL es el texto de un expediente que se convierte en vector: lo que describe de qué va (título, quién compra, tipo y códigos CPV).
const textoVectorSQL = `concat_ws('. ', nullif(e.titulo, ''), nullif(e.comprador_nombre, ''), nullif(e.tipo_contrato, ''), nullif(array_to_string(e.cpv, ' '), ''))`

// PorVectorizar devuelve hasta limite expedientes sin vector actual, los más recientes primero (lo que más se consulta queda listo antes).
func (s *Store) PorVectorizar(ctx context.Context, limite int) ([]PorVectorizar, error) {
	rows, err := s.pool.Query(ctx, `SELECT e.id::text, `+textoVectorSQL+`
FROM expedientes e LEFT JOIN expedientes_vectores x ON x.expediente_id = e.id
WHERE (x.expediente_id IS NULL OR x.version_texto < $1 OR x.creado < e.proyectada) AND e.titulo <> ''
ORDER BY e.actualizada DESC, e.id LIMIT $2`, VersionTextoVector, limite)
	if err != nil {
		return nil, fmt.Errorf("pg: expedientes por vectorizar: %w", err)
	}
	defer rows.Close()
	var out []PorVectorizar
	for rows.Next() {
		var p PorVectorizar
		if err := rows.Scan(&p.ID, &p.Texto); err != nil {
			return nil, fmt.Errorf("pg: leer un expediente por vectorizar: %w", err)
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

// ContarPorVectorizar devuelve cuántos expedientes faltan y cuántos hay ya con vector (para el estado del motor).
func (s *Store) ContarPorVectorizar(ctx context.Context) (faltan, hechos int, err error) {
	err = s.pool.QueryRow(ctx, `SELECT
    (SELECT count(*) FROM expedientes e LEFT JOIN expedientes_vectores x ON x.expediente_id = e.id
       WHERE (x.expediente_id IS NULL OR x.version_texto < $1 OR x.creado < e.proyectada) AND e.titulo <> ''),
    (SELECT count(*) FROM expedientes_vectores)`, VersionTextoVector).Scan(&faltan, &hechos)
	if err != nil {
		return 0, 0, fmt.Errorf("pg: contar los vectores: %w", err)
	}
	return faltan, hechos, nil
}

// literalVector escribe un vector como literal de pgvector («[0.1,0.2,…]»), que se pasa como parámetro de texto y se convierte con ::vector.
func literalVector(v []float32) string {
	var b strings.Builder
	b.Grow(len(v) * 10)
	b.WriteByte('[')
	for i, x := range v {
		if i > 0 {
			b.WriteByte(',')
		}
		b.WriteString(strconv.FormatFloat(float64(x), 'g', 7, 32))
	}
	b.WriteByte(']')
	return b.String()
}

// GuardarVectores escribe (o sustituye) los vectores de los expedientes dados. ids y vectores van en el mismo orden.
func (s *Store) GuardarVectores(ctx context.Context, modelo string, ids []string, vectores [][]float32) error {
	if len(ids) != len(vectores) {
		return errors.New("pg: ids y vectores no coinciden")
	}
	batch := &pgx.Batch{}
	for i, id := range ids {
		if len(vectores[i]) != DimensionesVector {
			return fmt.Errorf("pg: el vector de %s tiene %d dimensiones", id, len(vectores[i]))
		}
		batch.Queue(`INSERT INTO expedientes_vectores (expediente_id, version_texto, modelo, embedding)
SELECT $1::uuid, $2, $3, $4::vector WHERE EXISTS (SELECT 1 FROM expedientes WHERE id = $1::uuid)
ON CONFLICT (expediente_id) DO UPDATE SET version_texto = EXCLUDED.version_texto, modelo = EXCLUDED.modelo, embedding = EXCLUDED.embedding, creado = clock_timestamp()`,
			id, VersionTextoVector, modelo, literalVector(vectores[i]))
	}
	res := s.pool.SendBatch(ctx, batch)
	defer res.Close()
	for range ids {
		if _, err := res.Exec(); err != nil {
			return fmt.Errorf("pg: guardar un vector: %w", err)
		}
	}
	return nil
}

// efSearch es cuántos candidatos explora el índice HNSW; más = más exacto con los filtros puestos, y algo más lento.
const efSearch = 400

// BuscarPorSignificado devuelve los limite expedientes más cercanos al vector que cumplen el filtro (el texto q del filtro se ignora: de eso se ocupa
// la búsqueda de texto). Cada fila trae en ClaveOrden la distancia coseno (0 = igual; 1 = nada que ver).
func (s *Store) BuscarPorSignificado(ctx context.Context, f Filtro, vector []float32, limite int) ([]Fila, error) {
	if len(vector) != DimensionesVector {
		return nil, fmt.Errorf("pg: el vector tiene %d dimensiones", len(vector))
	}
	if limite < 1 || limite > 200 {
		return nil, fmt.Errorf("pg: limite fuera de rango: %d", limite)
	}
	f.Q = ""
	var c consulta
	vec := c.arg(literalVector(vector))
	f.aplicar(&c)
	where := "true"
	if len(c.where) > 0 {
		where = strings.Join(c.where, " AND ")
	}
	sql := fmt.Sprintf(`SELECT %s, (x.embedding <=> %s::vector)::text
FROM expedientes_vectores x JOIN expedientes e ON e.id = x.expediente_id LEFT JOIN vistas v ON v.fuente = e.fuente AND v.id_origen = e.id_origen
WHERE %s ORDER BY x.embedding <=> %s::vector, e.id LIMIT %d`, columnas, vec, where, vec, limite)
	return s.consultarFilas(ctx, sql, c.args)
}

// Parecida es un expediente cercano a otro, con el porqué de la cercanía.
type Parecida struct {
	Fila
	Distancia      float64
	MismoComprador bool // mismo NIF de comprador
	CPVEnComun     bool // comparten algún código CPV exacto
}

// Parecidas devuelve los limite expedientes más cercanos (por significado) al dado, sin incluirlo. Además de la distancia, dice si comparten comprador o CPV:
// es la parte «grafo» de la cercanía, resuelta con las relaciones que ya hay en la base.
func (s *Store) Parecidas(ctx context.Context, id string, limite int) ([]Parecida, error) {
	if limite < 1 || limite > 50 {
		return nil, fmt.Errorf("pg: limite fuera de rango: %d", limite)
	}
	id = strings.ToLower(id)
	var hay bool
	if err := s.pool.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM expedientes WHERE id::text = $1)`, id).Scan(&hay); err != nil {
		return nil, fmt.Errorf("pg: comprobar el expediente: %w", err)
	}
	if !hay {
		return nil, ErrNoEncontrado
	}
	var tiene bool
	if err := s.pool.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM expedientes_vectores WHERE expediente_id::text = $1)`, id).Scan(&tiene); err != nil {
		return nil, fmt.Errorf("pg: comprobar el vector: %w", err)
	}
	if !tiene {
		return nil, ErrSinVector
	}
	// El vector de partida va como subconsulta escalar (no como JOIN) para que el planificador pueda usar el índice HNSW.
	const origen = `(SELECT embedding FROM expedientes_vectores WHERE expediente_id = $1::uuid)`
	sql := fmt.Sprintf(`SELECT %s, (x.embedding <=> %[2]s)::float8,
    (e.comprador_nif <> '' AND e.comprador_nif = (SELECT comprador_nif FROM expedientes WHERE id = $1::uuid)),
    (e.cpv && (SELECT cpv FROM expedientes WHERE id = $1::uuid))
FROM expedientes_vectores x JOIN expedientes e ON e.id = x.expediente_id LEFT JOIN vistas v ON v.fuente = e.fuente AND v.id_origen = e.id_origen
WHERE x.expediente_id <> $1::uuid ORDER BY x.embedding <=> %[2]s, e.id LIMIT %[3]d`, columnas, origen, limite)
	rows, err := s.pool.Query(ctx, sql, id)
	if err != nil {
		return nil, fmt.Errorf("pg: buscar parecidas: %w", err)
	}
	defer rows.Close()
	var out []Parecida
	for rows.Next() {
		var p Parecida
		fila, err := escanear(rows, &p.Distancia, &p.MismoComprador, &p.CPVEnComun)
		if err != nil {
			return nil, fmt.Errorf("pg: leer una parecida: %w", err)
		}
		p.Fila = fila
		out = append(out, p)
	}
	return out, rows.Err()
}

func (s *Store) consultarFilas(ctx context.Context, sql string, args []any) ([]Fila, error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return nil, fmt.Errorf("pg: abrir la transacción: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, fmt.Sprintf("SET LOCAL hnsw.ef_search = %d", efSearch)); err != nil {
		return nil, ErrSinVectores
	}
	rows, err := tx.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("pg: buscar por significado: %w", err)
	}
	defer rows.Close()
	var out []Fila
	for rows.Next() {
		var clave string
		fila, err := escanear(rows, &clave)
		if err != nil {
			return nil, fmt.Errorf("pg: leer un expediente: %w", err)
		}
		fila.ClaveOrden = clave
		out = append(out, fila)
	}
	return out, rows.Err()
}
