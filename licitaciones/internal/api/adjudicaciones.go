package api

import (
	"fmt"
	"net/http"
	"regexp"
	"strconv"
	"strings"

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

var reNIFCompleto = regexp.MustCompile(`^[0-9A-Za-z]{9}$`)

// claveAdjudicatario es la clave con la que se identifica a un adjudicatario: su NIF si es uno completo; si no (persona física con el NIF tapado,
// sin identificador) su nombre en minúsculas con el prefijo «n:». Debe dar lo mismo que la proyección SQL (`lic_proyectar_adjudicaciones`): una
// prueba lo comprueba con datos reales. Un resultado desierto no tiene adjudicatario.
func claveAdjudicatario(r domain.Result) (clave, nif string) {
	if r.Code == domain.ResultVoid {
		return "", ""
	}
	if reNIFCompleto.MatchString(r.WinnerID) {
		n := strings.ToUpper(r.WinnerID)
		return n, n
	}
	if r.WinnerName != "" {
		return "n:" + strings.ToLower(r.WinnerName), ""
	}
	return "", ""
}

// orgAdjudicatario es la referencia a un adjudicatario; el id sale de su clave, igual que en la base.
func orgAdjudicatario(nombre, clave, nif string) *OrganizacionRef {
	if clave == "" {
		return nil
	}
	o := &OrganizacionRef{ID: uuid8("org:" + clave), Nombre: nombre}
	if nif != "" {
		o.NIF = &nif
	}
	return o
}

// AdjudicacionMercado es Adjudicacion del contrato tal como la sirve /awards: con el comprador, el mercado (CPV, zona, procedimiento) y la evidencia.
type AdjudicacionMercado struct {
	Adjudicacion
	Comprador     *OrganizacionRef `json:"comprador,omitempty"`
	Procedimiento string           `json:"procedimiento,omitempty"`
	CPV           []string         `json:"cpv"`
	NUTS          []string         `json:"nuts"`
	Evidencia     Evidencia        `json:"evidencia"`
}

func decimal(v *string) *float64 {
	if v == nil {
		return nil
	}
	f, err := strconv.ParseFloat(*v, 64)
	if err != nil {
		return nil
	}
	return &f
}

func importeBD(v *string, moneda, impuestos, significado string) *Importe {
	if v == nil {
		return nil
	}
	return &Importe{Valor: trimDecimal(*v), Moneda: moneda, Impuestos: impuestos, Significado: significado}
}

func adjudicacionMercado(a pg.Adjudicacion) AdjudicacionMercado {
	out := AdjudicacionMercado{
		Adjudicacion: Adjudicacion{
			ID: a.ID, LicitacionID: a.ExpedienteID, Expediente: a.Expediente, Titulo: a.Titulo, Lote: a.Lote, Resultado: a.Resultado,
			Importes: importes(importeBD(a.ImporteSinIVA, a.Moneda, "sin_iva", "adjudicado"), importeBD(a.ImporteConIVA, a.Moneda, "con_iva", "adjudicado"),
				importeBD(a.Presupuesto, a.Moneda, "sin_iva", "presupuesto_base"), importeBD(a.OfertaMasBaja, a.Moneda, "desconocido", "oferta_mas_baja"),
				importeBD(a.OfertaMasAlta, a.Moneda, "desconocido", "oferta_mas_alta")),
			Baja: decimal(a.Baja), OfertasRecibidas: a.Ofertas, BajaAnormal: a.BajaAnormal,
			FechaAdjudicacion: a.FechaAdjudicacion, FechaFormalizacion: a.FechaFormalizacion,
		},
		Comprador: orgRef(a.CompradorNombre, a.CompradorNIF, a.CompradorDIR3), Procedimiento: a.Procedimiento, CPV: nonNil(a.CPV), NUTS: nonNil(a.NUTS),
		Evidencia: Evidencia{Fuente: fuenteExterna(a.Fuente), IDOrigen: a.IDOrigen, URLOrigen: a.Enlace, CapturadoEn: a.Capturado.UTC(),
			SHA256: a.SHA256, ClaveRaw: a.ClaveRaw, VersionParser: ingest.ParserVersion},
	}
	if a.AdjudicatarioID != nil {
		o := &OrganizacionRef{ID: *a.AdjudicatarioID, Nombre: a.AdjudicatarioNombre}
		if a.AdjudicatarioNIF != "" {
			o.NIF = &a.AdjudicatarioNIF
		}
		out.Adjudicatario = o
	}
	return out
}

func (s *Server) adjudicaciones(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	f, p := parseAdjudicaciones(q)
	if p != nil {
		writeProblem(w, r, p)
		return
	}
	huella := huellaFiltros(q)
	if c, ok := one(q, "cursor"); ok {
		cd, err := decodeCursor(s.cursor, c, huella, s.Now())
		if err != nil || !reOrgUUID.MatchString(cd.I) {
			writeProblem(w, r, newProblem(http.StatusBadRequest, codCursor, "Cursor no válido", "El cursor no es válido, ha caducado o no corresponde a esta consulta."))
			return
		}
		f.Despues = &pg.Posicion{Clave: cd.K, ID: cd.I}
	}
	filas, total, exacto, err := s.Repo.BuscarAdjudicaciones(r.Context(), f)
	if err != nil {
		s.internal(w, r, err)
		return
	}
	var siguiente *string
	if len(filas) > f.Limit {
		filas = filas[:f.Limit]
		last := filas[len(filas)-1]
		c := encodeCursor(s.cursor, cursorData{K: last.ClaveOrden, I: last.ID, F: huella, E: s.Now().Add(cursorTTL).Unix()})
		siguiente = &c
	}
	items := make([]AdjudicacionMercado, len(filas))
	for i, a := range filas {
		items[i] = adjudicacionMercado(a)
	}
	rel := "eq"
	if !exacto {
		rel = "gte"
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"items": items, "siguiente_cursor": siguiente, "total": map[string]any{"valor": total, "relacion": rel},
	})
}

// Competidor es Competidor del contrato.
type Competidor struct {
	Organizacion       OrganizacionRef `json:"organizacion"`
	ContratosGanados   int             `json:"contratos_ganados"`
	ImporteAdjudicado  Importe         `json:"importe_adjudicado"`
	Cuota              float64         `json:"cuota"`
	BajaMedia          *float64        `json:"baja_media"`
	BajaP50            *float64        `json:"baja_p50"`
	Tendencia          string          `json:"tendencia"`
	UltimaAdjudicacion *string         `json:"ultima_adjudicacion"`
}

func (s *Server) competidores(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	f, p := parseCompetidores(q)
	if p != nil {
		writeProblem(w, r, p)
		return
	}
	huella := huellaFiltros(q)
	if c, ok := one(q, "cursor"); ok {
		cd, err := decodeCursor(s.cursor, c, huella, s.Now())
		if err != nil {
			writeProblem(w, r, newProblem(http.StatusBadRequest, codCursor, "Cursor no válido", "El cursor no es válido, ha caducado o no corresponde a esta consulta."))
			return
		}
		f.Despues = &pg.Posicion{Clave: cd.K, ID: cd.I}
	}
	filas, total, muestra, err := s.Repo.Competidores(r.Context(), f)
	if err != nil {
		s.internal(w, r, err)
		return
	}
	var siguiente *string
	if len(filas) > f.Limit {
		filas = filas[:f.Limit]
		last := filas[len(filas)-1]
		c := encodeCursor(s.cursor, cursorData{K: last.ClaveOrden, I: last.Clave, F: huella, E: s.Now().Add(cursorTTL).Unix()})
		siguiente = &c
	}
	items := make([]Competidor, len(filas))
	for i, x := range filas {
		o := OrganizacionRef{ID: x.ID, Nombre: x.Nombre}
		if x.NIF != "" {
			nif := x.NIF
			o.NIF = &nif
		}
		items[i] = Competidor{Organizacion: o, ContratosGanados: x.Contratos, Cuota: redondear(x.Cuota), BajaMedia: redondearPtr(x.BajaMedia),
			BajaP50: redondearPtr(x.BajaP50), Tendencia: x.Tendencia, UltimaAdjudicacion: x.Ultima,
			ImporteAdjudicado: Importe{Valor: trimDecimal(x.Importe), Moneda: "EUR", Impuestos: "sin_iva", Significado: "adjudicado"}}
	}
	rel := "eq"
	if total >= pg.MaxTotal {
		rel = "gte"
	}
	m := map[string]any{"adjudicaciones": muestra.Adjudicaciones}
	if muestra.Desde != nil {
		m["desde"] = *muestra.Desde
	}
	if muestra.Hasta != nil {
		m["hasta"] = *muestra.Hasta
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"items": items, "siguiente_cursor": siguiente, "total": map[string]any{"valor": total, "relacion": rel}, "muestra": m,
	})
}

func redondear(v float64) float64 {
	f, _ := strconv.ParseFloat(fmt.Sprintf("%.6f", v), 64)
	return f
}

func redondearPtr(v *float64) *float64 {
	if v == nil {
		return nil
	}
	r := redondear(*v)
	return &r
}
