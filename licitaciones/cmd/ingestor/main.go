// Command ingestor: ingesta las fuentes de contratación (PLACSP) en el almacén de originales, el estado en Postgres y el bus de eventos.
// Escucha solo /healthz; la configuración llega por variables de entorno (ver internal/ingestor).
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
	"github.com/ionindustry/cerebro101/licitaciones/internal/service"
	"github.com/ionindustry/cerebro101/licitaciones/internal/version"
)

func main() { os.Exit(run()) }

func run() int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	for _, a := range os.Args[1:] {
		if a == "-version" || a == "--version" {
			fmt.Println("ingestor", version.String())
			return 0
		}
	}
	cfg, err := ingestor.FromEnv(os.Getenv)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ingestor: %v\n", err)
		return 2
	}
	log := slog.New(slog.NewJSONHandler(os.Stderr, nil)).With("servicio", "ingestor", "version", version.String())
	ctx, cancel := context.WithCancelCause(ctx)
	defer cancel(nil)
	done := make(chan error, 1)
	go func() { err := ingestor.Run(ctx, cfg, log); cancel(err); done <- err }()

	err = service.Run(ctx, "ingestor", service.Options{Args: nil, Stdout: os.Stdout, Stderr: os.Stderr, Getenv: os.Getenv}, func(*http.ServeMux) {})
	cancel(nil)
	if werr := <-done; werr != nil {
		fmt.Fprintf(os.Stderr, "ingestor: %v\n", werr)
		return 1
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "ingestor: %v\n", err)
		return 1
	}
	return 0
}
