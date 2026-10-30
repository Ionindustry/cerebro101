package api

import (
	"net/http"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

// Grupo es un elemento de un reparto del dashboard de la búsqueda.
type Grupo struct {
	Valor   string `json:"valor"`
	NIF     string `json:"nif,omitempty"`
	Cuenta  int    `json:"cuenta"`
	Importe string `json:"importe,omitempty"`
}

// decimalOVacio formatea un importe decimal; vacío (no hay) sigue vacío.
func decimalOVacio(v string) string {
	if v == "" {
		return ""
	}
	return trimDecimal(v)
}

func grupos(cs []pg.Cuenta) []Grupo {
	out := make([]Grupo, len(cs))
	for i, c := range cs {
		out[i] = Grupo{Valor: c.Valor, NIF: c.NIF, Cuenta: c.Cuenta, Importe: decimalOVacio(c.Importe)}
	}
	return out
}

// estadisticas responde con los agregados de todo lo que cumple los filtros de /tenders (mismos parámetros; el orden, el cursor y el límite no cuentan).
// El importe es siempre el valor estimado sin IVA, en euros.
func (s *Server) estadisticas(w http.ResponseWriter, r *http.Request) {
	f, p := parseBusqueda(r.URL.Query())
	if p != nil {
		writeProblem(w, r, p)
		return
	}
	e, err := s.Repo.Estadisticas(r.Context(), f)
	if err != nil {
		s.internal(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"total": e.Total, "abiertas": e.Abiertas, "vencen_7_dias": e.VencenSemana,
		"importe": map[string]any{
			"total": decimalOVacio(e.ImporteTotal), "medio": decimalOVacio(e.ImporteMedio), "con_importe": e.ConImporte,
			"moneda": "EUR", "impuestos": "sin_iva", "significado": "valor_estimado",
		},
		"estados": grupos(e.Estados), "zonas": grupos(e.Zonas), "cpv": grupos(e.CPV), "importes": grupos(e.Importes),
		"compradores": grupos(e.Compradores), "plazos": grupos(e.Plazos),
	})
}
