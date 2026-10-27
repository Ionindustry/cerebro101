package service

import (
	"bytes"
	"context"
	"encoding/json"
	"net"
	"net/http"
	"strings"
	"testing"
	"time"
)

func env(m map[string]string) func(string) string { return func(k string) string { return m[k] } }

func TestVersionNoArrancaElServidor(t *testing.T) {
	var out bytes.Buffer
	err := Run(context.Background(), "api", Options{Args: []string{"-version"}, Stdout: &out, Stderr: &bytes.Buffer{}, Getenv: env(nil)}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(out.String(), "api ") {
		t.Fatalf("salida inesperada: %q", out.String())
	}
}

func TestNivelDeRegistroNoValido(t *testing.T) {
	err := Run(context.Background(), "api", Options{Stdout: &bytes.Buffer{}, Stderr: &bytes.Buffer{}, Getenv: env(map[string]string{EnvLogLevel: "charlatan"})}, nil)
	if err == nil || !strings.Contains(err.Error(), EnvLogLevel) {
		t.Fatalf("esperaba un error que nombre %s, llegó %v", EnvLogLevel, err)
	}
}

func TestDireccionOcupada(t *testing.T) {
	ln, err := (&net.ListenConfig{}).Listen(context.Background(), "tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	err = Run(context.Background(), "api", Options{Stdout: &bytes.Buffer{}, Stderr: &bytes.Buffer{}, Getenv: env(map[string]string{EnvAddr: ln.Addr().String()})}, nil)
	if err == nil {
		t.Fatal("esperaba un error al escuchar en un puerto ocupado")
	}
}

func TestServeHealthzYSeParaConElContexto(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan net.Addr, 1)
	done := make(chan error, 1)
	go func() {
		done <- Run(ctx, "ingestor", Options{
			Stdout: &bytes.Buffer{}, Stderr: &bytes.Buffer{},
			Getenv: env(map[string]string{EnvAddr: "127.0.0.1:0"}),
			Ready:  func(a net.Addr) { ready <- a },
		}, func(mux *http.ServeMux) {
			mux.HandleFunc("GET /extra", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNoContent) })
		})
	}()
	addr := (<-ready).String()

	get := func(path string) *http.Response {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://"+addr+path, nil)
		if err != nil {
			t.Fatal(err)
		}
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		return resp
	}

	resp := get("/healthz")
	defer resp.Body.Close()
	var body map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if resp.StatusCode != http.StatusOK || body["estado"] != "ok" || body["servicio"] != "ingestor" {
		t.Fatalf("healthz inesperado: %d %v", resp.StatusCode, body)
	}
	extra := get("/extra")
	defer extra.Body.Close()
	if extra.StatusCode != http.StatusNoContent {
		t.Fatalf("la ruta registrada por el binario no responde: %d", extra.StatusCode)
	}
	nope := get("/no-existe")
	defer nope.Body.Close()
	if nope.StatusCode != http.StatusNotFound {
		t.Fatalf("una ruta desconocida debe dar 404, dio %d", nope.StatusCode)
	}

	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("la parada ordenada devolvió un error: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("el servicio no se paró tras cancelar el contexto")
	}
}
