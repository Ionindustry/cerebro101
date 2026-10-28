package api

import (
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

var (
	reOrgUUID = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
	reFecha   = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}$`)
)

// Parámetros de /awards y /competitors que el contrato define pero esta versión todavía no implementa: se rechazan en vez de ignorarlos.
var noSoportadosMercado = map[string]bool{"area": true}

var soportadosAdjudicaciones = map[string]bool{
	"q": true, "cpv": true, "nuts": true, "comprador": true, "adjudicatario": true, "fuente": true, "importe_min": true, "importe_max": true,
	"adjudicada_desde": true, "adjudicada_hasta": true, "resultado": true, "procedimiento": true, "orden": true, "limit": true, "cursor": true,
}

var soportadosCompetidores = map[string]bool{
	"cpv": true, "nuts": true, "comprador": true, "importe_min": true, "importe_max": true, "desde": true, "hasta": true, "orden": true,
	"limit": true, "cursor": true,
}

func fecha(q url.Values, campo string) (string, *problem) {
	v, ok := one(q, campo)
	if !ok {
		return "", nil
	}
	if _, err := time.Parse("2006-01-02", v); err != nil || !reFecha.MatchString(v) {
		return "", invalid(campo, "fecha «AAAA-MM-DD», p. ej. 2026-10-27")
	}
	return v, nil
}

func limite(q url.Values) (int, *problem) {
	v, ok := one(q, "limit")
	if !ok {
		return 20, nil
	}
	n, err := strconv.Atoi(v)
	if err != nil || n < 1 || n > 100 {
		return 0, invalid("limit", "entre 1 y 100")
	}
	return n, nil
}

// parseMercado lee los filtros comunes (cpv, nuts, comprador, importes y las dos fechas, que se llaman distinto según la ruta).
func parseMercado(q url.Values, campoDesde, campoHasta string) (pg.Mercado, *problem) {
	var m pg.Mercado
	var p *problem
	if m.CPV, p = lista(q, "cpv", 20, func(s string) bool { return reCPV.MatchString(s) }, "2 a 8 cifras"); p != nil {
		return m, p
	}
	if m.NUTS, p = lista(q, "nuts", 20, func(s string) bool { return reNUTS.MatchString(s) }, "código NUTS, p. ej. ES512"); p != nil {
		return m, p
	}
	cs, p := lista(q, "comprador", 20, func(string) bool { return true }, "")
	if p != nil {
		return m, p
	}
	for _, c := range cs {
		switch {
		case reNIF.MatchString(c):
			m.CompradorNIF = append(m.CompradorNIF, reNIF.FindStringSubmatch(c)[1])
		case reDIR3.MatchString(c):
			m.CompradorDIR3 = append(m.CompradorDIR3, reDIR3.FindStringSubmatch(c)[1])
		default:
			return m, invalid("comprador", "por ahora solo se admite nif:XXXXXXXXX o dir3:XXXXXXXXX")
		}
	}
	for campo, dst := range map[string]*string{"importe_min": &m.ImporteMin, "importe_max": &m.ImporteMax} {
		if v, ok := one(q, campo); ok {
			if !reImporte.MatchString(v) {
				return m, invalid(campo, "importe decimal en euros, p. ej. 125000.50")
			}
			*dst = v
		}
	}
	if campoDesde == "" { // /expiring-contracts tiene sus propias fechas (vence_desde, vence_hasta) y no filtra por fecha de adjudicación
		return m, nil
	}
	if m.Desde, p = fecha(q, campoDesde); p != nil {
		return m, p
	}
	if m.Hasta, p = fecha(q, campoHasta); p != nil {
		return m, p
	}
	if m.Desde != "" && m.Hasta != "" && m.Desde > m.Hasta {
		return m, invalid(campoDesde, "no puede ser posterior a "+campoHasta)
	}
	return m, nil
}

func comprobarNombres(q url.Values, soportados map[string]bool) *problem {
	for k := range q {
		switch {
		case noSoportadosMercado[k]:
			return invalid(k, "este parámetro todavía no está disponible")
		case !soportados[k]:
			return invalid(k, "parámetro desconocido")
		}
	}
	return nil
}

// parseAdjudicaciones valida los parámetros de /awards.
func parseAdjudicaciones(q url.Values) (pg.FiltroAdjudicaciones, *problem) {
	var f pg.FiltroAdjudicaciones
	if p := comprobarNombres(q, soportadosAdjudicaciones); p != nil {
		return f, p
	}
	var p *problem
	if f.Mercado, p = parseMercado(q, "adjudicada_desde", "adjudicada_hasta"); p != nil {
		return f, p
	}
	if v, ok := one(q, "q"); ok {
		v = strings.TrimSpace(v)
		if n := len([]rune(v)); n < 2 || n > 200 || strings.IndexFunc(v, unicode.IsControl) >= 0 {
			return f, invalid("q", "debe tener entre 2 y 200 caracteres, sin caracteres de control")
		}
		f.Q = v
	}
	as, p := lista(q, "adjudicatario", 20, func(string) bool { return true }, "")
	if p != nil {
		return f, p
	}
	for _, a := range as {
		switch {
		case reOrgUUID.MatchString(strings.ToLower(a)):
			f.AdjudicatarioID = append(f.AdjudicatarioID, strings.ToLower(a))
		case reNIF.MatchString(a):
			f.AdjudicatarioClave = append(f.AdjudicatarioClave, reNIF.FindStringSubmatch(a)[1])
		default:
			return f, invalid("adjudicatario", "por ahora solo se admite el UUID de la organización o nif:XXXXXXXXX")
		}
	}
	fs, p := lista(q, "fuente", 5, func(s string) bool { _, ok := fuentesExternas[s]; return ok }, "fuente desconocida")
	if p != nil {
		return f, p
	}
	for _, e := range fs {
		f.Fuentes = append(f.Fuentes, fuentesExternas[e])
	}
	if f.Procedimientos, p = lista(q, "procedimiento", 10, func(s string) bool { return procs[s] }, "procedimiento desconocido"); p != nil {
		return f, p
	}
	if v, ok := one(q, "resultado"); ok {
		if v != "adjudicado" && v != "desierto" {
			return f, invalid("resultado", "adjudicado o desierto")
		}
		f.Resultado = v
	}
	f.Orden = pg.OrdenFecha
	if v, ok := one(q, "orden"); ok {
		switch v {
		case pg.OrdenFecha, pg.OrdenImporte, pg.OrdenBaja:
			f.Orden = v
		default:
			return f, invalid("orden", "usa fecha, importe o baja")
		}
	}
	if f.Limit, p = limite(q); p != nil {
		return f, p
	}
	return f, nil
}

// parseCompetidores valida los parámetros de /competitors. Exige acotar el mercado (CPV, zona u organismo) para no listar todo.
func parseCompetidores(q url.Values) (pg.FiltroCompetidores, *problem) {
	var f pg.FiltroCompetidores
	if p := comprobarNombres(q, soportadosCompetidores); p != nil {
		return f, p
	}
	var p *problem
	if f.Mercado, p = parseMercado(q, "desde", "hasta"); p != nil {
		return f, p
	}
	if len(f.CPV) == 0 && len(f.NUTS) == 0 && len(f.CompradorNIF) == 0 && len(f.CompradorDIR3) == 0 {
		return f, invalid("cpv", "hay que acotar el mercado con al menos uno de cpv, nuts o comprador")
	}
	f.Orden = pg.OrdenImporte
	if v, ok := one(q, "orden"); ok {
		switch v {
		case pg.OrdenImporte, pg.OrdenContratos, pg.OrdenCuota:
			f.Orden = v
		default:
			return f, invalid("orden", "usa importe, contratos o cuota")
		}
	}
	if f.Limit, p = limite(q); p != nil {
		return f, p
	}
	return f, nil
}

var soportadosVencimientos = map[string]bool{
	"cpv": true, "nuts": true, "comprador": true, "importe_min": true, "vence_desde": true, "vence_hasta": true, "con_prorrogas": true, "limit": true, "cursor": true,
}

// MaxMesesVencimientos es la anchura máxima del periodo de /expiring-contracts (contrato: 36 meses desde vence_desde).
const MaxMesesVencimientos = 36

// parseVencimientos valida los parámetros de /expiring-contracts. Por defecto mira de hoy + 3 meses a hoy + 12 meses (contrato).
func parseVencimientos(q url.Values, hoy time.Time) (pg.FiltroVencimientos, *problem) {
	var f pg.FiltroVencimientos
	if p := comprobarNombres(q, soportadosVencimientos); p != nil {
		return f, p
	}
	var p *problem
	if f.Mercado, p = parseMercado(q, "", ""); p != nil {
		return f, p
	}
	hoy = hoy.UTC()
	f.VenceDesde, f.VenceHasta = hoy.AddDate(0, 3, 0).Format("2006-01-02"), hoy.AddDate(0, 12, 0).Format("2006-01-02")
	if f.VenceDesde, p = defectoFecha(q, "vence_desde", f.VenceDesde); p != nil {
		return f, p
	}
	if f.VenceHasta, p = defectoFecha(q, "vence_hasta", f.VenceHasta); p != nil {
		return f, p
	}
	desde, _ := time.Parse("2006-01-02", f.VenceDesde)
	hasta, _ := time.Parse("2006-01-02", f.VenceHasta)
	if hasta.Before(desde) {
		return f, invalid("vence_hasta", "no puede ser anterior a vence_desde")
	}
	if hasta.After(desde.AddDate(0, MaxMesesVencimientos, 0)) {
		return f, invalid("vence_hasta", "como máximo 36 meses desde vence_desde")
	}
	if v, ok := one(q, "con_prorrogas"); ok {
		switch v {
		case "true":
			f.ConProrrogas = true
		case "false":
		default:
			return f, invalid("con_prorrogas", "true o false")
		}
	}
	if f.Limit, p = limite(q); p != nil {
		return f, p
	}
	return f, nil
}

func defectoFecha(q url.Values, campo, defecto string) (string, *problem) {
	v, p := fecha(q, campo)
	if p != nil || v == "" {
		return defecto, p
	}
	return v, nil
}
