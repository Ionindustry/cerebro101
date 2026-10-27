package main

// Consultas objetivo del proyecto, parametrizadas, con parámetros aleatorios reproducibles y medida de latencias.

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"math"
	"math/rand/v2"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/neo4j/neo4j-go-driver/v5/neo4j"
)

type querySpec struct {
	Name  string
	Desc  string
	Text  string
	Param func(w *world, r *rand.Rand, n int) map[string]any
}

// randomProc: un expediente cargado al azar que cumpla la condición (o el último probado).
func randomProc(w *world, r *rand.Rand, n int, ok func(*procedure) bool) *procedure {
	var p *procedure
	for i := 0; i < 200; i++ {
		p = w.proc(r.IntN(n))
		if ok == nil || ok(p) {
			return p
		}
	}
	return p
}

func awardedLot(p *procedure, needBidders bool) *lot {
	for i := range p.Lots {
		l := &p.Lots[i]
		if l.Award != nil && (!needBidders || len(l.Bidders) > 1) {
			return l
		}
	}
	return nil
}

var queries = []querySpec{
	{
		Name: "q1_comprador_cpv",
		Desc: "Concursos de un comprador en un prefijo CPV (los 50 más recientes)",
		Text: `MATCH (b:Organization {id: $buyer})<-[:PUBLISHED_BY]-(p:Procedure)-[:CLASSIFIED_AS]->(c:CPV)
WHERE c.code STARTS WITH $cpv
RETURN p.id AS id, p.title AS title, p.date AS date, p.budget AS budget, c.code AS cpv
ORDER BY date DESC LIMIT 50`,
		Param: func(w *world, r *rand.Rand, n int) map[string]any {
			p := randomProc(w, r, n, nil)
			k := 2 + r.IntN(2)
			return map[string]any{"buyer": w.buyers[p.Buyer].ID, "cpv": p.CPV[:k]}
		},
	},
	{
		Name: "q2_adjudicaciones_proveedor",
		Desc: "Adjudicaciones de un proveedor por NIF (las 100 más recientes)",
		Text: `MATCH (s:Organization {nif: $nif})-[a:AWARDED_TO]->(l:Lot)<-[:HAS_LOT]-(p:Procedure)-[:PUBLISHED_BY]->(b:Organization)
RETURN p.id AS id, l.id AS lot, a.importe AS importe, a.baja AS baja, a.fecha AS fecha, b.name AS comprador
ORDER BY fecha DESC LIMIT 100`,
		Param: func(w *world, r *rand.Rand, n int) map[string]any {
			p := randomProc(w, r, n, func(p *procedure) bool { return awardedLot(p, false) != nil })
			l := awardedLot(p, false)
			if l == nil {
				return map[string]any{"nif": w.firms[0].NIF}
			}
			return map[string]any{"nif": w.firms[l.Award.Firm].NIF}
		},
	},
	{
		Name: "q3_competidores_cpv_nuts",
		Desc: "Top competidores en un prefijo CPV y una zona NUTS2, últimos 24 meses, con baja media",
		Text: `MATCH (n:Nuts) WHERE n.level = 3 AND n.code STARTS WITH $nuts
MATCH (n)<-[:LOCATED_IN]-(p:Procedure)-[:CLASSIFIED_AS]->(c:CPV)
WHERE p.date >= $since AND c.code STARTS WITH $cpv
MATCH (p)-[:HAS_LOT]->(l:Lot)<-[a:AWARDED_TO]-(s:Organization)
RETURN s.nif AS nif, s.name AS name, count(a) AS adjudicaciones, sum(a.importe) AS importe, avg(a.baja) AS baja_media
ORDER BY adjudicaciones DESC LIMIT 20`,
		Param: func(w *world, r *rand.Rand, n int) map[string]any {
			p := randomProc(w, r, n, func(p *procedure) bool { return awardedLot(p, false) != nil })
			sig := significant(p.CPV)
			k := 3 + r.IntN(2)
			if k > len(sig) {
				k = len(sig)
			}
			return map[string]any{"nuts": nuts3[p.Nuts3].Code[:4], "cpv": sig[:k], "since": neo4j.DateOf(w.today.AddDate(0, -24, 0))}
		},
	},
	{
		Name: "q4a_vecindad_comprador",
		Desc: "Comprador → proveedores a los que adjudica (1 salto lógico, 3 físicos), top 20",
		Text: `MATCH (b:Organization {id: $buyer})<-[:PUBLISHED_BY]-(p:Procedure)-[:HAS_LOT]->(l:Lot)<-[a:AWARDED_TO]-(s:Organization)
RETURN s.nif AS nif, s.name AS name, count(a) AS contratos, sum(a.importe) AS importe
ORDER BY contratos DESC LIMIT 20`,
		Param: func(w *world, r *rand.Rand, n int) map[string]any {
			p := randomProc(w, r, n, nil)
			return map[string]any{"buyer": w.buyers[p.Buyer].ID}
		},
	},
	{
		Name: "q4b_vecindad_competidores",
		Desc: "Proveedor → lotes en que compitió → otros licitadores (2 saltos), con quién ganó",
		Text: `MATCH (s:Organization {nif: $nif})-[:COMPETED_IN]->(l:Lot)<-[:COMPETED_IN]-(o:Organization)
WHERE o <> s
OPTIONAL MATCH (o)-[w:AWARDED_TO]->(l)
RETURN o.nif AS nif, o.name AS name, count(l) AS encuentros, count(w) AS victorias
ORDER BY encuentros DESC LIMIT 20`,
		Param: func(w *world, r *rand.Rand, n int) map[string]any {
			p := randomProc(w, r, n, func(p *procedure) bool { return awardedLot(p, true) != nil })
			l := awardedLot(p, true)
			if l == nil {
				return map[string]any{"nif": w.firms[0].NIF}
			}
			b := l.Bidders[r.IntN(len(l.Bidders))]
			return map[string]any{"nif": w.firms[b.Firm].NIF}
		},
	},
	{
		Name: "q5_historial_versiones",
		Desc: "Historial de anuncios y versiones de un expediente",
		Text: `MATCH (p:Procedure {id: $id})-[:HAS_NOTICE]->(n:Notice)-[:HAS_VERSION]->(v:NoticeVersion)
OPTIONAL MATCH (v)-[:SUPERSEDES]->(prev:NoticeVersion)
RETURN n.id AS notice, n.type AS type, v.version AS version, v.published AS published, v.hash AS hash, prev.id AS supersedes
ORDER BY published, version`,
		Param: func(w *world, r *rand.Rand, n int) map[string]any {
			return map[string]any{"id": w.proc(r.IntN(n)).ID}
		},
	},
	{
		Name: "q6_contratos_vencen",
		Desc: "Contratos de un conjunto de CPV que vencen en 3–12 meses (los 200 primeros)",
		Text: `MATCH (c:CPV) WHERE c.code IN $cpvs
MATCH (c)<-[:CLASSIFIED_AS]-(l:Lot)<-[:REFERENCES]-(a:Award)
WHERE a.end_date >= $from AND a.end_date <= $to
MATCH (s:Organization)-[:AWARDED_TO]->(l)<-[:HAS_LOT]-(p:Procedure)-[:PUBLISHED_BY]->(b:Organization)
RETURN p.id AS id, l.id AS lot, c.code AS cpv, a.end_date AS fin, a.importe AS importe, s.nif AS adjudicatario, b.name AS comprador
ORDER BY fin LIMIT 200`,
		Param: func(w *world, r *rand.Rand, n int) map[string]any {
			k := 3 + r.IntN(3)
			perm := r.Perm(len(cpvOfInterest))
			var cpvs []any
			for _, i := range perm[:k] {
				cpvs = append(cpvs, cpvOfInterest[i])
			}
			return map[string]any{"cpvs": cpvs, "from": neo4j.DateOf(w.today.AddDate(0, 3, 0)), "to": neo4j.DateOf(w.today.AddDate(0, 12, 0))}
		},
	},
	{
		Name: "q7_similares",
		Desc: "Concursos similares: mismo CPV y mismo organismo, con baja media adjudicada",
		Text: `MATCH (p:Procedure {id: $id})-[:PUBLISHED_BY]->(b:Organization)
MATCH (p)-[:CLASSIFIED_AS]->(c:CPV)
MATCH (b)<-[:PUBLISHED_BY]-(o:Procedure)-[:CLASSIFIED_AS]->(c)
WHERE o <> p
WITH o ORDER BY o.date DESC LIMIT 50
OPTIONAL MATCH (o)-[:HAS_LOT]->(:Lot)<-[a:AWARDED_TO]-(:Organization)
RETURN o.id AS id, o.date AS date, o.budget AS budget, count(a) AS adjudicaciones, avg(a.baja) AS baja_media
ORDER BY date DESC`,
		Param: func(w *world, r *rand.Rand, n int) map[string]any {
			return map[string]any{"id": w.proc(r.IntN(n)).ID}
		},
	},
}

func seedFor(parts ...string) uint64 {
	h := fnv.New64a()
	h.Write([]byte(strings.Join(parts, "|")))
	return h.Sum64()
}

type job struct {
	q   *querySpec
	seq int
	p   map[string]any
}

type sample struct {
	q     string
	seq   int
	us    int64
	rows  int
	err   string
	start time.Time
}

type qstats struct {
	Query  string  `json:"query"`
	N      int     `json:"n"`
	Errors int     `json:"errors"`
	P50    float64 `json:"p50_ms"`
	P95    float64 `json:"p95_ms"`
	P99    float64 `json:"p99_ms"`
	Max    float64 `json:"max_ms"`
	Mean   float64 `json:"mean_ms"`
	Rows   float64 `json:"mean_rows"`
	QPS    float64 `json:"qps"`
	Err1   string  `json:"first_error,omitempty"`
}

type runSummary struct {
	Engine  string    `json:"engine"`
	Tag     string    `json:"tag"`
	Mode    string    `json:"mode"`
	Conc    int       `json:"concurrency"`
	Procs   int       `json:"procedures_loaded"`
	Seconds float64   `json:"seconds"`
	Stats   []qstats  `json:"queries"`
	When    time.Time `json:"when"`
}

func pct(xs []float64, p float64) float64 {
	if len(xs) == 0 {
		return math.NaN()
	}
	i := int(math.Ceil(p/100*float64(len(xs)))) - 1
	if i < 0 {
		i = 0
	}
	return xs[i]
}

func execAll(ctx context.Context, drv neo4j.DriverWithContext, jobs []job, conc int, maxSec float64) []sample {
	ch := make(chan job)
	out := make(chan sample, 1024)
	var wg sync.WaitGroup
	for i := 0; i < conc; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			s := drv.NewSession(ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeRead})
			defer s.Close(ctx)
			for j := range ch {
				t0 := time.Now()
				res, err := s.Run(ctx, j.q.Text, j.p)
				rows := 0
				if err == nil {
					var recs []*neo4j.Record
					recs, err = res.Collect(ctx)
					rows = len(recs)
				}
				sm := sample{q: j.q.Name, seq: j.seq, us: time.Since(t0).Microseconds(), rows: rows, start: t0}
				if err != nil {
					sm.err = strings.ReplaceAll(err.Error(), "\n", " ")
					if len(sm.err) > 300 {
						sm.err = sm.err[:300]
					}
				}
				out <- sm
			}
		}()
	}
	var samples []sample
	done := make(chan struct{})
	go func() {
		for s := range out {
			samples = append(samples, s)
		}
		close(done)
	}()
	deadline := time.Now().Add(time.Duration(maxSec * float64(time.Second)))
	for _, j := range jobs {
		if time.Now().After(deadline) || ctx.Err() != nil {
			break
		}
		ch <- j
	}
	close(ch)
	wg.Wait()
	close(out)
	<-done
	return samples
}

// runQueries: mode warm = cada consulta por separado tras un calentamiento; cold = mezcla intercalada sin calentar.
func runQueries(ctx context.Context, drv neo4j.DriverWithContext, w *world, engine, tag, mode string, procs, conc, n int,
	maxSec float64, only string, outCSV, outJSON string) error {
	sel := queries
	if only != "" {
		sel = nil
		for _, q := range queries {
			if strings.Contains(","+only+",", ","+q.Name+",") {
				sel = append(sel, q)
			}
		}
	}
	pool := func(q *querySpec, kind string, k int) []job {
		r := rand.New(rand.NewPCG(w.seed, seedFor(q.Name, kind, strconv.Itoa(procs))))
		js := make([]job, k)
		for i := range js {
			js[i] = job{q: q, seq: i, p: q.Param(w, r, procs)}
		}
		return js
	}
	t0 := time.Now()
	var all []sample
	switch mode {
	case "warm":
		for i := range sel {
			q := &sel[i]
			js := pool(q, "warm", n)
			// calentamiento: el mismo conjunto de parámetros una vez, con concurrencia 16
			execAll(ctx, drv, js, 16, maxSec)
			// medida: n ejecuciones (con concurrencia > 1, el conjunto se recorre varias veces)
			var mj []job
			reps := 1
			if conc > 1 {
				reps = 4
			}
			for k := 0; k < reps; k++ {
				mj = append(mj, js...)
			}
			s := execAll(ctx, drv, mj, conc, maxSec)
			fmt.Printf("  %s %s c=%d: %d ejecuciones\n", engine, q.Name, conc, len(s))
			all = append(all, s...)
		}
	case "cold":
		// parámetros no vistos, intercalados entre tipos de consulta
		pools := make([][]job, len(sel))
		for i := range sel {
			pools[i] = pool(&sel[i], "cold-"+tag, n)
		}
		var mj []job
		for k := 0; k < n; k++ {
			for i := range sel {
				mj = append(mj, pools[i][k])
			}
		}
		all = execAll(ctx, drv, mj, conc, maxSec*float64(len(sel)))
	default:
		return fmt.Errorf("modo desconocido %q", mode)
	}
	el := time.Since(t0).Seconds()
	if outCSV != "" {
		f, err := os.OpenFile(outCSV, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			return fmt.Errorf("abriendo %s: %w", outCSV, err)
		}
		cw := csv.NewWriter(f)
		for _, s := range all {
			cw.Write([]string{engine, tag, mode, strconv.Itoa(conc), strconv.Itoa(procs), s.q, strconv.Itoa(s.seq),
				strconv.FormatInt(s.us, 10), strconv.Itoa(s.rows), s.err})
		}
		cw.Flush()
		f.Close()
	}
	sum := runSummary{Engine: engine, Tag: tag, Mode: mode, Conc: conc, Procs: procs, Seconds: el, When: time.Now().UTC()}
	byQ := map[string][]sample{}
	for _, s := range all {
		byQ[s.q] = append(byQ[s.q], s)
	}
	for _, q := range sel {
		ss := byQ[q.Name]
		st := qstats{Query: q.Name}
		var lat []float64
		var rows float64
		var first, last time.Time
		for _, s := range ss {
			st.N++
			if s.err != "" {
				st.Errors++
				if st.Err1 == "" {
					st.Err1 = s.err
				}
				continue
			}
			ms := float64(s.us) / 1000
			lat = append(lat, ms)
			rows += float64(s.rows)
			if first.IsZero() || s.start.Before(first) {
				first = s.start
			}
			if e := s.start.Add(time.Duration(s.us) * time.Microsecond); e.After(last) {
				last = e
			}
		}
		sort.Float64s(lat)
		if len(lat) > 0 {
			st.P50, st.P95, st.P99, st.Max = pct(lat, 50), pct(lat, 95), pct(lat, 99), lat[len(lat)-1]
			tot := 0.0
			for _, x := range lat {
				tot += x
			}
			st.Mean = tot / float64(len(lat))
			st.Rows = rows / float64(len(lat))
			if mode == "warm" && last.After(first) {
				st.QPS = float64(len(lat)) / last.Sub(first).Seconds()
			}
		}
		sum.Stats = append(sum.Stats, st)
		fmt.Printf("%-9s %-5s c=%-2d %-28s n=%-5d err=%-3d p50=%8.2f p95=%8.2f p99=%8.2f max=%8.2f filas=%.1f qps=%.0f\n",
			engine, mode, conc, q.Name, st.N, st.Errors, st.P50, st.P95, st.P99, st.Max, st.Rows, st.QPS)
		if st.Err1 != "" {
			fmt.Printf("    primer error: %s\n", st.Err1)
		}
	}
	if outJSON != "" {
		var prev []runSummary
		if b, err := os.ReadFile(outJSON); err == nil {
			_ = json.Unmarshal(b, &prev)
		}
		prev = append(prev, sum)
		b, _ := json.MarshalIndent(prev, "", "  ")
		if err := os.WriteFile(outJSON, b, 0o644); err != nil {
			return fmt.Errorf("escribiendo %s: %w", outJSON, err)
		}
	}
	return nil
}

// explain: plan de cada consulta (PROFILE no; solo EXPLAIN, sin ejecutar).
func explain(ctx context.Context, drv neo4j.DriverWithContext, w *world, procs int) error {
	s := drv.NewSession(ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeRead})
	defer s.Close(ctx)
	for i := range queries {
		q := &queries[i]
		r := rand.New(rand.NewPCG(w.seed, seedFor(q.Name, "explain")))
		res, err := s.Run(ctx, "EXPLAIN "+q.Text, q.Param(w, r, procs))
		if err != nil {
			return fmt.Errorf("explain %s: %w", q.Name, err)
		}
		recs, err := res.Collect(ctx)
		if err != nil {
			return fmt.Errorf("explain %s: %w", q.Name, err)
		}
		fmt.Printf("== %s\n", q.Name)
		for _, rec := range recs { // Memgraph devuelve el plan como filas
			fmt.Println("  ", rec.Values...)
		}
		if sm, err := res.Consume(ctx); err == nil && sm.Plan() != nil {
			printPlan(sm.Plan(), 1)
		}
	}
	return nil
}

func printPlan(p neo4j.Plan, depth int) {
	fmt.Printf("%s%s %v\n", strings.Repeat("  ", depth), p.Operator(), p.Arguments()["Details"])
	for _, c := range p.Children() {
		printPlan(c, depth+1)
	}
}
