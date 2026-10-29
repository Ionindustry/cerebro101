// Command vectorizador: calcula los vectores de los expedientes para la búsqueda por significado y por cercanía. Escucha solo /healthz.
// Configuración por entorno: LIC_PG_URL (base) y LIC_OLLAMA_URL (Ollama del Cerebro, p. ej. http://ollama:11434). Sin LIC_OLLAMA_URL no hace nada.
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ionindustry/cerebro101/licitaciones/internal/embed"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingestor"
	"github.com/ionindustry/cerebro101/licitaciones/internal/service"
	"github.com/ionindustry/cerebro101/licitaciones/internal/startup"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
	"github.com/ionindustry/cerebro101/licitaciones/internal/vectorizador"
	"github.com/ionindustry/cerebro101/licitaciones/internal/version"
)

// EnvOllama es la dirección de Ollama.
const EnvOllama = "LIC_OLLAMA_URL"

func main() { os.Exit(run()) }

func run() int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	for _, a := range os.Args[1:] {
		if a == "-version" || a == "--version" {
			fmt.Println("vectorizador", version.String())
			return 0
		}
	}
	dsn := os.Getenv(ingestor.EnvPG)
	if dsn == "" {
		fmt.Fprintf(os.Stderr, "vectorizador: falta la variable %s\n", ingestor.EnvPG)
		return 2
	}
	cli, err := embed.Nuevo(os.Getenv(EnvOllama))
	if err != nil {
		fmt.Fprintf(os.Stderr, "vectorizador: %s: %v\n", EnvOllama, err)
		return 2
	}
	log := slog.New(slog.NewJSONHandler(os.Stderr, nil)).With("servicio", "vectorizador", "version", version.String())
	ctx, cancel := context.WithCancelCause(ctx)
	defer cancel(nil)
	done := make(chan error, 1)
	if cli == nil {
		log.Warn("sin " + EnvOllama + ": la búsqueda por significado queda desactivada")
		close(done)
	} else {
		pool, err := startup.Retry(ctx, log, "postgres", func() (*pgxpool.Pool, error) { return pg.Connect(ctx, dsn) })
		if err != nil {
			fmt.Fprintf(os.Stderr, "vectorizador: %v\n", err)
			return 1
		}
		defer pool.Close()
		// Las migraciones las aplican la API y el proyector; aquí hace falta la tabla expedientes, que espera la primera de ellas.
		if err := pg.Migrate(ctx, pool); err != nil {
			fmt.Fprintf(os.Stderr, "vectorizador: %v\n", err)
			return 1
		}
		go func() {
			err := vectorizador.Run(ctx, pg.New(pool), cli, vectorizador.Opciones{Modelo: cli.Modelo}, log)
			cancel(err)
			done <- err
		}()
	}
	err = service.Run(ctx, "vectorizador", service.Options{Stdout: os.Stdout, Stderr: os.Stderr, Getenv: os.Getenv}, func(*http.ServeMux) {})
	cancel(nil)
	if werr := <-done; werr != nil {
		fmt.Fprintf(os.Stderr, "vectorizador: %v\n", werr)
		return 1
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "vectorizador: %v\n", err)
		return 1
	}
	return 0
}
