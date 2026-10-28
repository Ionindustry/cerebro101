// Command proyector: construye el modelo de lectura de los expedientes a partir de los eventos del bus (PostgreSQL). Escucha solo /healthz;
// la configuración llega por variables de entorno (las mismas conexiones que el ingestor, ver internal/ingestor).
package main

import (
	"context"
	"flag"
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
	if len(os.Args) > 1 && os.Args[1] == "reproyectar" {
		return reproyectar(ctx, cfg, os.Args[2:])
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

// reproyectar es la tarea de una sola vez `proyector reproyectar [-fuente placsp-643] [-limite N] [-despues ID] [-simular]`: vuelve a leer los originales de los expedientes ya
// proyectados y rehace su modelo de lectura con el parser actual (por ejemplo, para que los expedientes antiguos tengan lo que el parser aprendió después).
func reproyectar(ctx context.Context, cfg ingestor.Config, args []string) int {
	fs := flag.NewFlagSet("reproyectar", flag.ContinueOnError)
	var opt projector.OpcionesReproyeccion
	fs.StringVar(&opt.Fuente, "fuente", "", "solo esta fuente (placsp-643…); vacío = todas")
	fs.IntVar(&opt.Limite, "limite", 0, "como máximo este número de expedientes; 0 = todos")
	fs.StringVar(&opt.Despues, "despues", "", "seguir después de este id de expediente (el que enseñó una pasada cortada)")
	fs.BoolVar(&opt.Simular, "simular", false, "no escribe nada: cuenta cuántos expedientes cambiarían")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if opt.Limite < 0 {
		fmt.Fprintln(os.Stderr, "proyector reproyectar: -limite no puede ser negativo")
		return 2
	}
	log := slog.New(slog.NewJSONHandler(os.Stderr, nil)).With("servicio", "proyector", "tarea", "reproyectar", "version", version.String())
	opt.Progreso = func(r projector.ResumenReproyeccion) { fmt.Println("…", r) }
	r, err := projector.ReproyectarTodo(ctx, cfg, opt, log)
	modo := "Reproyección"
	if opt.Simular {
		modo = "Simulación (no se ha escrito nada)"
	}
	fmt.Printf("%s: %s\n", modo, r)
	if err != nil {
		fmt.Fprintf(os.Stderr, "proyector reproyectar: %v (se puede repetir sin riesgo; para seguir por donde iba: -despues %s)\n", err, r.UltimoID)
		return 1
	}
	if !r.Terminado {
		fmt.Println("Se ha parado en el límite pedido. Para seguir: -despues", r.UltimoID)
	}
	return 0
}
