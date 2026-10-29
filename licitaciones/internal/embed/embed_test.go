package embed

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func vectorDe(n int) []float32 { return make([]float32, n) }

func TestNuevoValidaLaDireccion(t *testing.T) {
	if c, err := Nuevo(""); c != nil || err != nil {
		t.Fatalf("vacío debe ser sin cliente y sin error: %v %v", c, err)
	}
	for _, malo := range []string{"ftp://x", "http://u:p@x:1", "x:11434", "http://"} {
		if _, err := Nuevo(malo); err == nil {
			t.Errorf("%q debería rechazarse", malo)
		}
	}
	if c, err := Nuevo("http://ollama:11434/"); err != nil || c.Base != "http://ollama:11434" {
		t.Fatalf("válida: %v %v", c, err)
	}
}

func TestVectores(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			Model string   `json:"model"`
			Input []string `json:"input"`
		}
		_ = json.NewDecoder(r.Body).Decode(&in)
		if r.URL.Path != "/api/embed" || in.Model != Modelo {
			http.Error(w, "no", 400)
			return
		}
		out := make([][]float32, len(in.Input))
		for i := range out {
			out[i] = vectorDe(Dimensiones)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"embeddings": out})
	}))
	defer srv.Close()
	c, _ := Nuevo(srv.URL)
	v, err := c.Vectores(context.Background(), []string{"a", "b"})
	if err != nil || len(v) != 2 {
		t.Fatalf("vectores: %v %v", v, err)
	}
}

func TestVectoresRechazaDimensionesDistintas(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"embeddings": [][]float32{vectorDe(3)}})
	}))
	defer srv.Close()
	c, _ := Nuevo(srv.URL)
	if _, err := c.Uno(context.Background(), "a"); err == nil || !strings.Contains(err.Error(), "dimensiones") {
		t.Fatalf("esperaba error de dimensiones: %v", err)
	}
}

func TestVectoresErrorHTTP(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Error(w, "model not found", 404) }))
	defer srv.Close()
	c, _ := Nuevo(srv.URL)
	if _, err := c.Uno(context.Background(), "a"); err == nil || !strings.Contains(err.Error(), "404") {
		t.Fatalf("esperaba el 404: %v", err)
	}
}
