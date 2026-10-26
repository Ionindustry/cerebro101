// Banco de pruebas Neo4j frente a Memgraph para el motor de licitaciones (fase 0, §12.7).
//
// Uso (dentro del contenedor cliente; ver run.sh y README.md):
//
//	bench -engine neo4j|memgraph <orden> [opciones]
//
// Órdenes: stats, wait, schema, load, upsert, query, explain, info.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/neo4j/neo4j-go-driver/v5/neo4j"
	"github.com/neo4j/neo4j-go-driver/v5/neo4j/config"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func run() error {
	fs := flag.NewFlagSet("bench", flag.ExitOnError)
	engine := fs.String("engine", "neo4j", "neo4j | memgraph")
	uri := fs.String("uri", "", "URI Bolt (por defecto bolt://licit-bench-<engine>:7687)")
	seed := fs.Uint64("seed", 20261026, "semilla del generador")
	todayS := fs.String("today", "2026-10-26", "fecha de referencia (AAAA-MM-DD)")
	from := fs.Int("from", 0, "primer expediente (incluido)")
	to := fs.Int("to", 1000000, "último expediente (excluido)")
	procs := fs.Int("procs", 1000000, "expedientes cargados (para elegir parámetros)")
	chunk := fs.Int("chunk", 5000, "expedientes por bloque de carga")
	batch := fs.Int("batch", 10000, "filas por UNWIND")
	static := fs.Bool("static", false, "cargar antes catálogos y organizaciones")
	mode := fs.String("mode", "warm", "warm | cold")
	conc := fs.Int("conc", 1, "concurrencia")
	n := fs.Int("n", 500, "ejecuciones (o parámetros) por consulta")
	maxSec := fs.Float64("maxsec", 60, "tiempo máximo por consulta y fase")
	only := fs.String("only", "", "lista de consultas separadas por comas")
	tag := fs.String("tag", "", "etiqueta de la tanda")
	outCSV := fs.String("csv", "", "CSV de salida (se añade)")
	outJSON := fs.String("json", "", "JSON de salida")
	timeout := fs.Duration("timeout", 15*time.Minute, "espera máxima (wait)")
	if len(os.Args) < 2 {
		return fmt.Errorf("falta la orden")
	}
	cmd := os.Args[1]
	if err := fs.Parse(os.Args[2:]); err != nil {
		return err
	}
	today, err := time.Parse("2006-01-02", *todayS)
	if err != nil {
		return fmt.Errorf("fecha: %w", err)
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	if cmd == "stats" {
		return genStats(newWorld(*seed, today), *from, *to)
	}
	if *uri == "" {
		*uri = "bolt://licit-bench-" + *engine + ":7687"
	}
	auth := neo4j.NoAuth()
	if pw := os.Getenv("BENCH_PASSWORD"); pw != "" {
		auth = neo4j.BasicAuth(os.Getenv("BENCH_USER"), pw, "")
	}
	drv, err := neo4j.NewDriverWithContext(*uri, auth, func(c *config.Config) {
		c.MaxConnectionPoolSize = 64
		c.ConnectionAcquisitionTimeout = 2 * time.Minute
		c.SocketConnectTimeout = 5 * time.Second
	})
	if err != nil {
		return fmt.Errorf("driver: %w", err)
	}
	defer drv.Close(ctx)

	switch cmd {
	case "wait":
		t0 := time.Now()
		for {
			cctx, c := context.WithTimeout(ctx, 3*time.Second)
			s := drv.NewSession(cctx, neo4j.SessionConfig{})
			res, err := s.Run(cctx, "RETURN 1 AS x", nil)
			if err == nil {
				_, err = res.Consume(cctx)
			}
			s.Close(cctx)
			c()
			if err == nil {
				fmt.Printf("listo en %d ms\n", time.Since(t0).Milliseconds())
				return nil
			}
			if time.Since(t0) > *timeout {
				return fmt.Errorf("el motor no responde tras %s: %w", *timeout, err)
			}
			time.Sleep(200 * time.Millisecond)
		}
	case "schema":
		return runSchema(ctx, drv, *engine)
	case "load", "upsert":
		w := newWorld(*seed, today)
		return runLoad(ctx, drv, w, *engine, *from, *to, *chunk, *batch, *static, cmd == "upsert", *outJSON, *outCSV)
	case "query":
		w := newWorld(*seed, today)
		return runQueries(ctx, drv, w, *engine, *tag, *mode, *procs, *conc, *n, *maxSec, *only, *outCSV, *outJSON)
	case "explain":
		return explain(ctx, drv, newWorld(*seed, today), *procs)
	case "info":
		return info(ctx, drv, *engine)
	default:
		return fmt.Errorf("orden desconocida %q", cmd)
	}
}

func info(ctx context.Context, drv neo4j.DriverWithContext, engine string) error {
	s := drv.NewSession(ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeRead})
	defer s.Close(ctx)
	qs := []string{"MATCH (n) RETURN count(n) AS nodos", "MATCH ()-[r]->() RETURN count(r) AS relaciones"}
	if engine == "memgraph" {
		qs = append(qs, "SHOW STORAGE INFO")
	}
	for _, q := range qs {
		res, err := s.Run(ctx, q, nil)
		if err != nil {
			return fmt.Errorf("%s: %w", q, err)
		}
		recs, err := res.Collect(ctx)
		if err != nil {
			return fmt.Errorf("%s: %w", q, err)
		}
		for _, r := range recs {
			var parts []string
			for i, k := range r.Keys {
				parts = append(parts, fmt.Sprintf("%s=%v", k, r.Values[i]))
			}
			fmt.Println(strings.Join(parts, " "))
		}
	}
	return nil
}

// genStats: recuento del conjunto sin motor (comprueba distribuciones y volumen).
func genStats(w *world, from, to int) error {
	t0 := time.Now()
	var lots, notices, versions, awards, bids, sup int
	firmWins := make([]int, nFirms)
	buyerProcs := make([]int, nBuyers)
	status := map[string]int{}
	for i := from; i < to; i++ {
		p := w.proc(i)
		buyerProcs[p.Buyer]++
		status[p.Status]++
		lots += len(p.Lots)
		for _, l := range p.Lots {
			if l.Award != nil {
				awards++
				firmWins[l.Award.Firm]++
			}
			bids += len(l.Bidders)
		}
		notices += len(p.Notices)
		for _, n := range p.Notices {
			versions += len(n.Versions)
			if len(n.Versions) > 1 {
				sup += len(n.Versions) - 1
			}
		}
	}
	np := to - from
	nodes := np + lots + notices + versions + awards + nBuyers + nFirms
	fmt.Printf("expedientes=%d lotes=%d anuncios=%d versiones=%d adjudicaciones=%d licitadores(COMPETED_IN)=%d supersedes=%d\n",
		np, lots, notices, versions, awards, bids, sup)
	fmt.Printf("nodos≈%d (sin catálogos) generados en %.1f s\n", nodes, time.Since(t0).Seconds())
	fmt.Println("estados:", status)
	top := func(xs []int, k int) (int, float64) {
		c := append([]int(nil), xs...)
		// orden descendente parcial
		for i := 0; i < k && i < len(c); i++ {
			for j := i + 1; j < len(c); j++ {
				if c[j] > c[i] {
					c[i], c[j] = c[j], c[i]
				}
			}
		}
		tot, s := 0, 0
		for _, x := range xs {
			tot += x
		}
		for i := 0; i < k; i++ {
			s += c[i]
		}
		return c[0], float64(s) / float64(tot)
	}
	mx, share := top(firmWins, 1500)
	zero := 0
	for _, x := range firmWins {
		if x == 0 {
			zero++
		}
	}
	fmt.Printf("empresas: máx adjudicaciones=%d, cuota del 1%% superior=%.1f%%, sin adjudicaciones=%d\n", mx, share*100, zero)
	mb, bshare := top(buyerProcs, 200)
	fmt.Printf("compradores: máx expedientes=%d, cuota del 1%% superior=%.1f%%\n", mb, bshare*100)
	return nil
}
