package api

import (
	"context"
	"net/http"
	"time"
)

// minHuecoPeticiones: como mucho una petición de «actualiza ya» por minuto, pase lo que pase.
const minHuecoPeticiones = time.Minute

// SolicitadorIngesta lo implementa el almacén (*pg.Store): anota la petición para que el ingestor empiece su vuelta sin esperar al intervalo. Es opcional en el Repo: sin él, 501.
type SolicitadorIngesta interface {
	SolicitarIngesta(ctx context.Context, por string, minHueco time.Duration) (bool, error)
}

// actualizar atiende POST /api/v1/ops/actualizar: pide al ingestor una vuelta inmediata. Responde 202 con {"solicitada": true} si ha anotado una petición nueva, o
// {"solicitada": false} si ya había una de hace menos de un minuto (el ingestor la está atendiendo). No ingiere nada aquí: la API no tiene salida a la fuente.
func (s *Server) actualizar(w http.ResponseWriter, r *http.Request) {
	sol, ok := s.Repo.(SolicitadorIngesta)
	if !ok {
		writeProblem(w, r, newProblem(http.StatusNotImplemented, "no_implementado", "No disponible", "Este almacén no admite pedir una actualización."))
		return
	}
	por := r.Header.Get("X-Pedido-Por") // quién lo pide (lo pone el Cerebro: el usuario del panel); solo para el rastro
	nueva, err := sol.SolicitarIngesta(r.Context(), por, minHuecoPeticiones)
	if err != nil {
		s.internal(w, r, err)
		return
	}
	s.Log.Info("petición de actualización", "nueva", nueva, "por", por)
	writeJSON(w, http.StatusAccepted, map[string]any{"solicitada": nueva})
}
