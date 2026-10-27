package api

import (
	"encoding/json"
	"net/http"
)

// Códigos de error del contrato (Problema.codigo).
const (
	codParametro    = "parametro_invalido"
	codCursor       = "cursor_invalido"
	codNoAuth       = "no_autenticado"
	codNoEncontrado = "no_encontrado"
	codNoDisponible = "no_disponible"
	codInterno      = "error_interno"
)

// problem es un error RFC 9457 (application/problem+json). Detail es apto para mostrar y nunca lleva secretos ni trazas internas.
type problem struct {
	Type     string       `json:"type"`
	Title    string       `json:"title"`
	Status   int          `json:"status"`
	Detail   string       `json:"detail,omitempty"`
	Instance string       `json:"instance,omitempty"`
	Codigo   string       `json:"codigo"`
	Errores  []campoError `json:"errores,omitempty"`
}

type campoError struct {
	Campo   string `json:"campo"`
	Mensaje string `json:"mensaje"`
}

func newProblem(status int, codigo, title, detail string, errs ...campoError) *problem {
	return &problem{Type: "https://licitaciones.101.cat/errores/" + codigo, Title: title, Status: status, Detail: detail, Codigo: codigo, Errores: errs}
}

func invalid(campo, msg string) *problem {
	return newProblem(http.StatusBadRequest, codParametro, "Parámetro no válido", "Algún parámetro de la petición no es válido.", campoError{campo, msg})
}

func writeProblem(w http.ResponseWriter, r *http.Request, p *problem) {
	p.Instance = r.Header.Get("X-Request-Id")
	w.Header().Set("Content-Type", "application/problem+json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(p.Status)
	_ = json.NewEncoder(w).Encode(p)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
