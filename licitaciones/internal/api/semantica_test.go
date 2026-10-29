package api

import (
	"context"
	"errors"
	"testing"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

type repoSemantico struct {
	fakeRepo
	cercanas     []pg.Fila
	parecidas    []pg.Parecida
	errParecidas error
	vistoVector  []float32
}

func (r *repoSemantico) BuscarPorSignificado(_ context.Context, fl pg.Filtro, v []float32, n int) ([]pg.Fila, error) {
	r.visto, r.vistoVector = fl, v
	if n < len(r.cercanas) {
		return r.cercanas[:n], nil
	}
	return r.cercanas, nil
}
func (r *repoSemantico) Parecidas(context.Context, string, int) ([]pg.Parecida, error) {
	return r.parecidas, r.errParecidas
}

type embedderFalso struct{ err error }

func (e embedderFalso) Uno(context.Context, string) ([]float32, error) {
	return []float32{1, 2, 3}, e.err
}

const uuidA = "11111111-1111-8111-8111-111111111111"

func fila(id, titulo, clave string) pg.Fila {
	return pg.Fila{ID: id, Titulo: titulo, ClaveOrden: clave, Fuente: "placsp-643"}
}

func TestModoSignificadoOrdenaPorCercaniaYDaLaCercania(t *testing.T) {
	repo := &repoSemantico{cercanas: []pg.Fila{fila(uuidA, "Mantenimiento de software", "0.2"), fila("22222222-2222-8222-8222-222222222222", "Soporte", "0.5")}}
	s, ts := servidor(t, repo)
	s.Embedder = embedderFalso{}
	res := get(t, ts, "/api/v1/tenders?q=informática&modo=significado&cpv=72", token)
	var out struct {
		Items []Resumen `json:"items"`
		Modo  string    `json:"modo"`
	}
	decode(t, res, &out)
	if res.StatusCode != 200 || out.Modo != "significado" || len(out.Items) != 2 {
		t.Fatalf("%d %s", res.StatusCode, res.Body)
	}
	if out.Items[0].Cercania == nil || *out.Items[0].Cercania != 0.8 || *out.Items[1].Cercania != 0.5 {
		t.Fatalf("cercanías: %v %v", out.Items[0].Cercania, out.Items[1].Cercania)
	}
	if len(repo.visto.CPV) != 1 || len(repo.vistoVector) != 3 {
		t.Fatalf("el filtro debe llegar al almacén: %+v", repo.visto)
	}
}

func TestModoSignificadoNoDisponible(t *testing.T) {
	// Sin Embedder (API sin Ollama) → 503; con Embedder caído también.
	repo := &repoSemantico{}
	s, ts := servidor(t, repo)
	if res := get(t, ts, "/api/v1/tenders?q=obras&modo=significado", token); res.StatusCode != 503 {
		t.Fatalf("sin embedder: %d %s", res.StatusCode, res.Body)
	}
	s.Embedder = embedderFalso{err: errors.New("caído")}
	if res := get(t, ts, "/api/v1/tenders?q=obras&modo=significado", token); res.StatusCode != 503 {
		t.Fatalf("embedder caído: %d %s", res.StatusCode, res.Body)
	}
	// Un repo sin la parte semántica (el fake simple) también da 503.
	_, ts2 := servidor(t, &fakeRepo{})
	if res := get(t, ts2, "/api/v1/tenders?q=obras&modo=significado", token); res.StatusCode != 503 {
		t.Fatalf("repo sin semántica: %d", res.StatusCode)
	}
}

func TestModoHibridoSeDegradaATextoAvisando(t *testing.T) {
	repo := &repoSemantico{}
	repo.filas = []pg.Fila{fila(uuidA, "Obras", "0.9")}
	s, ts := servidor(t, repo)
	s.Embedder = embedderFalso{err: errors.New("caído")}
	res := get(t, ts, "/api/v1/tenders?q=obras&modo=hibrido", token)
	var out struct {
		Items []Resumen `json:"items"`
		Modo  string    `json:"modo"`
		Aviso string    `json:"aviso"`
	}
	decode(t, res, &out)
	if res.StatusCode != 200 || out.Modo != "texto" || out.Aviso == "" || len(out.Items) != 1 {
		t.Fatalf("%d %s", res.StatusCode, res.Body)
	}
}

func TestModoHibridoMezclaTextoYSignificado(t *testing.T) {
	b, c := "22222222-2222-8222-8222-222222222222", "33333333-3333-8333-8333-333333333333"
	repo := &repoSemantico{cercanas: []pg.Fila{fila(b, "B", "0.1"), fila(uuidA, "A", "0.2"), fila(c, "C", "0.3")}}
	repo.filas = []pg.Fila{fila(uuidA, "A", "1"), fila(c, "C", "1")}
	s, ts := servidor(t, repo)
	s.Embedder = embedderFalso{}
	res := get(t, ts, "/api/v1/tenders?q=x%20y&modo=hibrido&limit=3", token)
	var out struct {
		Items []Resumen `json:"items"`
		Modo  string    `json:"modo"`
	}
	decode(t, res, &out)
	if res.StatusCode != 200 || out.Modo != "hibrido" || len(out.Items) != 3 {
		t.Fatalf("%d %s", res.StatusCode, res.Body)
	}
	// A sale en las dos listas (1.º en texto, 2.º en significado) y gana a B (solo 1.º en significado).
	if out.Items[0].ID != uuidA {
		t.Fatalf("el que sale en las dos listas debía ir primero: %s %s %s", out.Items[0].ID, out.Items[1].ID, out.Items[2].ID)
	}
}

func TestModoValidaLosParametros(t *testing.T) {
	_, ts := servidor(t, &repoSemantico{})
	for _, ruta := range []string{
		"/api/v1/tenders?modo=significado",                     // sin q
		"/api/v1/tenders?q=obras&modo=raro",                    // modo desconocido
		"/api/v1/tenders?q=obras&modo=significado&orden=plazo", // otro orden
		"/api/v1/tenders?q=obras&modo=significado&cursor=abc",  // sin paginación
	} {
		if res := get(t, ts, ruta, token); res.StatusCode != 400 {
			t.Errorf("%s: %d %s", ruta, res.StatusCode, res.Body)
		}
	}
	// modo=texto es el de siempre.
	if res := get(t, ts, "/api/v1/tenders?q=obras&modo=texto", token); res.StatusCode != 200 {
		t.Errorf("modo=texto: %d", res.StatusCode)
	}
}

func TestParecidas(t *testing.T) {
	repo := &repoSemantico{parecidas: []pg.Parecida{{Fila: fila("22222222-2222-8222-8222-222222222222", "Otro", ""), Distancia: 0.1, MismoComprador: true, CPVEnComun: true}}}
	_, ts := servidor(t, repo)
	res := get(t, ts, "/api/v1/tenders/"+uuidA+"/parecidas?limit=5", token)
	var out struct {
		Items []Resumen `json:"items"`
	}
	decode(t, res, &out)
	if res.StatusCode != 200 || len(out.Items) != 1 || *out.Items[0].Cercania != 0.9 || len(out.Items[0].Motivos) != 2 {
		t.Fatalf("%d %s", res.StatusCode, res.Body)
	}
	for ruta, esperado := range map[string]int{
		"/api/v1/tenders/nada/parecidas":                  404,
		"/api/v1/tenders/" + uuidA + "/parecidas?limit=0": 400,
		"/api/v1/tenders/" + uuidA + "/parecidas?otro=1":  400,
	} {
		if r := get(t, ts, ruta, token); r.StatusCode != esperado {
			t.Errorf("%s: %d", ruta, r.StatusCode)
		}
	}
	repo.errParecidas = pg.ErrSinVector
	if r := get(t, ts, "/api/v1/tenders/"+uuidA+"/parecidas", token); r.StatusCode != 503 {
		t.Errorf("sin vector: %d", r.StatusCode)
	}
	repo.errParecidas = pg.ErrNoEncontrado
	if r := get(t, ts, "/api/v1/tenders/"+uuidA+"/parecidas", token); r.StatusCode != 404 {
		t.Errorf("no existe: %d", r.StatusCode)
	}
	if r := get(t, ts, "/api/v1/tenders/"+uuidA+"/parecidas", ""); r.StatusCode != 401 {
		t.Errorf("sin token: %d", r.StatusCode)
	}
}
