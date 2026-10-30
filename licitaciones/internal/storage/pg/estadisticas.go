package pg

import (
	"context"
	"fmt"
	"strings"
)

// Cuenta es un grupo de un reparto: su valor, cuántas licitaciones tiene y, si procede, su importe sumado y el NIF del comprador.
type Cuenta struct {
	Valor   string
	NIF     string
	Cuenta  int
	Importe string // valor estimado sumado, decimal; vacío si el reparto no lo lleva
}

// Estadisticas son los agregados de TODOS los expedientes que cumplen un filtro (no solo los de una página): lo que alimenta el dashboard de la búsqueda.
type Estadisticas struct {
	Total        int
	ConImporte   int    // cuántos tienen valor estimado
	ImporteTotal string // suma del valor estimado, decimal
	ImporteMedio string // media del valor estimado, decimal; vacío si ninguno lo tiene
	Abiertas     int
	VencenSemana int // abiertas o con anuncio previo cuyo plazo termina en los próximos 7 días
	Estados      []Cuenta
	Zonas        []Cuenta // provincia (NUTS 3) del primer lugar de ejecución
	CPV          []Cuenta // división CPV (2 cifras) del primer código
	Importes     []Cuenta // tramos de valor estimado
	Compradores  []Cuenta
	Plazos       []Cuenta // por día (hora de Madrid) de los próximos 60 días
}

// Tramos de importe: clave y condición. El orden es el que se muestra.
var tramosImporte = []struct{ clave, cond string }{
	{"menos_15k", "e.valor_estimado < 15000"},
	{"15k_50k", "e.valor_estimado >= 15000 AND e.valor_estimado < 50000"},
	{"50k_200k", "e.valor_estimado >= 50000 AND e.valor_estimado < 200000"},
	{"200k_1m", "e.valor_estimado >= 200000 AND e.valor_estimado < 1000000"},
	{"mas_1m", "e.valor_estimado >= 1000000"},
}

// Estadisticas calcula los agregados con los mismos filtros que Buscar (ni orden, ni cursor, ni límite). Cada reparto es una consulta propia sobre el mismo
// WHERE: más sencillo de leer que una sola enorme, y todas comparten el contexto (y su plazo).
func (s *Store) Estadisticas(ctx context.Context, f Filtro) (Estadisticas, error) {
	var c consulta
	from := "FROM expedientes e"
	if f.Q != "" {
		from += fmt.Sprintf(", (SELECT websearch_to_tsquery('spanish', %[1]s) || websearch_to_tsquery('catalan', %[1]s) AS tsq) q", c.arg(f.Q))
	}
	f.aplicar(&c)
	donde := func(extra ...string) string {
		w := append(append([]string(nil), c.where...), extra...)
		if len(w) == 0 {
			return "true"
		}
		return strings.Join(w, " AND ")
	}
	var out Estadisticas

	err := s.pool.QueryRow(ctx, fmt.Sprintf(`SELECT count(*), count(e.valor_estimado), coalesce(sum(e.valor_estimado), 0)::text, coalesce(avg(e.valor_estimado)::text, ''),
		count(*) FILTER (WHERE %[1]s = 'abierta'),
		count(*) FILTER (WHERE %[1]s IN ('abierta', 'anuncio_previo') AND e.plazo_presentacion >= now() AND e.plazo_presentacion < now() + interval '7 days')
		%[2]s WHERE %[3]s`, estadoEfectivo, from, donde()), c.args...).
		Scan(&out.Total, &out.ConImporte, &out.ImporteTotal, &out.ImporteMedio, &out.Abiertas, &out.VencenSemana)
	if err != nil {
		return out, fmt.Errorf("pg: totales de la búsqueda: %w", err)
	}
	if out.Total == 0 {
		return out, nil
	}

	reparto := func(sql string, conNIF, conImporte bool) ([]Cuenta, error) {
		rows, err := s.pool.Query(ctx, sql, c.args...)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		var cs []Cuenta
		for rows.Next() {
			var x Cuenta
			dest := []any{&x.Valor}
			if conNIF {
				dest = append(dest, &x.NIF)
			}
			dest = append(dest, &x.Cuenta)
			if conImporte {
				dest = append(dest, &x.Importe)
			}
			if err := rows.Scan(dest...); err != nil {
				return nil, err
			}
			cs = append(cs, x)
		}
		return cs, rows.Err()
	}
	pasos := []struct {
		dst         *[]Cuenta
		sql         string
		nif, conImp bool
		que         string
	}{
		{&out.Estados, fmt.Sprintf("SELECT %s AS v, count(*) %s WHERE %s GROUP BY v ORDER BY count(*) DESC, v", estadoEfectivo, from, donde()), false, false, "estados"},
		{&out.Zonas, fmt.Sprintf("SELECT coalesce(left(e.nuts[1], 5), '') AS v, count(*) %s WHERE %s GROUP BY v ORDER BY count(*) DESC, v LIMIT 12", from, donde()), false, false, "zonas"},
		{&out.CPV, fmt.Sprintf("SELECT coalesce(left(e.cpv[1], 2), '') AS v, count(*) %s WHERE %s GROUP BY v ORDER BY count(*) DESC, v LIMIT 12", from, donde()), false, false, "CPV"},
		{&out.Compradores, fmt.Sprintf(`SELECT coalesce(nullif(e.comprador_nombre, ''), '(sin nombre)') AS v, coalesce(e.comprador_nif, ''), count(*), coalesce(sum(e.valor_estimado), 0)::text
			%s WHERE %s GROUP BY v, e.comprador_nif ORDER BY count(*) DESC, v LIMIT 10`, from, donde()), true, true, "compradores"},
		{&out.Plazos, fmt.Sprintf(`SELECT to_char((e.plazo_presentacion AT TIME ZONE 'Europe/Madrid')::date, 'YYYY-MM-DD') AS v, count(*) %s WHERE %s GROUP BY v ORDER BY v`, from,
			donde(estadoEfectivo+" IN ('abierta', 'anuncio_previo')", "e.plazo_presentacion >= now()", "e.plazo_presentacion < now() + interval '60 days'")), false, false, "plazos"},
	}
	for _, p := range pasos {
		cs, err := reparto(p.sql, p.nif, p.conImp)
		if err != nil {
			return out, fmt.Errorf("pg: reparto de %s: %w", p.que, err)
		}
		*p.dst = cs
	}

	// Tramos de importe: una sola pasada con FILTER por tramo (los sin importe van aparte).
	var cols []string
	for _, t := range tramosImporte {
		cols = append(cols, fmt.Sprintf("count(*) FILTER (WHERE %s)", t.cond))
	}
	cols = append(cols, "count(*) FILTER (WHERE e.valor_estimado IS NULL)")
	cuentas := make([]int, len(cols))
	dest := make([]any, len(cols))
	for i := range cuentas {
		dest[i] = &cuentas[i]
	}
	if err := s.pool.QueryRow(ctx, fmt.Sprintf("SELECT %s %s WHERE %s", strings.Join(cols, ", "), from, donde()), c.args...).Scan(dest...); err != nil {
		return out, fmt.Errorf("pg: tramos de importe: %w", err)
	}
	for i, t := range tramosImporte {
		out.Importes = append(out.Importes, Cuenta{Valor: t.clave, Cuenta: cuentas[i]})
	}
	out.Importes = append(out.Importes, Cuenta{Valor: "sin_importe", Cuenta: cuentas[len(tramosImporte)]})
	return out, nil
}
