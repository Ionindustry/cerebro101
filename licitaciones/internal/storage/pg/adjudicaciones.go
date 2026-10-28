package pg

import (
	"context"
	"fmt"
	"strings"
	"time"
)

// Órdenes admitidos en /awards y /competitors.
const (
	OrdenFecha     = "fecha"     // adjudicación más reciente primero
	OrdenBaja      = "baja"      // mayor baja primero; sin baja, al final
	OrdenContratos = "contratos" // más contratos ganados primero (competidores)
	OrdenCuota     = "cuota"     // mayor cuota primero (competidores; equivale al importe)
)

// Mercado son los filtros comunes a las adjudicaciones y a los competidores. Los valores van siempre como parámetros, nunca dentro del SQL.
type Mercado struct {
	CPV, NUTS     []string // prefijos de 2 a 8 cifras / códigos NUTS; varios = O
	CompradorNIF  []string
	CompradorDIR3 []string
	ImporteMin    string // decimal sobre el importe adjudicado sin IVA; vacío = sin límite
	ImporteMax    string
	Desde, Hasta  string // fecha de adjudicación «AAAA-MM-DD», ambas incluidas; vacío = sin límite
}

// FiltroAdjudicaciones describe una búsqueda de /awards ya validada.
type FiltroAdjudicaciones struct {
	Mercado
	Q                  string
	AdjudicatarioClave []string // NIF (nif:…)
	AdjudicatarioID    []string // UUID de la organización
	Fuentes            []string
	Procedimientos     []string
	Resultado          string // «adjudicado», «desierto» o vacío
	Orden              string
	Limit              int
	Despues            *Posicion
}

// Adjudicacion es una adjudicación por lote tal como la devuelve la búsqueda.
type Adjudicacion struct {
	ID, ExpedienteID                             string
	Expediente, Titulo, Lote, Resultado          string
	CompradorNombre, CompradorNIF, CompradorDIR3 string
	AdjudicatarioNombre, AdjudicatarioNIF        string
	AdjudicatarioID                              *string
	Moneda                                       string
	ImporteSinIVA, ImporteConIVA, Presupuesto    *string
	OfertaMasBaja, OfertaMasAlta, Baja           *string
	Ofertas                                      *int
	BajaAnormal                                  *bool
	FechaAdjudicacion, FechaFormalizacion        *string
	Procedimiento                                string
	CPV, NUTS                                    []string
	Fuente, IDOrigen, Enlace, SHA256, ClaveRaw   string
	Capturado                                    time.Time
	ClaveOrden                                   string
}

// aplicar añade los filtros del mercado sobre las tablas a (adjudicaciones) y e (expedientes).
func (m Mercado) aplicar(c *consulta) {
	if len(m.CPV) > 0 {
		c.add(fmt.Sprintf("EXISTS (SELECT 1 FROM unnest(e.cpv) x WHERE x LIKE ANY (%s::text[]))", c.arg(prefijos(m.CPV))))
	}
	if len(m.NUTS) > 0 {
		c.add(fmt.Sprintf("EXISTS (SELECT 1 FROM unnest(e.nuts) x WHERE x LIKE ANY (%s::text[]))", c.arg(prefijos(m.NUTS))))
	}
	switch {
	case len(m.CompradorNIF) > 0 && len(m.CompradorDIR3) > 0:
		c.add(fmt.Sprintf("(e.comprador_nif = ANY (%s::text[]) OR e.comprador_dir3 = ANY (%s::text[]))", c.arg(m.CompradorNIF), c.arg(m.CompradorDIR3)))
	case len(m.CompradorNIF) > 0:
		c.add("e.comprador_nif = ANY (" + c.arg(m.CompradorNIF) + "::text[])")
	case len(m.CompradorDIR3) > 0:
		c.add("e.comprador_dir3 = ANY (" + c.arg(m.CompradorDIR3) + "::text[])")
	}
	if m.ImporteMin != "" {
		c.add("a.importe_sin_iva >= " + c.arg(m.ImporteMin) + "::numeric")
	}
	if m.ImporteMax != "" {
		c.add("a.importe_sin_iva <= " + c.arg(m.ImporteMax) + "::numeric")
	}
	if m.Desde != "" {
		c.add("a.fecha_adjudicacion >= " + c.arg(m.Desde) + "::date")
	}
	if m.Hasta != "" {
		c.add("a.fecha_adjudicacion <= " + c.arg(m.Hasta) + "::date")
	}
}

func ordenAdjudicaciones(o string) (orden, error) {
	switch o {
	case "", OrdenFecha:
		return orden{"coalesce(a.fecha_adjudicacion, '0001-01-01'::date)", "date", true}, nil
	case OrdenImporte:
		return orden{"coalesce(a.importe_sin_iva, -1)", "numeric", true}, nil
	case OrdenBaja:
		return orden{"coalesce(a.baja, -1000)", "numeric", true}, nil
	}
	return orden{}, fmt.Errorf("orden desconocido %q", o)
}

const columnasAdjudicacion = `a.id::text, a.expediente_id::text, e.expediente, e.titulo, a.lote, a.resultado, e.comprador_nombre, e.comprador_nif,
    e.comprador_dir3, a.adjudicatario_nombre, a.adjudicatario_nif, a.adjudicatario_id::text, a.moneda, a.importe_sin_iva::text,
    a.importe_con_iva::text, a.presupuesto_sin_iva::text, a.oferta_mas_baja::text, a.oferta_mas_alta::text, a.baja::text, a.ofertas_recibidas,
    a.baja_anormal, a.fecha_adjudicacion::text, a.fecha_formalizacion::text, e.procedimiento, e.cpv, e.nuts, e.fuente, e.id_origen, e.enlace,
    e.sha256_original, e.clave_original, coalesce(v.visto_ultima, e.proyectada)`

// BuscarAdjudicaciones devuelve una página de adjudicaciones y el total (hasta MaxTotal; exacto=false indica «al menos»). Pide Limit+1 filas
// internamente: si devuelve más de Limit, la última sobra y solo sirve para saber que hay más.
func (s *Store) BuscarAdjudicaciones(ctx context.Context, f FiltroAdjudicaciones) (filas []Adjudicacion, total int, exacto bool, err error) {
	ord, err := ordenAdjudicaciones(f.Orden)
	if err != nil {
		return nil, 0, false, err
	}
	if f.Limit < 1 || f.Limit > 100 {
		return nil, 0, false, fmt.Errorf("limit fuera de rango: %d", f.Limit)
	}
	var c consulta
	from := `FROM adjudicaciones a JOIN expedientes e ON e.id = a.expediente_id
		LEFT JOIN vistas v ON v.fuente = e.fuente AND v.id_origen = e.id_origen`
	if f.Q != "" {
		from += fmt.Sprintf(", (SELECT websearch_to_tsquery('spanish', %[1]s) || websearch_to_tsquery('catalan', %[1]s) AS tsq) q", c.arg(f.Q))
		c.add("e.busqueda @@ q.tsq")
	}
	f.aplicar(&c)
	if len(f.AdjudicatarioClave) > 0 {
		c.add("a.adjudicatario_clave = ANY (" + c.arg(f.AdjudicatarioClave) + "::text[])")
	}
	if len(f.AdjudicatarioID) > 0 {
		c.add("a.adjudicatario_id = ANY (" + c.arg(f.AdjudicatarioID) + "::uuid[])")
	}
	if len(f.Fuentes) > 0 {
		c.add("e.fuente = ANY (" + c.arg(f.Fuentes) + "::text[])")
	}
	if len(f.Procedimientos) > 0 {
		c.add("e.procedimiento = ANY (" + c.arg(f.Procedimientos) + "::text[])")
	}
	if f.Resultado != "" {
		c.add("a.resultado = " + c.arg(f.Resultado))
	}
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
		c.add(fmt.Sprintf("(%s, a.id) %s (%s::%s, %s::uuid)", ord.expr, op, c.arg(f.Despues.Clave), ord.tipo, c.arg(f.Despues.ID)))
	}
	where := strings.Join(c.where, " AND ")
	if where == "" {
		where = "true"
	}
	sql := fmt.Sprintf("SELECT %s, (%s)::text %s WHERE %s ORDER BY %s DESC, a.id DESC LIMIT %d", columnasAdjudicacion, ord.expr, from, where, ord.expr, f.Limit+1)
	rows, err := s.pool.Query(ctx, sql, c.args...)
	if err != nil {
		return nil, 0, false, fmt.Errorf("pg: buscar adjudicaciones: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var a Adjudicacion
		if err := rows.Scan(&a.ID, &a.ExpedienteID, &a.Expediente, &a.Titulo, &a.Lote, &a.Resultado, &a.CompradorNombre, &a.CompradorNIF,
			&a.CompradorDIR3, &a.AdjudicatarioNombre, &a.AdjudicatarioNIF, &a.AdjudicatarioID, &a.Moneda, &a.ImporteSinIVA,
			&a.ImporteConIVA, &a.Presupuesto, &a.OfertaMasBaja, &a.OfertaMasAlta, &a.Baja, &a.Ofertas,
			&a.BajaAnormal, &a.FechaAdjudicacion, &a.FechaFormalizacion, &a.Procedimiento, &a.CPV, &a.NUTS, &a.Fuente, &a.IDOrigen, &a.Enlace,
			&a.SHA256, &a.ClaveRaw, &a.Capturado, &a.ClaveOrden); err != nil {
			return nil, 0, false, fmt.Errorf("pg: leer una adjudicación: %w", err)
		}
		filas = append(filas, a)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, false, fmt.Errorf("pg: leer las adjudicaciones: %w", err)
	}
	rows.Close()

	var n int
	cq := fmt.Sprintf("SELECT count(*) FROM (SELECT 1 %s WHERE %s LIMIT %d) t", from, whereTotal, MaxTotal+1)
	if err := s.pool.QueryRow(ctx, cq, argsTotal...).Scan(&n); err != nil {
		return nil, 0, false, fmt.Errorf("pg: contar adjudicaciones: %w", err)
	}
	if n > MaxTotal {
		return filas, MaxTotal, false, nil
	}
	return filas, n, true, nil
}

// FiltroCompetidores describe una consulta de /competitors ya validada.
type FiltroCompetidores struct {
	Mercado
	Orden   string
	Limit   int
	Despues *Posicion // clave de ordenación y NIF o clave del adjudicatario del último elemento servido
}

// Competidor es un adjudicatario con sus estadísticas en el mercado filtrado. Solo cuenta lo adjudicado (no los desiertos) y en euros.
type Competidor struct {
	ID, Clave, Nombre, NIF string
	Contratos              int
	Importe                string // suma de lo adjudicado sin IVA
	Cuota                  float64
	BajaMedia, BajaP50     *float64
	Ultima                 *string
	Tendencia              string // sube, estable, baja o sin_datos
	ClaveOrden             string
}

// MuestraMercado es cuántos datos hay detrás de la consulta (§6: siempre visible).
type MuestraMercado struct {
	Adjudicaciones int
	Desde, Hasta   *string
}

// tendencia compara los contratos de los últimos 12 meses con los 12 anteriores (contados hacia atrás desde «hasta» o, sin él, desde hoy).
// Con menos de tres contratos en total no hay datos suficientes para hablar de tendencia.
const tendenciaSQL = `CASE WHEN g.contratos < 3 THEN 'sin_datos' WHEN g.recientes > g.previos THEN 'sube' WHEN g.recientes < g.previos THEN 'baja' ELSE 'estable' END`

// Competidores devuelve el ranking de adjudicatarios del mercado y cuántos hay en total (hasta MaxTotal).
func (s *Store) Competidores(ctx context.Context, f FiltroCompetidores) (filas []Competidor, total int, muestra MuestraMercado, err error) {
	if f.Limit < 1 || f.Limit > 100 {
		return nil, 0, muestra, fmt.Errorf("limit fuera de rango: %d", f.Limit)
	}
	var clave, tipo string // expresión de ordenación sobre la subconsulta t y su tipo
	switch f.Orden {
	case "", OrdenImporte, OrdenCuota:
		clave, tipo = "t.importe_txt::numeric", "numeric"
	case OrdenContratos:
		clave, tipo = "t.contratos", "bigint"
	default:
		return nil, 0, muestra, fmt.Errorf("orden desconocido %q", f.Orden)
	}
	var c consulta
	c.add("a.resultado = 'adjudicado'")
	c.add("a.adjudicatario_clave <> ''")
	c.add("a.moneda = 'EUR'")
	f.aplicar(&c)
	ref := "current_date"
	if f.Hasta != "" {
		ref = "(" + c.arg(f.Hasta) + "::date)"
	}
	var despues string
	if f.Despues != nil {
		despues = fmt.Sprintf("WHERE (%s, t.clave) < (%s::%s, %s::text)", clave, c.arg(f.Despues.Clave), tipo, c.arg(f.Despues.ID))
	}
	sql := fmt.Sprintf(`
WITH base AS (
    SELECT a.* FROM adjudicaciones a JOIN expedientes e ON e.id = a.expediente_id WHERE %[1]s
), mercado AS (
    SELECT coalesce(sum(importe_sin_iva), 0) AS total, count(*) AS n, min(fecha_adjudicacion)::text AS desde, max(fecha_adjudicacion)::text AS hasta FROM base
), grupos AS (
    SELECT adjudicatario_clave AS clave,
           (array_agg(adjudicatario_nombre ORDER BY fecha_adjudicacion DESC NULLS LAST, id))[1] AS nombre,
           max(adjudicatario_nif) AS nif, (array_agg(adjudicatario_id ORDER BY id))[1]::text AS org_id,
           count(*) AS contratos, coalesce(sum(importe_sin_iva), 0) AS importe,
           avg(baja)::float8 AS baja_media, (percentile_cont(0.5) WITHIN GROUP (ORDER BY baja))::float8 AS baja_p50,
           max(fecha_adjudicacion)::text AS ultima,
           count(*) FILTER (WHERE fecha_adjudicacion > %[2]s - 365 AND fecha_adjudicacion <= %[2]s) AS recientes,
           count(*) FILTER (WHERE fecha_adjudicacion > %[2]s - 730 AND fecha_adjudicacion <= %[2]s - 365) AS previos
    FROM base GROUP BY adjudicatario_clave
)
SELECT t.*, m.n, m.desde, m.hasta FROM (
    SELECT g.clave, g.nombre, g.nif, g.org_id, g.contratos, g.importe::text AS importe_txt, g.baja_media, g.baja_p50, g.ultima,
           CASE WHEN m.total > 0 THEN (g.importe / m.total)::float8 ELSE 0 END AS cuota, %[3]s AS tendencia, count(*) OVER () AS grupos
    FROM grupos g, mercado m
) t, mercado m %[4]s
ORDER BY %[5]s DESC, t.clave DESC LIMIT %[6]d`, strings.Join(c.where, " AND "), ref, tendenciaSQL, despues, clave, f.Limit+1)
	rows, err := s.pool.Query(ctx, sql, c.args...)
	if err != nil {
		return nil, 0, muestra, fmt.Errorf("pg: competidores: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var x Competidor
		var grupos int
		if err := rows.Scan(&x.Clave, &x.Nombre, &x.NIF, &x.ID, &x.Contratos, &x.Importe, &x.BajaMedia, &x.BajaP50, &x.Ultima,
			&x.Cuota, &x.Tendencia, &grupos, &muestra.Adjudicaciones, &muestra.Desde, &muestra.Hasta); err != nil {
			return nil, 0, muestra, fmt.Errorf("pg: leer un competidor: %w", err)
		}
		x.ClaveOrden = x.Importe
		if f.Orden == OrdenContratos {
			x.ClaveOrden = fmt.Sprint(x.Contratos)
		}
		total = grupos
		filas = append(filas, x)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, muestra, fmt.Errorf("pg: leer los competidores: %w", err)
	}
	return filas, min(total, MaxTotal), muestra, nil
}
