package api

import (
	"context"
	"errors"
	"net/http"
	"net/url"
	"sort"
	"strconv"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

// Búsqueda por significado («modo=significado» y «modo=hibrido») y licitaciones parecidas. Es opcional: si la base no tiene pgvector o la API no llega a
// Ollama, la búsqueda de texto sigue igual y estas variantes responden 503 (o, en el modo híbrido, se degradan a texto avisándolo).

// Embedder convierte un texto en vector; lo cumple *embed.Cliente.
type Embedder interface {
	Uno(ctx context.Context, texto string) ([]float32, error)
}

// Semantico es lo que la API necesita de la base para buscar por significado; lo cumple *pg.Store. Va aparte de Repo para que sea opcional.
type Semantico interface {
	BuscarPorSignificado(ctx context.Context, f pg.Filtro, vector []float32, limite int) ([]pg.Fila, error)
	Parecidas(ctx context.Context, id string, limite int) ([]pg.Parecida, error)
}

const (
	modoTexto       = "texto"
	modoSignificado = "significado"
	modoHibrido     = "hibrido"

	candidatosHibrido = 50 // de cada lista que se mezcla
	kRRF              = 60 // constante de la fusión por rangos recíprocos (valor habitual)
)

// parseModo lee «modo» y comprueba que es compatible con el resto de parámetros.
func parseModo(q url.Values, f pg.Filtro) (string, *problem) {
	v, ok := one(q, "modo")
	if !ok || v == modoTexto {
		return modoTexto, nil
	}
	if v != modoSignificado && v != modoHibrido {
		return "", invalid("modo", "usa texto, significado o hibrido")
	}
	if f.Q == "" {
		return "", invalid("modo", "la búsqueda por significado necesita el parámetro q")
	}
	if _, ok := one(q, "cursor"); ok {
		return "", invalid("cursor", "la búsqueda por significado no se pagina: afina q o los filtros")
	}
	if o, ok := one(q, "orden"); ok && o != pg.OrdenRelevancia {
		return "", invalid("orden", "con búsqueda por significado el orden es por cercanía (relevancia)")
	}
	return v, nil
}

func (s *Server) semantico() (Semantico, bool) {
	sem, ok := s.Repo.(Semantico)
	return sem, ok && s.Embedder != nil
}

func noDisponible(w http.ResponseWriter, r *http.Request, detalle string) {
	writeProblem(w, r, newProblem(http.StatusServiceUnavailable, codNoDisponible, "No disponible", detalle))
}

func (s *Server) buscarPorSignificado(w http.ResponseWriter, r *http.Request, f pg.Filtro, modo string) {
	porTexto := func(aviso string) {
		g := f
		g.Orden, g.Despues = pg.OrdenRelevancia, nil
		filas, total, exacto, err := s.Repo.Buscar(r.Context(), g)
		if err != nil {
			s.internal(w, r, err)
			return
		}
		if len(filas) > g.Limit {
			filas = filas[:g.Limit]
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
			"items": items, "siguiente_cursor": nil, "total": map[string]any{"valor": total, "relacion": rel}, "modo": modoTexto, "aviso": aviso,
		})
	}
	sem, ok := s.semantico()
	if !ok {
		if modo == modoHibrido {
			porTexto("La búsqueda por significado no está activada; se ha buscado solo por texto.")
			return
		}
		noDisponible(w, r, "La búsqueda por significado no está activada en este motor.")
		return
	}
	vector, err := s.Embedder.Uno(r.Context(), f.Q)
	if err != nil {
		s.Log.Warn("búsqueda por significado: no se pudo vectorizar la consulta", "error", err)
		if modo == modoHibrido {
			porTexto("No se pudo calcular el significado de la búsqueda; se ha buscado solo por texto.")
			return
		}
		noDisponible(w, r, "No se pudo calcular el significado de la búsqueda (el modelo de lenguaje no responde). Prueba la búsqueda por texto.")
		return
	}
	n := f.Limit
	if modo == modoHibrido {
		n = candidatosHibrido
	}
	cercanas, err := sem.BuscarPorSignificado(r.Context(), f, vector, n)
	if errors.Is(err, pg.ErrSinVectores) {
		noDisponible(w, r, "La base de datos no tiene activada la búsqueda por significado (falta pgvector).")
		return
	}
	if err != nil {
		s.internal(w, r, err)
		return
	}
	var filas []pg.Fila
	if modo == modoSignificado {
		filas = cercanas
	} else {
		g := f
		g.Orden, g.Limit, g.Despues = pg.OrdenRelevancia, candidatosHibrido, nil
		deTexto, _, _, err := s.Repo.Buscar(r.Context(), g)
		if err != nil {
			s.internal(w, r, err)
			return
		}
		if len(deTexto) > candidatosHibrido {
			deTexto = deTexto[:candidatosHibrido]
		}
		filas = fusionar(deTexto, cercanas, f.Limit)
	}
	if len(filas) > f.Limit {
		filas = filas[:f.Limit]
	}
	items := make([]Resumen, len(filas))
	for i, fl := range filas {
		items[i] = resumen(fl)
		if modo == modoSignificado {
			items[i].Cercania = cercaniaDe(fl.ClaveOrden)
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"items": items, "siguiente_cursor": nil, "total": map[string]any{"valor": len(items), "relacion": "gte"}, "modo": modo,
	})
}

// cercaniaDe convierte la distancia coseno (texto) en cercanía de 0 a 1.
func cercaniaDe(distancia string) *float64 {
	d, err := parseFloat(distancia)
	if err != nil {
		return nil
	}
	c := 1 - d
	if c < 0 {
		c = 0
	}
	if c > 1 {
		c = 1
	}
	c = float64(int(c*1000+0.5)) / 1000
	return &c
}

// fusionar mezcla dos listas ya ordenadas con rangos recíprocos (RRF): un expediente que sale en las dos, o bien colocado en una, sube. Desempata por id.
func fusionar(a, b []pg.Fila, n int) []pg.Fila {
	punt := map[string]float64{}
	fila := map[string]pg.Fila{}
	for _, lista := range [][]pg.Fila{a, b} {
		for i, f := range lista {
			punt[f.ID] += 1.0 / float64(kRRF+i+1)
			if _, ok := fila[f.ID]; !ok {
				fila[f.ID] = f
			}
		}
	}
	ids := make([]string, 0, len(punt))
	for id := range punt {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool {
		if punt[ids[i]] != punt[ids[j]] {
			return punt[ids[i]] > punt[ids[j]]
		}
		return ids[i] < ids[j]
	})
	if len(ids) > n {
		ids = ids[:n]
	}
	out := make([]pg.Fila, len(ids))
	for i, id := range ids {
		out[i] = fila[id]
	}
	return out
}

// parecidas: GET /tenders/{id}/parecidas?limit=N — los expedientes más cercanos en significado, con el porqué (mismo comprador, CPV en común).
func (s *Server) parecidas(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if !reUUID.MatchString(id) {
		writeProblem(w, r, newProblem(http.StatusNotFound, codNoEncontrado, "No encontrado", "El expediente no existe."))
		return
	}
	q := r.URL.Query()
	for k := range q {
		if k != "limit" {
			writeProblem(w, r, invalid(k, "parámetro desconocido"))
			return
		}
	}
	limite := 10
	if v, ok := one(q, "limit"); ok {
		n, err := atoi(v)
		if err != nil || n < 1 || n > 50 {
			writeProblem(w, r, invalid("limit", "entre 1 y 50"))
			return
		}
		limite = n
	}
	sem, ok := s.Repo.(Semantico)
	if !ok {
		noDisponible(w, r, "La búsqueda por cercanía no está activada en este motor.")
		return
	}
	filas, err := sem.Parecidas(r.Context(), id, limite)
	switch {
	case errors.Is(err, pg.ErrNoEncontrado):
		writeProblem(w, r, newProblem(http.StatusNotFound, codNoEncontrado, "No encontrado", "El expediente no existe."))
		return
	case errors.Is(err, pg.ErrSinVector):
		noDisponible(w, r, "Este expediente todavía no se ha analizado para buscar parecidos; vuelve a intentarlo en unos minutos.")
		return
	case err != nil:
		s.internal(w, r, err)
		return
	}
	items := make([]Resumen, len(filas))
	for i, p := range filas {
		it := resumen(p.Fila)
		c := 1 - p.Distancia
		if c < 0 {
			c = 0
		}
		c = float64(int(c*1000+0.5)) / 1000
		it.Cercania = &c
		it.Motivos = []string{}
		if p.MismoComprador {
			it.Motivos = append(it.Motivos, "mismo_comprador")
		}
		if p.CPVEnComun {
			it.Motivos = append(it.Motivos, "cpv_comun")
		}
		items[i] = it
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items})
}

func parseFloat(s string) (float64, error) { return strconv.ParseFloat(s, 64) }
func atoi(s string) (int, error)           { return strconv.Atoi(s) }
