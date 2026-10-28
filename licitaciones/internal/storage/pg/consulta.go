package pg

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Órdenes admitidos en la búsqueda. Cada uno es una clave de ordenación más el identificador, para que la paginación por cursor sea estable.
const (
	OrdenActualizacion = "actualizacion" // más recientes primero
	OrdenRelevancia    = "relevancia"    // solo con texto de búsqueda
	OrdenPlazo         = "plazo"         // el plazo de presentación más próximo primero; sin plazo, al final
	OrdenImporte       = "importe"       // mayor valor estimado primero; sin importe, al final
)

// MaxTotal es hasta dónde se cuenta el total de resultados: por encima, la API informa «al menos MaxTotal».
const MaxTotal = 10000

// Filtro describe una búsqueda ya validada. Los valores van siempre como parámetros de la consulta, nunca dentro del SQL.
type Filtro struct {
	Q                string   // texto libre (castellano o catalán)
	CPV, NUTS        []string // prefijos de 2 a 8 cifras / códigos NUTS; varios = O
	Estados          []string
	Procedimientos   []string
	Fuentes          []string // identificadores internos (placsp-643…)
	IDOrigen         string   // identificador del expediente en la fuente; solo con una fuente (es único dentro de ella)
	CompradorNIF     []string
	CompradorDIR3    []string
	ImporteMin       string // decimal; vacío = sin límite
	ImporteMax       string
	ActualizadaDesde *time.Time
	PlazoDesde       *time.Time
	PlazoHasta       *time.Time
	Orden            string
	Limit            int
	Despues          *Posicion // dónde seguir (cursor); nil = primera página
}

// Posicion es el último elemento servido: su clave de ordenación (en texto) y su identificador.
type Posicion struct {
	Clave string
	ID    string
}

// Fila es un expediente tal como lo devuelve la búsqueda.
type Fila struct {
	ID                string
	Fuente, IDOrigen  string
	Version           int
	Actualizada       time.Time
	Expediente        string
	EstadoOrigen      string
	Estado            string
	Titulo            string
	CompradorNombre   string
	CompradorNIF      string
	CompradorDIR3     string
	Procedimiento     string
	CPV, NUTS         []string
	Valor             *string // valor estimado, decimal
	Moneda            string
	Plazo             *time.Time
	Enlace            string
	SHA256, ClaveRaw  string
	Capturado         time.Time // última vez que el ingestor vio el expediente (aproximación de «capturado en»; POR VERIFICAR)
	Documento         []byte    // registro normalizado completo (solo en la ficha)
	ClaveOrden        string    // clave de ordenación de esta fila, para construir el cursor
	ProyectadaEn      time.Time
	PresupuestoSinIVA *string
	PresupuestoConIVA *string
	TipoContrato      string
}

type orden struct {
	expr, tipo string
	desc       bool
}

func ordenDe(o string, conTexto bool) (orden, error) {
	switch o {
	case "", OrdenActualizacion:
		return orden{"e.actualizada", "timestamptz", true}, nil
	case OrdenRelevancia:
		if !conTexto {
			return orden{}, errors.New("el orden por relevancia necesita texto de búsqueda")
		}
		return orden{"round(ts_rank(e.busqueda, q.tsq)::numeric, 6)", "numeric", true}, nil
	case OrdenPlazo:
		return orden{"coalesce(e.plazo_presentacion, 'infinity'::timestamptz)", "timestamptz", false}, nil
	case OrdenImporte:
		return orden{"coalesce(e.valor_estimado, -1)", "numeric", true}, nil
	}
	return orden{}, fmt.Errorf("orden desconocido %q", o)
}

// construye el WHERE y sus argumentos; q es true si hay texto (la consulta tendrá el alias q con el tsquery).
type consulta struct {
	where []string
	args  []any
}

func (c *consulta) arg(v any) string {
	c.args = append(c.args, v)
	return fmt.Sprintf("$%d", len(c.args))
}

func (c *consulta) add(cond string) { c.where = append(c.where, cond) }

func prefijos(vs []string) []string {
	out := make([]string, len(vs))
	for i, v := range vs {
		out[i] = v + "%"
	}
	return out
}

func (f Filtro) aplicar(c *consulta) {
	if f.Q != "" {
		c.add("e.busqueda @@ q.tsq")
	}
	if len(f.CPV) > 0 {
		c.add(fmt.Sprintf("EXISTS (SELECT 1 FROM unnest(e.cpv) x WHERE x LIKE ANY (%s::text[]))", c.arg(prefijos(f.CPV))))
	}
	if len(f.NUTS) > 0 {
		c.add(fmt.Sprintf("EXISTS (SELECT 1 FROM unnest(e.nuts) x WHERE x LIKE ANY (%s::text[]))", c.arg(prefijos(f.NUTS))))
	}
	if len(f.Estados) > 0 {
		c.add("e.estado = ANY (" + c.arg(f.Estados) + "::text[])")
	}
	if len(f.Procedimientos) > 0 {
		c.add("e.procedimiento = ANY (" + c.arg(f.Procedimientos) + "::text[])")
	}
	if len(f.Fuentes) > 0 {
		c.add("e.fuente = ANY (" + c.arg(f.Fuentes) + "::text[])")
	}
	if f.IDOrigen != "" {
		c.add("e.id_origen = " + c.arg(f.IDOrigen))
	}
	switch {
	case len(f.CompradorNIF) > 0 && len(f.CompradorDIR3) > 0:
		c.add(fmt.Sprintf("(e.comprador_nif = ANY (%s::text[]) OR e.comprador_dir3 = ANY (%s::text[]))", c.arg(f.CompradorNIF), c.arg(f.CompradorDIR3)))
	case len(f.CompradorNIF) > 0:
		c.add("e.comprador_nif = ANY (" + c.arg(f.CompradorNIF) + "::text[])")
	case len(f.CompradorDIR3) > 0:
		c.add("e.comprador_dir3 = ANY (" + c.arg(f.CompradorDIR3) + "::text[])")
	}
	if f.ImporteMin != "" {
		c.add("e.valor_estimado >= " + c.arg(f.ImporteMin) + "::numeric")
	}
	if f.ImporteMax != "" {
		c.add("e.valor_estimado <= " + c.arg(f.ImporteMax) + "::numeric")
	}
	if f.ActualizadaDesde != nil {
		c.add("e.actualizada >= " + c.arg(*f.ActualizadaDesde) + "::timestamptz")
	}
	if f.PlazoDesde != nil {
		c.add("e.plazo_presentacion >= " + c.arg(*f.PlazoDesde) + "::timestamptz")
	}
	if f.PlazoHasta != nil {
		c.add("e.plazo_presentacion <= " + c.arg(*f.PlazoHasta) + "::timestamptz")
	}
}

const columnas = `e.id::text, e.fuente, e.id_origen, e.version_entidad, e.actualizada, e.expediente, e.estado_origen, e.estado, e.titulo,
    e.comprador_nombre, e.comprador_nif, e.comprador_dir3, e.procedimiento, e.cpv, e.nuts, e.valor_estimado::text, e.moneda, e.plazo_presentacion,
    e.enlace, e.sha256_original, e.clave_original, coalesce(v.visto_ultima, e.proyectada), e.proyectada, e.presupuesto_sin_iva::text,
    e.presupuesto_con_iva::text, e.tipo_contrato`

func escanear(r pgx.Row, extra ...any) (Fila, error) {
	var f Fila
	dest := []any{&f.ID, &f.Fuente, &f.IDOrigen, &f.Version, &f.Actualizada, &f.Expediente, &f.EstadoOrigen, &f.Estado, &f.Titulo,
		&f.CompradorNombre, &f.CompradorNIF, &f.CompradorDIR3, &f.Procedimiento, &f.CPV, &f.NUTS, &f.Valor, &f.Moneda, &f.Plazo,
		&f.Enlace, &f.SHA256, &f.ClaveRaw, &f.Capturado, &f.ProyectadaEn, &f.PresupuestoSinIVA, &f.PresupuestoConIVA, &f.TipoContrato}
	return f, r.Scan(append(dest, extra...)...)
}

// Buscar devuelve una página de expedientes y el total (hasta MaxTotal; exacto=false indica «al menos»). Pide Limit+1 filas internamente
// para saber si hay más: si devuelve más de Limit filas, la última sobra y solo sirve para eso.
func (s *Store) Buscar(ctx context.Context, f Filtro) (filas []Fila, total int, exacto bool, err error) {
	ord, err := ordenDe(f.Orden, f.Q != "")
	if err != nil {
		return nil, 0, false, err
	}
	if f.Limit < 1 || f.Limit > 100 {
		return nil, 0, false, fmt.Errorf("limit fuera de rango: %d", f.Limit)
	}
	var c consulta
	from := "FROM expedientes e LEFT JOIN vistas v ON v.fuente = e.fuente AND v.id_origen = e.id_origen"
	if f.Q != "" {
		from += fmt.Sprintf(", (SELECT websearch_to_tsquery('spanish', %[1]s) || websearch_to_tsquery('catalan', %[1]s) AS tsq) q", c.arg(f.Q))
	}
	f.aplicar(&c)
	whereTotal := strings.Join(c.where, " AND ")
	if whereTotal == "" {
		whereTotal = "true"
	}
	argsTotal := append([]any(nil), c.args...)

	if f.Despues != nil {
		op := ">"
		if ord.desc {
			op = "<"
		}
		c.add(fmt.Sprintf("(%s, e.id) %s (%s::%s, %s::uuid)", ord.expr, op, c.arg(f.Despues.Clave), ord.tipo, c.arg(f.Despues.ID)))
	}
	dir := "ASC"
	if ord.desc {
		dir = "DESC"
	}
	where := strings.Join(c.where, " AND ")
	if where == "" {
		where = "true"
	}
	sql := fmt.Sprintf("SELECT %s, (%s)::text %s WHERE %s ORDER BY %s %s, e.id %s LIMIT %d", columnas, ord.expr, from, where, ord.expr, dir, dir, f.Limit+1)
	rows, err := s.pool.Query(ctx, sql, c.args...)
	if err != nil {
		return nil, 0, false, fmt.Errorf("pg: buscar expedientes: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var clave string
		fila, err := escanear(rows, &clave)
		if err != nil {
			return nil, 0, false, fmt.Errorf("pg: leer un expediente: %w", err)
		}
		fila.ClaveOrden = clave
		filas = append(filas, fila)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, false, fmt.Errorf("pg: leer los expedientes: %w", err)
	}
	rows.Close()

	var n int
	cq := fmt.Sprintf("SELECT count(*) FROM (SELECT 1 %s WHERE %s LIMIT %d) t", from, whereTotal, MaxTotal+1)
	if err := s.pool.QueryRow(ctx, cq, argsTotal...).Scan(&n); err != nil {
		return nil, 0, false, fmt.Errorf("pg: contar expedientes: %w", err)
	}
	if n > MaxTotal {
		return filas, MaxTotal, false, nil
	}
	return filas, n, true, nil
}

// ErrNoEncontrado se devuelve cuando el expediente no existe.
var ErrNoEncontrado = errors.New("pg: no encontrado")

// Expediente devuelve un expediente con su registro completo. El id no válido (que no es un UUID) cuenta como no encontrado.
func (s *Store) Expediente(ctx context.Context, id string) (Fila, error) {
	var doc []byte
	f, err := escanear(s.pool.QueryRow(ctx, `SELECT `+columnas+`, e.documento FROM expedientes e
		LEFT JOIN vistas v ON v.fuente = e.fuente AND v.id_origen = e.id_origen WHERE e.id::text = $1`, strings.ToLower(id)), &doc)
	if errors.Is(err, pgx.ErrNoRows) {
		return Fila{}, ErrNoEncontrado
	}
	if err != nil {
		return Fila{}, fmt.Errorf("pg: leer el expediente: %w", err)
	}
	f.Documento = doc
	return f, nil
}

// EstadoFuente es el último punto de control de una fuente.
type EstadoFuente struct {
	Fuente     string
	UltimaOK   *time.Time // nil si la última ejecución no terminó o nunca hubo una
	Expediente int        // expedientes proyectados de la fuente
}

// Fuentes devuelve el estado de las fuentes conocidas: las que tienen punto de control o expedientes.
func (s *Store) Fuentes(ctx context.Context) ([]EstadoFuente, error) {
	rows, err := s.pool.Query(ctx, `
SELECT f.fuente, CASE WHEN p.ultima_ejecucion > '2000-01-01' THEN p.ultima_ejecucion END, coalesce(c.n, 0)
FROM (SELECT fuente FROM puntos_control UNION SELECT fuente FROM expedientes) f
LEFT JOIN puntos_control p ON p.fuente = f.fuente
LEFT JOIN (SELECT fuente, count(*) AS n FROM expedientes GROUP BY fuente) c ON c.fuente = f.fuente
ORDER BY f.fuente`)
	if err != nil {
		return nil, fmt.Errorf("pg: leer las fuentes: %w", err)
	}
	defer rows.Close()
	var out []EstadoFuente
	for rows.Next() {
		var e EstadoFuente
		if err := rows.Scan(&e.Fuente, &e.UltimaOK, &e.Expediente); err != nil {
			return nil, fmt.Errorf("pg: leer una fuente: %w", err)
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

// Ping comprueba la base y devuelve lo que ha tardado.
func (s *Store) Ping(ctx context.Context) (time.Duration, error) {
	t0 := time.Now()
	var x int
	if err := s.pool.QueryRow(ctx, `SELECT 1`).Scan(&x); err != nil {
		return 0, fmt.Errorf("pg: ping: %w", err)
	}
	return time.Since(t0), nil
}
