// Package vectorizador mantiene al día los vectores de los expedientes (búsqueda por significado): toma los que no tienen vector, o lo tienen de un texto
// antiguo, pide sus vectores a Ollama por lotes y los guarda. Va despacio a propósito (un lote cada vez): comparte Ollama con los agentes del Cerebro.
package vectorizador

import (
	"context"
	"log/slog"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

// Almacen es lo que necesita del almacén; lo cumple *pg.Store.
type Almacen interface {
	PrepararVectores(ctx context.Context) (bool, error)
	PorVectorizar(ctx context.Context, limite int) ([]pg.PorVectorizar, error)
	GuardarVectores(ctx context.Context, modelo string, ids []string, vectores [][]float32) error
}

// Embebedor convierte textos en vectores.
type Embebedor interface {
	Vectores(ctx context.Context, textos []string) ([][]float32, error)
}

// Opciones de la ejecución.
type Opciones struct {
	Modelo    string
	Lote      int           // expedientes por petición a Ollama
	Reposo    time.Duration // espera cuando no queda nada por vectorizar
	Reintento time.Duration // espera tras un error (Ollama caído, modelo sin descargar…)
}

func (o *Opciones) defecto() {
	if o.Lote < 1 {
		o.Lote = 32
	}
	if o.Reposo <= 0 {
		o.Reposo = 30 * time.Second
	}
	if o.Reintento <= 0 {
		o.Reintento = time.Minute
	}
}

// Run trabaja hasta que se cancele el contexto.
func Run(ctx context.Context, a Almacen, e Embebedor, o Opciones, log *slog.Logger) error {
	o.defecto()
	// Sin pgvector no hay nada que hacer: se avisa y se queda esperando (por si se cambia la imagen de la base y se reinicia).
	for {
		ok, err := a.PrepararVectores(ctx)
		if err == nil && ok {
			break
		}
		if err != nil {
			log.Warn("no se pudo preparar la tabla de vectores", "error", err)
		} else {
			log.Warn("la base no tiene pgvector: la búsqueda por significado queda desactivada (ver docs: imagen pgvector/pgvector:pg16)")
		}
		if !esperar(ctx, 10*o.Reintento) {
			return nil
		}
	}
	log.Info("vectorizador listo", "modelo", o.Modelo, "lote", o.Lote)
	hechos := 0
	for {
		lote, err := a.PorVectorizar(ctx, o.Lote)
		if err == nil && len(lote) > 0 {
			err = procesar(ctx, a, e, o.Modelo, lote)
			if err == nil {
				hechos += len(lote)
				if hechos%(10*o.Lote) < len(lote) {
					log.Info("vectorizando", "hechos_desde_el_arranque", hechos)
				}
				continue // sin pausa: hay más
			}
		}
		espera := o.Reposo
		if err != nil {
			log.Warn("vectorización fallida; se reintenta", "error", err)
			espera = o.Reintento
		}
		if !esperar(ctx, espera) {
			return nil
		}
	}
}

func procesar(ctx context.Context, a Almacen, e Embebedor, modelo string, lote []pg.PorVectorizar) error {
	textos := make([]string, len(lote))
	ids := make([]string, len(lote))
	for i, p := range lote {
		textos[i], ids[i] = p.Texto, p.ID
	}
	vs, err := e.Vectores(ctx, textos)
	if err != nil {
		return err
	}
	return a.GuardarVectores(ctx, modelo, ids, vs)
}

func esperar(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}
