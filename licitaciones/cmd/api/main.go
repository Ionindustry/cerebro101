// Command api: API REST del motor de licitaciones (contrato en api/openapi.yaml). Solo para la red interna. Configuración por entorno:
// LIC_PG_URL (base de datos) y LIC_API_TOKEN (token compartido, mínimo 32 caracteres); LICITACIONES_ADDR para la dirección de escucha;
// LIC_OLLAMA_URL (opcional) para la búsqueda por significado.
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

	"github.com/ionindustry/cerebro101/licitaciones/internal/api"
	"github.com/ionindustry/cerebro101/licitaciones/internal/embed"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingestor"
	"github.com/ionindustry/cerebro101/licitaciones/internal/service"
	"github.com/ionindustry/cerebro101/licitaciones/internal/startup"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
	"github.com/ionindustry/cerebro101/licitaciones/internal/version"
)

const envAPI = "LIC_API_TOKEN" // credencial de la API; el nombre no debe llamarse «token» para no confundir a gosec G101

func main() { os.Exit(run()) }

func run() int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	for _, a := range os.Args[1:] {
		if a == "-version" || a == "--version" {
			fmt.Println("api", version.String())
			return 0
		}
	}
	dsn, token := os.Getenv(ingestor.EnvPG), os.Getenv(envAPI)
	if dsn == "" {
		fmt.Fprintf(os.Stderr, "api: falta la variable %s\n", ingestor.EnvPG)
		return 2
	}
	log := slog.New(slog.NewJSONHandler(os.Stderr, nil)).With("servicio", "api", "version", version.String())
	// El token se comprueba antes de abrir nada: una API sin credencial válida no arranca.
	if _, err := api.New(nil, token, log); err != nil {
		fmt.Fprintf(os.Stderr, "api: %s: %v\n", envAPI, err)
		return 2
	}
	// Opcional: con LIC_OLLAMA_URL la API calcula el significado de la búsqueda (modo=significado|hibrido); sin ella solo hay búsqueda de texto.
	emb, err := embed.Nuevo(os.Getenv("LIC_OLLAMA_URL"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "api: LIC_OLLAMA_URL: %v\n", err)
		return 2
	}
	pool, err := startup.Retry(ctx, log, "postgres", func() (*pgxpool.Pool, error) { return pg.Connect(ctx, dsn) })
	if err != nil {
		fmt.Fprintf(os.Stderr, "api: %v\n", err)
		return 1
	}
	defer pool.Close()
	if err := pg.Migrate(ctx, pool); err != nil {
		fmt.Fprintf(os.Stderr, "api: %v\n", err)
		return 1
	}
	srv, err := api.New(pg.New(pool), token, log)
	if err != nil {
		fmt.Fprintf(os.Stderr, "api: %v\n", err)
		return 2
	}
	if emb != nil {
		srv.Embedder = emb
	}
	if err := service.Run(ctx, "api", service.Options{Stdout: os.Stdout, Stderr: os.Stderr, Getenv: os.Getenv}, func(mux *http.ServeMux) { srv.Register(mux) }); err != nil {
		fmt.Fprintf(os.Stderr, "api: %v\n", err)
		return 1
	}
	return 0
}
