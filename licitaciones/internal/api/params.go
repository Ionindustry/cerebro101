package api

import (
	"fmt"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

// Fuentes del contrato (nombre externo) y su identificador interno.
var fuentesExternas = map[string]string{
	"placsp": "placsp-643", "placsp_agregadas": "placsp-1044", "placsp_menores": "placsp-1143", "ted": "ted", "cat": "cat",
}

func fuenteExterna(interna string) string {
	for ext, in := range fuentesExternas {
		if in == interna {
			return ext
		}
	}
	return interna
}

var (
	estados = map[string]bool{"anuncio_previo": true, "abierta": true, "cerrada": true, "adjudicada": true, "formalizada": true, "anulada": true, "desierta": true}
	procs   = map[string]bool{
		"abierto": true, "abierto_simplificado": true, "abierto_simplificado_abreviado": true, "restringido": true, "negociado_con_publicidad": true,
		"negociado_sin_publicidad": true, "dialogo_competitivo": true, "asociacion_innovacion": true, "licitacion_con_negociacion": true,
		"basado_en_acuerdo_marco": true, "menor": true, "otro": true,
	}
	reCPV     = regexp.MustCompile(`^[0-9]{2,8}$`)
	reNUTS    = regexp.MustCompile(`^[A-Z]{2}[0-9A-Z]{0,3}$`)
	reImporte = regexp.MustCompile(`^[0-9]{1,12}(\.[0-9]{1,2})?$`)
	reNIF     = regexp.MustCompile(`^nif:([0-9A-Z]{9})$`)
	reDIR3    = regexp.MustCompile(`^dir3:([0-9A-Z]{9,10})$`)
)

// Parámetros que el contrato define pero esta versión todavía no implementa: se rechazan en vez de ignorarlos en silencio.
var noSoportados = map[string]bool{"area": true, "publicada_desde": true, "publicada_hasta": true, "encaje_min": true, "facetas": true}

var soportados = map[string]bool{
	"q": true, "cpv": true, "nuts": true, "comprador": true, "estado": true, "procedimiento": true, "fuente": true, "importe_min": true,
	"importe_max": true, "actualizada_desde": true, "plazo_desde": true, "plazo_hasta": true, "orden": true, "limit": true, "cursor": true,
}

// parseBusqueda valida los parámetros de /tenders y construye el filtro. Cualquier problema es un 400 con el campo señalado.
func parseBusqueda(q url.Values) (pg.Filtro, *problem) {
	var f pg.Filtro
	for k := range q {
		switch {
		case noSoportados[k]:
			return f, invalid(k, "este parámetro todavía no está disponible")
		case !soportados[k]:
			return f, invalid(k, "parámetro desconocido")
		}
	}
	if v, ok := one(q, "q"); ok {
		v = strings.TrimSpace(v)
		if n := len([]rune(v)); n < 2 || n > 200 || strings.IndexFunc(v, unicode.IsControl) >= 0 {
			return f, invalid("q", "debe tener entre 2 y 200 caracteres, sin caracteres de control")
		}
		f.Q = v
	}
	var p *problem
	if f.CPV, p = lista(q, "cpv", 20, func(s string) bool { return reCPV.MatchString(s) }, "2 a 8 cifras"); p != nil {
		return f, p
	}
	if f.NUTS, p = lista(q, "nuts", 20, func(s string) bool { return reNUTS.MatchString(s) }, "código NUTS, p. ej. ES512"); p != nil {
		return f, p
	}
	if f.Estados, p = lista(q, "estado", 7, func(s string) bool { return estados[s] }, "estado desconocido"); p != nil {
		return f, p
	}
	if f.Procedimientos, p = lista(q, "procedimiento", 10, func(s string) bool { return procs[s] }, "procedimiento desconocido"); p != nil {
		return f, p
	}
	fs, p := lista(q, "fuente", 5, func(s string) bool { _, ok := fuentesExternas[s]; return ok }, "fuente desconocida")
	if p != nil {
		return f, p
	}
	for _, e := range fs {
		f.Fuentes = append(f.Fuentes, fuentesExternas[e])
	}
	cs, p := lista(q, "comprador", 20, func(string) bool { return true }, "")
	if p != nil {
		return f, p
	}
	for _, c := range cs {
		switch {
		case reNIF.MatchString(c):
			f.CompradorNIF = append(f.CompradorNIF, reNIF.FindStringSubmatch(c)[1])
		case reDIR3.MatchString(c):
			f.CompradorDIR3 = append(f.CompradorDIR3, reDIR3.FindStringSubmatch(c)[1])
		default:
			return f, invalid("comprador", "por ahora solo se admite nif:XXXXXXXXX o dir3:XXXXXXXXX")
		}
	}
	for campo, dst := range map[string]*string{"importe_min": &f.ImporteMin, "importe_max": &f.ImporteMax} {
		if v, ok := one(q, campo); ok {
			if !reImporte.MatchString(v) {
				return f, invalid(campo, "importe decimal en euros, p. ej. 125000.50")
			}
			*dst = v
		}
	}
	for campo, dst := range map[string]**time.Time{"actualizada_desde": &f.ActualizadaDesde, "plazo_desde": &f.PlazoDesde, "plazo_hasta": &f.PlazoHasta} {
		if v, ok := one(q, campo); ok {
			t, err := time.Parse(time.RFC3339, v)
			if err != nil {
				return f, invalid(campo, "fecha y hora RFC 3339, p. ej. 2026-10-27T10:00:00Z")
			}
			*dst = &t
		}
	}
	f.Orden = pg.OrdenActualizacion
	if f.Q != "" {
		f.Orden = pg.OrdenRelevancia
	}
	if v, ok := one(q, "orden"); ok {
		switch v {
		case pg.OrdenActualizacion, pg.OrdenPlazo, pg.OrdenImporte:
			f.Orden = v
		case pg.OrdenRelevancia:
			if f.Q == "" {
				return f, invalid("orden", "la relevancia necesita el parámetro q")
			}
			f.Orden = v
		case "encaje", "publicacion":
			return f, invalid("orden", "este orden todavía no está disponible")
		default:
			return f, invalid("orden", "usa relevancia, actualizacion, plazo o importe")
		}
	}
	f.Limit = 20
	if v, ok := one(q, "limit"); ok {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 || n > 100 {
			return f, invalid("limit", "entre 1 y 100")
		}
		f.Limit = n
	}
	return f, nil
}

func one(q url.Values, k string) (string, bool) {
	vs, ok := q[k]
	if !ok || len(vs) == 0 {
		return "", false
	}
	return vs[0], true
}

// lista lee un parámetro repetido (explode) o separado por comas, con tope de elementos y validación de cada uno.
func lista(q url.Values, k string, max int, ok func(string) bool, ayuda string) ([]string, *problem) {
	var out []string
	for _, v := range q[k] {
		for _, s := range strings.Split(v, ",") {
			if s = strings.TrimSpace(s); s != "" {
				out = append(out, s)
			}
		}
	}
	if len(out) > max {
		return nil, invalid(k, fmt.Sprintf("como máximo %d valores", max))
	}
	for _, s := range out {
		if !ok(s) {
			return nil, invalid(k, ayuda)
		}
	}
	return out, nil
}
