// Command proyector: construye el modelo de lectura de los expedientes a partir de los eventos del bus (PostgreSQL). Escucha solo /healthz;
// la configuración llega por variables de entorno (las mismas conexiones que el ingestor, ver internal/ingestor).
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingestor"
	"github.com/ionindustry/cerebro101/licitaciones/internal/projector"
	"github.com/ionindustry/cerebro101/licitaciones/internal/service"
	"github.com/ionindustry/cerebro101/licitaciones/internal/version"
)

func main() { os.Exit(run()) }

func run() int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	for _, a := range os.Args[1:] {
		if a == "-version" || a == "--version" {
			fmt.Println("proyector", version.String())
			return 0
		}
	}
	cfg, err := ingestor.FromEnv(os.Getenv)
	if err != nil {
		fmt.Fprintf(os.Stderr, "proyector: %v\n", err)
		return 2
	}
	log := slog.New(slog.NewJSONHandler(os.Stderr, nil)).With("servicio", "proyector", "version", version.String())
	ctx, cancel := context.WithCancelCause(ctx)
	defer cancel(nil)
	done := make(chan error, 1)
	go func() { err := projector.Run(ctx, cfg, log); cancel(err); done <- err }()

	err = service.Run(ctx, "proyector", service.Options{Stdout: os.Stdout, Stderr: os.Stderr, Getenv: os.Getenv}, func(*http.ServeMux) {})
	cancel(nil)
	if werr := <-done; werr != nil {
		fmt.Fprintf(os.Stderr, "proyector: %v\n", werr)
		return 1
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "proyector: %v\n", err)
		return 1
	}
	return 0
}
