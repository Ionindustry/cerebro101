package pg

import (
	"context"
	"errors"
	"fmt"
	"strings"
)

// ErrOrganizacionSinDatos se devuelve cuando la organización no es comprador de ningún expediente ni adjudicataria de ninguna adjudicación.
var ErrOrganizacionSinDatos = errors.New("pg: organización desconocida")

// FiltroOrganizacion acota las estadísticas de una ficha (no su existencia): periodo de adjudicación y CPV.
type FiltroOrganizacion struct {
	ID           string // UUID de la organización (el mismo de las listas)
	DIR3         string // si la petición vino como dir3:X, también se busca por él entre los compradores (un comprador con NIF y DIR3 tiene el id del NIF)
	Desde, Hasta string // «AAAA-MM-DD», ambas incluidas; vacío = sin límite
	CPV          []string
}

// Contratos agrupa por CPV (grupo de 5 cifras).
type ContratosCPV struct {
	CPV       string
	Contratos int
}

// Trimestre es lo adjudicado en un trimestre natural, «2026-T3».
type Trimestre struct {
	Trimestre string
	Contratos int
	Importe   string
}

// Otra es una organización de la otra parte de las adjudicaciones (adjudicatario de un comprador, comprador de un adjudicatario).
type OrgContratos struct {
	ID, Nombre, NIF, DIR3 string
	Contratos             int
	Importe               string
	Cuota                 float64 // sobre el importe adjudicado en el rol y periodo
}

// StatsRol son las estadísticas de una organización en uno de sus dos papeles. Solo cuenta lo adjudicado, en euros.
type StatsRol struct {
	Contratos                   int
	Importe                     string
	BajaMedia, BajaP25, BajaP50 *float64
	BajaP75, OfertasMedias      *float64
	PorCPV                      []ContratosCPV
	PorTrimestre                []Trimestre
	Muestra                     MuestraMercado
	Otras                       []OrgContratos // principales adjudicatarios (comprador) o principales compradores (proveedor)
	Repeticion                  *float64       // solo comprador: proporción de contratos del adjudicatario más frecuente
}

// FichaOrganizacion es lo que se sabe de una organización.
type FichaOrganizacion struct {
	ID, Nombre, NIF, DIR3 string
	PersonaFisica         bool
	Alternativos          []string
	NUTS                  []string
	Comprador, Proveedor  *StatsRol // nil si la organización no actúa en ese papel
}

type rol struct {
	from  string // FROM con el alias a (adjudicaciones) y e (expedientes)
	donde string // condición del papel
}

// Organizacion devuelve la ficha de una organización por el UUID de las listas. Las estadísticas respetan el filtro; que exista o no, no.
func (s *Store) Organizacion(ctx context.Context, f FiltroOrganizacion) (*FichaOrganizacion, error) {
	const desde = "adjudicaciones a JOIN expedientes e ON e.id = a.expediente_id"
	comprador := rol{from: desde, donde: "(e.comprador_id = $1::uuid OR ($2 <> '' AND e.comprador_dir3 = $2))"}
	proveedor := rol{from: desde, donde: "a.adjudicatario_id = $1::uuid AND $2::text IS NOT NULL"} // $2 (el DIR3) no cuenta aquí, pero la consulta tiene que usarlo

	ficha := &FichaOrganizacion{ID: f.ID}
	var nCompra, nProv int
	// Identidad y existencia (sin filtros): el nombre más reciente de cada papel y los otros nombres con que aparece.
	row := s.pool.QueryRow(ctx, `
SELECT (SELECT count(*) FROM expedientes e WHERE e.comprador_id = $1::uuid OR ($2 <> '' AND e.comprador_dir3 = $2)),
       (SELECT count(*) FROM adjudicaciones a WHERE a.adjudicatario_id = $1::uuid AND a.resultado = 'adjudicado')`, f.ID, f.DIR3)
	if err := row.Scan(&nCompra, &nProv); err != nil {
		return nil, fmt.Errorf("pg: organización: %w", err)
	}
	if nCompra == 0 && nProv == 0 {
		return nil, ErrOrganizacionSinDatos
	}
	var nombres []string
	if nCompra > 0 {
		var comprador string
		err := s.pool.QueryRow(ctx, `SELECT e.comprador_id::text, e.comprador_nombre, e.comprador_nif, e.comprador_dir3 FROM expedientes e
			WHERE e.comprador_id = $1::uuid OR ($2 <> '' AND e.comprador_dir3 = $2) ORDER BY e.actualizada DESC, e.id LIMIT 1`, f.ID, f.DIR3).Scan(&comprador, &ficha.Nombre, &ficha.NIF, &ficha.DIR3)
		if err != nil {
			return nil, fmt.Errorf("pg: identidad del comprador: %w", err)
		}
		ficha.ID = comprador
		otros, err := s.textos(ctx, `SELECT DISTINCT e.comprador_nombre FROM expedientes e WHERE (e.comprador_id = $1::uuid OR ($2 <> '' AND e.comprador_dir3 = $2)) AND e.comprador_nombre <> '' LIMIT 20`, f.ID, f.DIR3)
		if err != nil {
			return nil, fmt.Errorf("pg: nombres del comprador: %w", err)
		}
		nombres = append(nombres, otros...)
	}
	if nProv > 0 {
		var nombre, nif, clave string
		err := s.pool.QueryRow(ctx, `SELECT a.adjudicatario_nombre, a.adjudicatario_nif, a.adjudicatario_clave FROM adjudicaciones a
			WHERE a.adjudicatario_id = $1::uuid ORDER BY a.fecha_adjudicacion DESC NULLS LAST, a.id LIMIT 1`, f.ID).Scan(&nombre, &nif, &clave)
		if err != nil {
			return nil, fmt.Errorf("pg: identidad del adjudicatario: %w", err)
		}
		if ficha.Nombre == "" {
			ficha.Nombre, ficha.NIF = nombre, nif
		}
		ficha.PersonaFisica = strings.HasPrefix(clave, "n:")
		otros, err := s.textos(ctx, `SELECT DISTINCT a.adjudicatario_nombre FROM adjudicaciones a WHERE a.adjudicatario_id = $1::uuid AND a.adjudicatario_nombre <> '' LIMIT 20`, f.ID)
		if err != nil {
			return nil, fmt.Errorf("pg: nombres del adjudicatario: %w", err)
		}
		nombres = append(nombres, otros...)
	}
	vistos := map[string]bool{ficha.Nombre: true}
	for _, n := range nombres {
		if !vistos[n] && len(ficha.Alternativos) < 10 {
			vistos[n] = true
			ficha.Alternativos = append(ficha.Alternativos, n)
		}
	}
	var err error
	if nCompra > 0 {
		if ficha.Comprador, err = s.statsRol(ctx, comprador, f, true); err != nil {
			return nil, err
		}
	}
	if nProv > 0 {
		if ficha.Proveedor, err = s.statsRol(ctx, proveedor, f, false); err != nil {
			return nil, err
		}
	}
	ficha.NUTS, err = s.textos(ctx, `
SELECT n FROM (
  SELECT unnest(e.nuts) AS n FROM expedientes e WHERE e.comprador_id = $1::uuid OR ($2 <> '' AND e.comprador_dir3 = $2)
  UNION ALL
  SELECT unnest(e.nuts) FROM adjudicaciones a JOIN expedientes e ON e.id = a.expediente_id WHERE a.adjudicatario_id = $1::uuid) t
WHERE n <> '' GROUP BY n ORDER BY count(*) DESC, n LIMIT 10`, f.ID, f.DIR3)
	if err != nil {
		return nil, fmt.Errorf("pg: zonas de la organización: %w", err)
	}
	return ficha, nil
}

// textos ejecuta una consulta de una sola columna de texto y devuelve sus filas.
func (s *Store) textos(ctx context.Context, sql string, args ...any) ([]string, error) {
	rows, err := s.pool.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var t string
		if err := rows.Scan(&t); err != nil {
			return nil, fmt.Errorf("leer un texto: %w", err)
		}
		out = append(out, t)
	}
	return out, rows.Err()
}

// statsRol calcula las estadísticas del papel con los filtros de la ficha. Los argumentos 1 y 2 son siempre el id y el DIR3; los filtros empiezan en el 3.
func (s *Store) statsRol(ctx context.Context, r rol, f FiltroOrganizacion, esComprador bool) (*StatsRol, error) {
	var c consulta
	c.args = []any{f.ID, f.DIR3}
	c.add(r.donde)
	c.add("a.resultado = 'adjudicado'")
	c.add("a.moneda = 'EUR'")
	if f.Desde != "" {
		c.add("a.fecha_adjudicacion >= " + c.arg(f.Desde) + "::date")
	}
	if f.Hasta != "" {
		c.add("a.fecha_adjudicacion <= " + c.arg(f.Hasta) + "::date")
	}
	if len(f.CPV) > 0 {
		c.add(fmt.Sprintf("EXISTS (SELECT 1 FROM unnest(e.cpv) x WHERE x LIKE ANY (%s::text[]))", c.arg(prefijos(f.CPV))))
	}
	base := fmt.Sprintf("WITH base AS (SELECT a.*, e.cpv, e.comprador_id, e.comprador_nombre, e.comprador_nif, e.comprador_dir3 FROM %s WHERE %s)", r.from, strings.Join(c.where, " AND "))
	out := &StatsRol{}
	err := s.pool.QueryRow(ctx, base+`
SELECT count(*), coalesce(sum(importe_sin_iva), 0)::text, avg(baja)::float8,
       (percentile_cont(0.25) WITHIN GROUP (ORDER BY baja))::float8, (percentile_cont(0.5) WITHIN GROUP (ORDER BY baja))::float8,
       (percentile_cont(0.75) WITHIN GROUP (ORDER BY baja))::float8, avg(ofertas_recibidas)::float8, min(fecha_adjudicacion)::text, max(fecha_adjudicacion)::text FROM base`, c.args...).
		Scan(&out.Contratos, &out.Importe, &out.BajaMedia, &out.BajaP25, &out.BajaP50, &out.BajaP75, &out.OfertasMedias, &out.Muestra.Desde, &out.Muestra.Hasta)
	if err != nil {
		return nil, fmt.Errorf("pg: estadísticas de la organización: %w", err)
	}
	out.Muestra.Adjudicaciones = out.Contratos

	rows, err := s.pool.Query(ctx, base+`
SELECT left(c, 5), count(*) FROM (SELECT DISTINCT id, unnest(cpv) AS c FROM base) t GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 8`, c.args...)
	if err != nil {
		return nil, fmt.Errorf("pg: CPV de la organización: %w", err)
	}
	for rows.Next() {
		var x ContratosCPV
		if err := rows.Scan(&x.CPV, &x.Contratos); err != nil {
			rows.Close()
			return nil, fmt.Errorf("pg: leer un CPV: %w", err)
		}
		out.PorCPV = append(out.PorCPV, x)
	}
	rows.Close()

	rows, err = s.pool.Query(ctx, base+`
SELECT to_char(fecha_adjudicacion, 'YYYY') || '-T' || extract(quarter FROM fecha_adjudicacion)::int, count(*), coalesce(sum(importe_sin_iva), 0)::text
FROM base WHERE fecha_adjudicacion IS NOT NULL GROUP BY 1 ORDER BY 1`, c.args...)
	if err != nil {
		return nil, fmt.Errorf("pg: trimestres de la organización: %w", err)
	}
	for rows.Next() {
		var x Trimestre
		if err := rows.Scan(&x.Trimestre, &x.Contratos, &x.Importe); err != nil {
			rows.Close()
			return nil, fmt.Errorf("pg: leer un trimestre: %w", err)
		}
		out.PorTrimestre = append(out.PorTrimestre, x)
	}
	rows.Close()
	if n := len(out.PorTrimestre); n > 16 {
		out.PorTrimestre = out.PorTrimestre[n-16:]
	}

	// La otra parte: a quién adjudica un comprador / a quién vende un adjudicatario.
	var otras string
	if esComprador {
		otras = `SELECT adjudicatario_id::text, (array_agg(adjudicatario_nombre ORDER BY fecha_adjudicacion DESC NULLS LAST, id))[1], max(adjudicatario_nif), '',
		count(*), coalesce(sum(importe_sin_iva), 0)::text, sum(coalesce(importe_sin_iva, 0))::float8
		FROM base WHERE adjudicatario_clave <> '' GROUP BY adjudicatario_id ORDER BY count(*) DESC, sum(coalesce(importe_sin_iva, 0)) DESC, adjudicatario_id LIMIT 5`
	} else {
		otras = `SELECT comprador_id::text, (array_agg(comprador_nombre ORDER BY fecha_adjudicacion DESC NULLS LAST, id))[1], max(comprador_nif), max(comprador_dir3),
		count(*), coalesce(sum(importe_sin_iva), 0)::text, sum(coalesce(importe_sin_iva, 0))::float8
		FROM base WHERE comprador_id IS NOT NULL GROUP BY comprador_id ORDER BY count(*) DESC, sum(coalesce(importe_sin_iva, 0)) DESC, comprador_id LIMIT 5`
	}
	rows, err = s.pool.Query(ctx, base+otras, c.args...)
	if err != nil {
		return nil, fmt.Errorf("pg: contrapartes de la organización: %w", err)
	}
	var total float64
	var importes []float64
	for rows.Next() {
		var x OrgContratos
		var suma float64
		if err := rows.Scan(&x.ID, &x.Nombre, &x.NIF, &x.DIR3, &x.Contratos, &x.Importe, &suma); err != nil {
			rows.Close()
			return nil, fmt.Errorf("pg: leer una contraparte: %w", err)
		}
		importes = append(importes, suma)
		out.Otras = append(out.Otras, x)
	}
	rows.Close()
	if err := s.pool.QueryRow(ctx, base+`SELECT coalesce(sum(importe_sin_iva), 0)::float8 FROM base`, c.args...).Scan(&total); err != nil {
		return nil, fmt.Errorf("pg: total de la organización: %w", err)
	}
	for i := range out.Otras {
		if total > 0 {
			out.Otras[i].Cuota = importes[i] / total
		}
	}
	if esComprador && out.Contratos > 0 {
		var conGanador, masFrecuente int
		if err := s.pool.QueryRow(ctx, base+`SELECT coalesce(sum(n) FILTER (WHERE clave <> ''), 0)::int, coalesce(max(n) FILTER (WHERE clave <> ''), 0)::int
			FROM (SELECT adjudicatario_clave AS clave, count(*) AS n FROM base GROUP BY 1) g`, c.args...).Scan(&conGanador, &masFrecuente); err != nil {
			return nil, fmt.Errorf("pg: repetición del adjudicatario: %w", err)
		}
		if conGanador > 0 {
			r := float64(masFrecuente) / float64(conGanador)
			out.Repeticion = &r
		}
	}
	return out, nil
}
