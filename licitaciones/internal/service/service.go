// Package service es el arranque común de los binarios del motor (api, ingestor, proyector):
// registro JSON con log/slog, configuración por variables de entorno, /healthz y parada
// ordenada con SIGINT/SIGTERM. Cada binario solo registra lo suyo.
package service

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/version"
)

// Variables de entorno comunes.
const (
	EnvAddr     = "LICITACIONES_ADDR"      // dirección de escucha; por defecto solo bucle local
	EnvLogLevel = "LICITACIONES_LOG_LEVEL" // debug, info, warn o error
	defaultAddr = "127.0.0.1:8081"
)

// Options permite a las pruebas sustituir la entrada y la salida.
type Options struct {
	Args   []string
	Stdout io.Writer
	Stderr io.Writer
	Getenv func(string) string
	// Ready se llama con la dirección real de escucha una vez abierto el puerto.
	Ready func(net.Addr)
}

// Main arranca el servicio con la configuración del proceso y devuelve el código de salida.
func Main(name string, register func(mux *http.ServeMux)) int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	err := Run(ctx, name, Options{Args: os.Args[1:], Stdout: os.Stdout, Stderr: os.Stderr, Getenv: os.Getenv}, register)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s: %v\n", name, err)
		return 1
	}
	return 0
}

// Run abre el puerto, sirve /healthz y lo que registre el binario, y vuelve cuando ctx se cancela.
func Run(ctx context.Context, name string, o Options, register func(mux *http.ServeMux)) error {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(o.Stderr)
	showVersion := fs.Bool("version", false, "muestra la versión y termina")
	if err := fs.Parse(o.Args); err != nil {
		return err
	}
	if *showVersion {
		_, err := fmt.Fprintf(o.Stdout, "%s %s\n", name, version.String())
		return err
	}

	level, err := parseLevel(o.Getenv(EnvLogLevel))
	if err != nil {
		return err
	}
	logger := slog.New(slog.NewJSONHandler(o.Stderr, &slog.HandlerOptions{Level: level})).With("servicio", name, "version", version.String())

	addr := o.Getenv(EnvAddr)
	if addr == "" {
		addr = defaultAddr
	}
	lc := net.ListenConfig{}
	ln, err := lc.Listen(ctx, "tcp", addr)
	if err != nil {
		return fmt.Errorf("escuchar en %s: %w", addr, err)
	}
	if o.Ready != nil {
		o.Ready(ln.Addr())
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", healthz(name))
	if register != nil {
		register(mux)
	}
	srv := &http.Server{
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
		MaxHeaderBytes:    1 << 16,
		ErrorLog:          slog.NewLogLogger(logger.Handler(), slog.LevelWarn),
	}

	errc := make(chan error, 1)
	go func() { errc <- srv.Serve(ln) }()
	logger.Info("servicio iniciado", "addr", ln.Addr().String())

	select {
	case err := <-errc:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return fmt.Errorf("servidor: %w", err)
	case <-ctx.Done():
	}

	logger.Info("parada ordenada")
	// El contexto de la parada no hereda la cancelación: se concede un plazo para terminar lo que está en curso.
	shutdownCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 15*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("parada: %w", err)
	}
	return nil
}

func healthz(name string) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		_ = json.NewEncoder(w).Encode(map[string]string{"estado": "ok", "servicio": name, "version": version.String()})
	}
}

func parseLevel(s string) (slog.Level, error) {
	if s == "" {
		return slog.LevelInfo, nil
	}
	var l slog.Level
	if err := l.UnmarshalText([]byte(s)); err != nil {
		return 0, fmt.Errorf("%s no válido (%q): usa debug, info, warn o error", EnvLogLevel, s)
	}
	return l, nil
}
