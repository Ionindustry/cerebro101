package api

import (
	"context"
	"net/http"
	"strings"
	"testing"
	"time"
)

type repoConPeticiones struct {
	fakeRepo
	nueva bool
	por   string
	hueco time.Duration
	err   error
}

func (r *repoConPeticiones) SolicitarIngesta(_ context.Context, por string, hueco time.Duration) (bool, error) {
	r.por, r.hueco = por, hueco
	return r.nueva, r.err
}

func TestActualizarAnotaLaPeticionYDiceSiEraNueva(t *testing.T) {
	repo := &repoConPeticiones{nueva: true}
	_, ts := servidor(t, repo)
	for _, nueva := range []bool{true, false} {
		repo.nueva = nueva
		req, _ := http.NewRequestWithContext(context.Background(), http.MethodPost, ts.URL+"/api/v1/ops/actualizar", strings.NewReader(""))
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("X-Pedido-Por", "albert")
		res, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		_ = res.Body.Close()
		if res.StatusCode != http.StatusAccepted {
			t.Fatalf("estado %d", res.StatusCode)
		}
		if repo.por != "albert" || repo.hueco != time.Minute {
			t.Fatalf("la petición no llegó al almacén como debía: %+v", repo)
		}
	}
}

func TestActualizarExigeTokenYAlmacenQueLoAdmita(t *testing.T) {
	_, ts := servidor(t, &repoConPeticiones{})
	req, _ := http.NewRequestWithContext(context.Background(), http.MethodPost, ts.URL+"/api/v1/ops/actualizar", nil)
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	_ = res.Body.Close()
	if res.StatusCode != http.StatusUnauthorized {
		t.Fatalf("sin token debe ser 401, es %d", res.StatusCode)
	}
	_, ts2 := servidor(t, &fakeRepo{}) // un almacén sin la capacidad
	req, _ = http.NewRequestWithContext(context.Background(), http.MethodPost, ts2.URL+"/api/v1/ops/actualizar", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	res, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	_ = res.Body.Close()
	if res.StatusCode != http.StatusNotImplemented {
		t.Fatalf("sin capacidad debe ser 501, es %d", res.StatusCode)
	}
}
