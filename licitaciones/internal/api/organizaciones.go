package api

import (
	"errors"
	"net/http"
	"net/url"
	"regexp"
	"strings"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

var soportadosOrganizacion = map[string]bool{"desde": true, "hasta": true, "cpv": true}

var reVAT = regexp.MustCompile(`^vat:[A-Z]{2}[0-9A-Z]{2,13}$`)

// refOrganizacion traduce el identificador de la ruta (UUID de las listas, nif: o dir3:) al filtro de la base. Un NIF o un DIR3 dan el mismo UUID que las
// listas calculan para esa organización, así que todo se busca por UUID; el DIR3 se mira además entre los compradores (un comprador con NIF y DIR3 tiene el
// UUID de su NIF).
func refOrganizacion(id string) (pg.FiltroOrganizacion, *problem) {
	var f pg.FiltroOrganizacion
	switch {
	case reOrgUUID.MatchString(strings.ToLower(id)):
		f.ID = strings.ToLower(id)
	case reNIF.MatchString(id):
		f.ID = uuid8("org:" + reNIF.FindStringSubmatch(id)[1])
	case reDIR3.MatchString(id):
		d := reDIR3.FindStringSubmatch(id)[1]
		f.ID, f.DIR3 = uuid8("org:"+d), d
	case reVAT.MatchString(id):
		return f, invalid("id", "los identificadores vat: todavía no están disponibles")
	default:
		return f, invalid("id", "UUID de la organización, nif:XXXXXXXXX o dir3:XXXXXXXXX")
	}
	return f, nil
}

func parseOrganizacion(id string, q url.Values) (pg.FiltroOrganizacion, *problem) {
	f, p := refOrganizacion(id)
	if p != nil {
		return f, p
	}
	if p := comprobarNombres(q, soportadosOrganizacion); p != nil {
		return f, p
	}
	if f.CPV, p = lista(q, "cpv", 20, func(s string) bool { return reCPV.MatchString(s) }, "2 a 8 cifras"); p != nil {
		return f, p
	}
	if f.Desde, p = fecha(q, "desde"); p != nil {
		return f, p
	}
	if f.Hasta, p = fecha(q, "hasta"); p != nil {
		return f, p
	}
	if f.Desde != "" && f.Hasta != "" && f.Desde > f.Hasta {
		return f, invalid("desde", "no puede ser posterior a hasta")
	}
	return f, nil
}

// Identificador es un identificador oficial de una organización.
type Identificador struct {
	Esquema string `json:"esquema"`
	Valor   string `json:"valor"`
}

type cuotaCPV struct {
	CPV       string  `json:"cpv"`
	Contratos int     `json:"contratos"`
	Cuota     float64 `json:"cuota"`
}

type porTrimestre struct {
	Trimestre string  `json:"trimestre"`
	Contratos int     `json:"contratos"`
	Importe   Importe `json:"importe"`
}

type otraOrg struct {
	Organizacion OrganizacionRef `json:"organizacion"`
	Contratos    int             `json:"contratos"`
	Cuota        *float64        `json:"cuota,omitempty"`
}

// EstadisticasRol es EstadisticasMercado del contrato más lo propio de cada papel.
type EstadisticasRol struct {
	Contratos     int            `json:"contratos"`
	ImporteTotal  Importe        `json:"importe_total"`
	BajaMedia     *float64       `json:"baja_media"`
	BajaP25       *float64       `json:"baja_p25"`
	BajaP50       *float64       `json:"baja_p50"`
	BajaP75       *float64       `json:"baja_p75"`
	OfertasMedias *float64       `json:"ofertas_medias"`
	PorCPV        []cuotaCPV     `json:"por_cpv"`
	PorTrimestre  []porTrimestre `json:"por_trimestre"`
	Muestra       map[string]any `json:"muestra"`

	PrincipalesAdjudicatarios []otraOrg `json:"principales_adjudicatarios,omitempty"`
	RepeticionAdjudicatario   *float64  `json:"repeticion_adjudicatario,omitempty"`
	PrincipalesCompradores    []otraOrg `json:"principales_compradores,omitempty"`
}

// OrganizacionFicha es Organizacion del contrato.
type OrganizacionFicha struct {
	ID                  string           `json:"id"`
	Nombre              string           `json:"nombre"`
	NombresAlternativos []string         `json:"nombres_alternativos"`
	Identificadores     []Identificador  `json:"identificadores"`
	PersonaFisica       bool             `json:"persona_fisica"`
	Roles               []string         `json:"roles"`
	NUTS                []string         `json:"nuts"`
	ComoComprador       *EstadisticasRol `json:"como_comprador,omitempty"`
	ComoProveedor       *EstadisticasRol `json:"como_proveedor,omitempty"`
}

func estadisticasRol(s *pg.StatsRol, comprador bool) *EstadisticasRol {
	if s == nil {
		return nil
	}
	m := map[string]any{"adjudicaciones": s.Muestra.Adjudicaciones}
	if s.Muestra.Desde != nil {
		m["desde"] = *s.Muestra.Desde
	}
	if s.Muestra.Hasta != nil {
		m["hasta"] = *s.Muestra.Hasta
	}
	out := &EstadisticasRol{
		Contratos: s.Contratos, ImporteTotal: Importe{Valor: trimDecimal(s.Importe), Moneda: "EUR", Impuestos: "sin_iva", Significado: "adjudicado"},
		BajaMedia: redondearPtr(s.BajaMedia), BajaP25: redondearPtr(s.BajaP25), BajaP50: redondearPtr(s.BajaP50), BajaP75: redondearPtr(s.BajaP75),
		OfertasMedias: s.OfertasMedias, PorCPV: []cuotaCPV{}, PorTrimestre: []porTrimestre{}, Muestra: m,
	}
	for _, c := range s.PorCPV {
		q := 0.0
		if s.Contratos > 0 {
			q = redondear(float64(c.Contratos) / float64(s.Contratos))
		}
		out.PorCPV = append(out.PorCPV, cuotaCPV{CPV: c.CPV, Contratos: c.Contratos, Cuota: q})
	}
	for _, t := range s.PorTrimestre {
		out.PorTrimestre = append(out.PorTrimestre, porTrimestre{Trimestre: t.Trimestre, Contratos: t.Contratos,
			Importe: Importe{Valor: trimDecimal(t.Importe), Moneda: "EUR", Impuestos: "sin_iva", Significado: "adjudicado"}})
	}
	var otras []otraOrg
	for _, o := range s.Otras {
		ref := OrganizacionRef{ID: o.ID, Nombre: o.Nombre}
		if o.NIF != "" {
			nif := o.NIF
			ref.NIF = &nif
		}
		if o.DIR3 != "" {
			d := o.DIR3
			ref.DIR3 = &d
		}
		x := otraOrg{Organizacion: ref, Contratos: o.Contratos}
		if comprador { // la cuota va sobre el importe adjudicado por el comprador
			q := redondear(o.Cuota)
			x.Cuota = &q
		}
		otras = append(otras, x)
	}
	if comprador {
		out.PrincipalesAdjudicatarios, out.RepeticionAdjudicatario = otras, redondearPtr(s.Repeticion)
	} else {
		out.PrincipalesCompradores = otras
	}
	return out
}

func (s *Server) organizacion(w http.ResponseWriter, r *http.Request) {
	f, p := parseOrganizacion(r.PathValue("id"), r.URL.Query())
	if p != nil {
		writeProblem(w, r, p)
		return
	}
	ficha, err := s.Repo.Organizacion(r.Context(), f)
	switch {
	case errors.Is(err, pg.ErrOrganizacionSinDatos):
		writeProblem(w, r, newProblem(http.StatusNotFound, codNoEncontrado, "No encontrado", "No hay datos de esa organización."))
		return
	case err != nil:
		s.internal(w, r, err)
		return
	}
	out := OrganizacionFicha{ID: ficha.ID, Nombre: ficha.Nombre, NombresAlternativos: nonNil(ficha.Alternativos), PersonaFisica: ficha.PersonaFisica,
		NUTS: nonNil(ficha.NUTS), Identificadores: []Identificador{}, Roles: []string{},
		ComoComprador: estadisticasRol(ficha.Comprador, true), ComoProveedor: estadisticasRol(ficha.Proveedor, false)}
	if ficha.NIF != "" {
		out.Identificadores = append(out.Identificadores, Identificador{Esquema: "NIF", Valor: ficha.NIF})
	}
	if ficha.DIR3 != "" {
		out.Identificadores = append(out.Identificadores, Identificador{Esquema: "DIR3", Valor: ficha.DIR3})
	}
	if ficha.Comprador != nil {
		out.Roles = append(out.Roles, "comprador")
	}
	if ficha.Proveedor != nil {
		out.Roles = append(out.Roles, "proveedor")
	}
	writeJSON(w, http.StatusOK, out)
}
