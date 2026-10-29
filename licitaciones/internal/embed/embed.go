// Package embed convierte textos en vectores con Ollama (modelo bge-m3, 1024 dimensiones). Es un cliente HTTP mínimo hacia una dirección fija de la red
// interna (LIC_OLLAMA_URL): no sigue redirecciones ni descarga nada de direcciones que vengan de los datos.
package embed

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Modelo y dimensiones del Cerebro (config/modelos.yaml); si cambian hay que revectorizar (la tabla guarda el modelo con cada vector).
const (
	Modelo      = "bge-m3"
	Dimensiones = 1024
)

// Cliente habla con /api/embed de Ollama.
type Cliente struct {
	Base   string
	Modelo string
	HTTP   *http.Client
}

// Nuevo valida la dirección (http o https, sin credenciales) y crea el cliente. Dirección vacía = sin cliente (la búsqueda por significado queda desactivada).
func Nuevo(base string) (*Cliente, error) {
	base = strings.TrimRight(strings.TrimSpace(base), "/")
	if base == "" {
		return nil, nil
	}
	u, err := url.Parse(base)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || u.User != nil {
		return nil, errors.New("embed: la dirección de Ollama no es válida (esperaba http://servidor:puerto)")
	}
	return &Cliente{
		Base: base, Modelo: Modelo,
		HTTP: &http.Client{
			Timeout:       120 * time.Second,
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		},
	}, nil
}

// Vectores devuelve un vector por texto, en el mismo orden.
func (c *Cliente) Vectores(ctx context.Context, textos []string) ([][]float32, error) {
	if len(textos) == 0 {
		return nil, nil
	}
	cuerpo, err := json.Marshal(map[string]any{"model": c.Modelo, "input": textos, "truncate": true})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.Base+"/api/embed", bytes.NewReader(cuerpo))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, fmt.Errorf("embed: Ollama no responde: %w", err)
	}
	defer resp.Body.Close()
	datos, err := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
	if err != nil {
		return nil, fmt.Errorf("embed: leer la respuesta: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("embed: Ollama respondió %d: %.200s", resp.StatusCode, datos)
	}
	var r struct {
		Embeddings [][]float32 `json:"embeddings"`
	}
	if err := json.Unmarshal(datos, &r); err != nil {
		return nil, fmt.Errorf("embed: respuesta no válida: %w", err)
	}
	if len(r.Embeddings) != len(textos) {
		return nil, fmt.Errorf("embed: pedí %d vectores y llegaron %d", len(textos), len(r.Embeddings))
	}
	for i, v := range r.Embeddings {
		if len(v) != Dimensiones {
			return nil, fmt.Errorf("embed: el vector %d tiene %d dimensiones y se esperaban %d (¿otro modelo?)", i, len(v), Dimensiones)
		}
	}
	return r.Embeddings, nil
}

// Uno es Vectores para un solo texto.
func (c *Cliente) Uno(ctx context.Context, texto string) ([]float32, error) {
	v, err := c.Vectores(ctx, []string{texto})
	if err != nil {
		return nil, err
	}
	return v[0], nil
}
