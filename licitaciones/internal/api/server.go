// Package api sirve el contrato HTTP del motor (api/openapi.yaml): búsqueda y ficha de licitaciones, adjudicaciones, competidores y estado del motor. Esta primera versión
// lee del modelo de lectura de Postgres (ADR 0009) y se autentica con un token compartido; la validación de tokens de Keycloak (SEC-031)
// sustituirá a ese token cuando la API la usen el panel y los agentes. Solo para la red interna: no se publica fuera.
package api

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"log/slog"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

// Repo es lo que la API necesita de la base; lo satisface *pg.Store.
type Repo interface {
	Buscar(ctx context.Context, f pg.Filtro) ([]pg.Fila, int, bool, error)
	Expediente(ctx context.Context, id string) (pg.Fila, error)
	BuscarAdjudicaciones(ctx context.Context, f pg.FiltroAdjudicaciones) ([]pg.Adjudicacion, int, bool, error)
	Competidores(ctx context.Context, f pg.FiltroCompetidores) ([]pg.Competidor, int, pg.MuestraMercado, error)
	ContratosQueVencen(ctx context.Context, f pg.FiltroVencimientos) ([]pg.ContratoVence, int, bool, error)
	Organizacion(ctx context.Context, f pg.FiltroOrganizacion) (*pg.FichaOrganizacion, error)
	Fuentes(ctx context.Context) ([]pg.EstadoFuente, error)
	Ping(ctx context.Context) (time.Duration, error)
}

// Server es la API.
type Server struct {
	Repo  Repo
	Token string // token compartido que debe llegar en «Authorization: Bearer …»
	Log   *slog.Logger
	Now   func() time.Time
	// Embedder vectoriza el texto de la búsqueda por significado; nil = solo búsqueda de texto.
	Embedder Embedder
	cursor   []byte
}

// MinTokenLen es la longitud mínima del token: uno corto se adivina.
const MinTokenLen = 32

// New crea la API. El token se rechaza si es corto.
func New(repo Repo, token string, log *slog.Logger) (*Server, error) {
	if len(token) < MinTokenLen {
		return nil, errors.New("el token de la API es demasiado corto (mínimo 32 caracteres)")
	}
	if log == nil {
		log = slog.New(slog.DiscardHandler)
	}
	// La clave de firma de los cursores se deriva del token, pero no es el token: filtrar un cursor no revela la credencial.
	k := sha256.Sum256([]byte("cursor|" + token))
	return &Server{Repo: repo, Token: token, Log: log, Now: time.Now, cursor: k[:]}, nil
}

// Register añade las rutas a mux. /healthz lo sirve el arranque común, sin autenticación.
func (s *Server) Register(mux *http.ServeMux) {
	mux.Handle("GET /api/v1/tenders", s.wrap(s.buscar))
	mux.Handle("GET /api/v1/tenders/{id}", s.wrap(s.ficha))
	mux.Handle("GET /api/v1/tenders/{id}/parecidas", s.wrap(s.parecidas))
	mux.Handle("GET /api/v1/awards", s.wrap(s.adjudicaciones))
	mux.Handle("GET /api/v1/competitors", s.wrap(s.competidores))
	mux.Handle("GET /api/v1/expiring-contracts", s.wrap(s.contratosQueVencen))
	mux.Handle("GET /api/v1/organizations/{id}", s.wrap(s.organizacion))
	mux.Handle("GET /api/v1/ops/status", s.wrap(s.estado))
	mux.Handle("/api/", s.wrap(func(w http.ResponseWriter, r *http.Request) {
		writeProblem(w, r, newProblem(http.StatusNotFound, codNoEncontrado, "No encontrado", "La ruta no existe."))
	}))
}

// wrap añade a cada ruta el identificador de petición, las cabeceras de seguridad y la autenticación.
func (s *Server) wrap(h http.HandlerFunc) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := requestID()
		r.Header.Set("X-Request-Id", id)
		w.Header().Set("X-Request-Id", id)
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Cache-Control", "no-store")
		if !s.authorized(r) {
			w.Header().Set("WWW-Authenticate", `Bearer realm="licitaciones"`)
			writeProblem(w, r, newProblem(http.StatusUnauthorized, codNoAuth, "No autenticado", "Falta el token o no es válido."))
			return
		}
		h(w, r)
	})
}

func (s *Server) authorized(r *http.Request) bool {
	tok, ok := strings.CutPrefix(r.Header.Get("Authorization"), "Bearer ")
	if !ok || tok == "" {
		return false
	}
	// Se comparan los resúmenes para que el tiempo no dependa de dónde difieren ni de la longitud.
	a, b := sha256.Sum256([]byte(tok)), sha256.Sum256([]byte(s.Token))
	return subtle.ConstantTimeCompare(a[:], b[:]) == 1
}

func requestID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

var reUUID = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

// internal registra el error real y responde sin detalles internos.
func (s *Server) internal(w http.ResponseWriter, r *http.Request, err error) {
	s.Log.Error("error interno de la API", "ruta", r.URL.Path, "peticion", r.Header.Get("X-Request-Id"), "error", err)
	writeProblem(w, r, newProblem(http.StatusInternalServerError, codInterno, "Error interno", "No se ha podido atender la petición."))
}

func (s *Server) buscar(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	f, p := parseBusqueda(q)
	if p != nil {
		writeProblem(w, r, p)
		return
	}
	modo, p := parseModo(q, f)
	if p != nil {
		writeProblem(w, r, p)
		return
	}
	if modo != modoTexto {
		s.buscarPorSignificado(w, r, f, modo)
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
	filas, total, exacto, err := s.Repo.Buscar(r.Context(), f)
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
	items := make([]Resumen, len(filas))
	for i, fl := range filas {
		items[i] = resumen(fl)
	}
	rel := "eq"
	if !exacto {
		rel = "gte"
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"items": items, "siguiente_cursor": siguiente, "total": map[string]any{"valor": total, "relacion": rel}, "modo": modoTexto,
	})
}

func (s *Server) ficha(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if !reUUID.MatchString(id) {
		writeProblem(w, r, newProblem(http.StatusNotFound, codNoEncontrado, "No encontrado", "El expediente no existe."))
		return
	}
	f, err := s.Repo.Expediente(r.Context(), id)
	switch {
	case errors.Is(err, pg.ErrNoEncontrado):
		writeProblem(w, r, newProblem(http.StatusNotFound, codNoEncontrado, "No encontrado", "El expediente no existe."))
		return
	case err != nil:
		s.internal(w, r, err)
		return
	}
	etag := `"` + f.ID + "-v" + strconv.Itoa(f.Version) + `"`
	w.Header().Set("ETag", etag)
	if r.Header.Get("If-None-Match") == etag {
		w.WriteHeader(http.StatusNotModified)
		return
	}
	out, err := ficha(f)
	if err != nil {
		s.internal(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}
