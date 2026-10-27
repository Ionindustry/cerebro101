package main

// Esquema (restricciones de unicidad e índices) y carga por lotes con UNWIND.

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"time"

	"github.com/neo4j/neo4j-go-driver/v5/neo4j"
)

var uniqueKeys = [][2]string{
	{"Procedure", "id"}, {"Lot", "id"}, {"Notice", "id"}, {"NoticeVersion", "id"}, {"Award", "id"},
	{"Organization", "id"}, {"CPV", "code"}, {"Nuts", "code"}, {"Source", "id"},
}

var plainIndexes = [][2]string{
	{"Organization", "nif"}, {"Organization", "dir3"}, {"Procedure", "date"}, {"Award", "end_date"}, {"Award", "fecha"},
}

func schemaStatements(engine string) []string {
	var out []string
	switch engine {
	case "neo4j":
		for _, k := range uniqueKeys {
			out = append(out, fmt.Sprintf("CREATE CONSTRAINT %s_%s_uniq IF NOT EXISTS FOR (n:%s) REQUIRE n.%s IS UNIQUE", k[0], k[1], k[0], k[1]))
		}
		for _, k := range plainIndexes {
			out = append(out, fmt.Sprintf("CREATE INDEX %s_%s_idx IF NOT EXISTS FOR (n:%s) ON (n.%s)", k[0], k[1], k[0], k[1]))
		}
		out = append(out, "CREATE INDEX awarded_fecha_idx IF NOT EXISTS FOR ()-[r:AWARDED_TO]-() ON (r.fecha)")
	case "memgraph":
		// En Memgraph la restricción de unicidad no crea índice: hacen falta los dos.
		for _, k := range uniqueKeys {
			out = append(out, fmt.Sprintf("CREATE INDEX ON :%s(%s)", k[0], k[1]))
			out = append(out, fmt.Sprintf("CREATE CONSTRAINT ON (n:%s) ASSERT n.%s IS UNIQUE", k[0], k[1]))
		}
		for _, k := range plainIndexes {
			out = append(out, fmt.Sprintf("CREATE INDEX ON :%s(%s)", k[0], k[1]))
		}
		out = append(out, "CREATE EDGE INDEX ON :AWARDED_TO(fecha)")
	}
	return out
}

func runSchema(ctx context.Context, drv neo4j.DriverWithContext, engine string) error {
	s := drv.NewSession(ctx, neo4j.SessionConfig{})
	defer s.Close(ctx)
	for _, q := range schemaStatements(engine) {
		t0 := time.Now()
		res, err := s.Run(ctx, q, nil)
		if err == nil {
			_, err = res.Consume(ctx)
		}
		if err != nil {
			return fmt.Errorf("esquema %q: %w", q, err)
		}
		fmt.Printf("esquema %6.0f ms  %s\n", float64(time.Since(t0).Microseconds())/1000, q)
	}
	if engine == "neo4j" {
		res, err := s.Run(ctx, "CALL db.awaitIndexes(600)", nil)
		if err == nil {
			_, err = res.Consume(ctx)
		}
		if err != nil {
			return fmt.Errorf("esperando índices: %w", err)
		}
	}
	return nil
}

// stmt: una sentencia de carga y sus filas.
type stmt struct {
	name  string
	query string
	rel   bool
	rows  []any
}

func nodeQ(label, key string) string {
	return fmt.Sprintf("UNWIND $rows AS r MERGE (n:%s {%s: r.k}) SET n += r.p", label, key)
}

// relQ: modo de carga inicial (CREATE) o idempotente (MERGE).
func relQ(la, ka, typ, lb, kb string, props, merge bool) string {
	verb := "CREATE"
	if merge {
		verb = "MERGE"
	}
	q := fmt.Sprintf("UNWIND $rows AS r MATCH (a:%s {%s: r.a}) MATCH (b:%s {%s: r.b}) %s (a)-[x:%s]->(b)", la, ka, lb, kb, verb, typ)
	if props {
		q += " SET x += r.p"
	}
	return q
}

type loader struct {
	ctx       context.Context
	drv       neo4j.DriverWithContext
	w         *world
	batch     int
	merge     bool // relaciones con MERGE (proyección idempotente)
	nodes     int64
	rels      int64
	perStmtMs map[string]float64
}

func (l *loader) exec(st *stmt) error {
	if len(st.rows) == 0 {
		return nil
	}
	s := l.drv.NewSession(l.ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeWrite})
	defer s.Close(l.ctx)
	t0 := time.Now()
	for i := 0; i < len(st.rows); i += l.batch {
		j := i + l.batch
		if j > len(st.rows) {
			j = len(st.rows)
		}
		res, err := s.Run(l.ctx, st.query, map[string]any{"rows": st.rows[i:j]})
		if err == nil {
			_, err = res.Consume(l.ctx)
		}
		if err != nil {
			return fmt.Errorf("carga %s (filas %d-%d): %w", st.name, i, j, err)
		}
	}
	l.perStmtMs[st.name] += float64(time.Since(t0).Microseconds()) / 1000
	if st.rel {
		l.rels += int64(len(st.rows))
	} else {
		l.nodes += int64(len(st.rows))
	}
	return nil
}

func d(t time.Time) neo4j.Date { return neo4j.DateOf(t) }

func m(kv ...any) map[string]any {
	out := make(map[string]any, len(kv)/2)
	for i := 0; i < len(kv); i += 2 {
		out[kv[i].(string)] = kv[i+1]
	}
	return out
}

func (l *loader) loadStatic() error {
	w := l.w
	src := &stmt{name: "Source", query: nodeQ("Source", "id")}
	for _, s := range sources {
		src.rows = append(src.rows, m("k", s, "p", m("name", s)))
	}
	nuts := &stmt{name: "Nuts", query: nodeQ("Nuts", "code")}
	partOf := &stmt{name: "PART_OF", query: relQ("Nuts", "code", "PART_OF", "Nuts", "code", false, l.merge), rel: true}
	for lvl, list := range [][]nutsEntry{nuts1, nuts2, nuts3} {
		for _, n := range list {
			nuts.rows = append(nuts.rows, m("k", n.Code, "p", m("name", n.Name, "level", lvl+1)))
			if lvl > 0 {
				partOf.rows = append(partOf.rows, m("a", n.Code, "b", n.Code[:len(n.Code)-1]))
			}
		}
	}
	cpv := &stmt{name: "CPV", query: nodeQ("CPV", "code")}
	broader := &stmt{name: "BROADER", query: relQ("CPV", "code", "BROADER", "CPV", "code", false, l.merge), rel: true}
	for _, e := range cpvList {
		cpv.rows = append(cpv.rows, m("k", e.Code, "p", m("name", e.Name, "level", len(significant(e.Code)), "division", e.Code[:2])))
		if p := cpvParent(e.Code, w.cat.cpvSet); p != "" {
			broader.rows = append(broader.rows, m("a", e.Code, "b", p))
		}
	}
	orgs := &stmt{name: "Organization", query: nodeQ("Organization", "id")}
	orgLoc := &stmt{name: "LOCATED_IN(org)", query: relQ("Organization", "id", "LOCATED_IN", "Nuts", "code", false, l.merge), rel: true}
	for _, list := range [][]org{w.buyers, w.firms} {
		for _, o := range list {
			p := m("nif", o.NIF, "name", o.Name, "kind", o.Kind, "type", o.Type)
			if o.DIR3 != "" {
				p["dir3"] = o.DIR3
			}
			orgs.rows = append(orgs.rows, m("k", o.ID, "p", p))
			orgLoc.rows = append(orgLoc.rows, m("a", o.ID, "b", nuts3[o.Nuts3].Code))
		}
	}
	for _, st := range []*stmt{src, nuts, partOf, cpv, broader, orgs, orgLoc} {
		if err := l.exec(st); err != nil {
			return err
		}
	}
	return nil
}

// chunkStatements: sentencias de un bloque de expedientes, en orden (primero nodos, luego relaciones).
func (l *loader) chunkStatements(procs []*procedure) []*stmt {
	w := l.w
	mg := l.merge
	sP := &stmt{name: "Procedure", query: nodeQ("Procedure", "id")}
	sL := &stmt{name: "Lot", query: nodeQ("Lot", "id")}
	sN := &stmt{name: "Notice", query: nodeQ("Notice", "id")}
	sV := &stmt{name: "NoticeVersion", query: nodeQ("NoticeVersion", "id")}
	sA := &stmt{name: "Award", query: nodeQ("Award", "id")}
	rPub := &stmt{name: "PUBLISHED_BY", query: relQ("Procedure", "id", "PUBLISHED_BY", "Organization", "id", false, mg), rel: true}
	rCls := &stmt{name: "CLASSIFIED_AS(proc)", query: relQ("Procedure", "id", "CLASSIFIED_AS", "CPV", "code", false, mg), rel: true}
	rLoc := &stmt{name: "LOCATED_IN(proc)", query: relQ("Procedure", "id", "LOCATED_IN", "Nuts", "code", false, mg), rel: true}
	rSrc := &stmt{name: "DERIVED_FROM(proc)", query: relQ("Procedure", "id", "DERIVED_FROM", "Source", "id", false, mg), rel: true}
	rLot := &stmt{name: "HAS_LOT", query: relQ("Procedure", "id", "HAS_LOT", "Lot", "id", false, mg), rel: true}
	rLCls := &stmt{name: "CLASSIFIED_AS(lot)", query: relQ("Lot", "id", "CLASSIFIED_AS", "CPV", "code", false, mg), rel: true}
	rNot := &stmt{name: "HAS_NOTICE", query: relQ("Procedure", "id", "HAS_NOTICE", "Notice", "id", false, mg), rel: true}
	rVer := &stmt{name: "HAS_VERSION", query: relQ("Notice", "id", "HAS_VERSION", "NoticeVersion", "id", false, mg), rel: true}
	rSup := &stmt{name: "SUPERSEDES", query: relQ("NoticeVersion", "id", "SUPERSEDES", "NoticeVersion", "id", false, mg), rel: true}
	rAw := &stmt{name: "AWARDED_TO", query: relQ("Organization", "id", "AWARDED_TO", "Lot", "id", true, mg), rel: true}
	rRef := &stmt{name: "REFERENCES", query: relQ("Award", "id", "REFERENCES", "Lot", "id", false, mg), rel: true}
	rAN := &stmt{name: "DERIVED_FROM(award)", query: relQ("Award", "id", "DERIVED_FROM", "Notice", "id", false, mg), rel: true}
	rCmp := &stmt{name: "COMPETED_IN", query: relQ("Organization", "id", "COMPETED_IN", "Lot", "id", true, mg), rel: true}
	for _, p := range procs {
		sP.rows = append(sP.rows, m("k", p.ID, "p", m("source", p.Source, "expediente", p.Expediente, "title", p.Title,
			"cpv", p.CPV, "date", d(p.Date), "deadline", d(p.Deadline), "budget", p.Budget, "currency", "EUR",
			"budget_kind", "presupuesto_base_sin_iva", "proc_type", p.ProcType, "status", p.Status)))
		rPub.rows = append(rPub.rows, m("a", p.ID, "b", w.buyers[p.Buyer].ID))
		rCls.rows = append(rCls.rows, m("a", p.ID, "b", p.CPV))
		rLoc.rows = append(rLoc.rows, m("a", p.ID, "b", nuts3[p.Nuts3].Code))
		rSrc.rows = append(rSrc.rows, m("a", p.ID, "b", p.Source))
		for _, lt := range p.Lots {
			sL.rows = append(sL.rows, m("k", lt.ID, "p", m("num", lt.Num, "cpv", lt.CPV, "budget", lt.Budget, "currency", "EUR")))
			rLot.rows = append(rLot.rows, m("a", p.ID, "b", lt.ID))
			rLCls.rows = append(rLCls.rows, m("a", lt.ID, "b", lt.CPV))
			if a := lt.Award; a != nil {
				ap := m("importe", a.Importe, "importe_iva", a.ImporteI, "budget", lt.Budget, "baja", a.Baja,
					"fecha", d(a.Fecha), "end_date", d(a.End), "n_ofertas", a.NOfertas, "currency", "EUR")
				if !a.Formal.IsZero() {
					ap["formalizacion"] = d(a.Formal)
				}
				sA.rows = append(sA.rows, m("k", a.ID, "p", ap))
				rAw.rows = append(rAw.rows, m("a", w.firms[a.Firm].ID, "b", lt.ID,
					"p", m("importe", a.Importe, "baja", a.Baja, "fecha", d(a.Fecha))))
				rRef.rows = append(rRef.rows, m("a", a.ID, "b", lt.ID))
				if p.AwardNotic != "" {
					rAN.rows = append(rAN.rows, m("a", a.ID, "b", p.AwardNotic))
				}
			}
			for _, b := range lt.Bidders {
				rCmp.rows = append(rCmp.rows, m("a", w.firms[b.Firm].ID, "b", lt.ID,
					"p", m("oferta", b.Oferta, "baja", b.Baja, "ganadora", b.Winner)))
			}
		}
		for _, n := range p.Notices {
			sN.rows = append(sN.rows, m("k", n.ID, "p", m("type", n.Type, "date", d(n.Date))))
			rNot.rows = append(rNot.rows, m("a", p.ID, "b", n.ID))
			for i, v := range n.Versions {
				sV.rows = append(sV.rows, m("k", v.ID, "p", m("version", v.N, "published", d(v.Published), "hash", v.Hash)))
				rVer.rows = append(rVer.rows, m("a", n.ID, "b", v.ID))
				if i > 0 {
					rSup.rows = append(rSup.rows, m("a", v.ID, "b", n.Versions[i-1].ID))
				}
			}
		}
	}
	return []*stmt{sP, sL, sN, sV, sA, rPub, rCls, rLoc, rSrc, rLot, rLCls, rNot, rVer, rSup, rAw, rRef, rAN, rCmp}
}

type loadSummary struct {
	Engine    string             `json:"engine"`
	Mode      string             `json:"mode"`
	From      int                `json:"from_procedure"`
	To        int                `json:"to_procedure"`
	Batch     int                `json:"batch_rows"`
	Nodes     int64              `json:"nodes"`
	Rels      int64              `json:"relationships"`
	Seconds   float64            `json:"seconds"`
	PerSecond float64            `json:"nodes_plus_rels_per_second"`
	PerStmtMs map[string]float64 `json:"ms_per_statement"`
}

// runLoad carga [from,to) en bloques; con static=true carga antes los catálogos y las organizaciones.
func runLoad(ctx context.Context, drv neo4j.DriverWithContext, w *world, engine string, from, to, chunk, batch int,
	static, merge bool, outJSON, outCSV string) error {
	l := &loader{ctx: ctx, drv: drv, w: w, batch: batch, merge: merge, perStmtMs: map[string]float64{}}
	t0 := time.Now()
	if static {
		if err := l.loadStatic(); err != nil {
			return err
		}
		fmt.Printf("estáticos: %d nodos, %d relaciones en %.1f s\n", l.nodes, l.rels, time.Since(t0).Seconds())
	}
	var cw *csv.Writer
	if outCSV != "" {
		f, err := os.OpenFile(outCSV, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			return fmt.Errorf("abriendo %s: %w", outCSV, err)
		}
		defer f.Close()
		cw = csv.NewWriter(f)
		defer cw.Flush()
	}
	// generación en paralelo con la carga (un bloque por delante)
	type gen struct {
		end   int
		stmts []*stmt
	}
	ch := make(chan gen, 1)
	go func() {
		defer close(ch)
		for a := from; a < to; a += chunk {
			b := a + chunk
			if b > to {
				b = to
			}
			procs := make([]*procedure, 0, b-a)
			for i := a; i < b; i++ {
				procs = append(procs, w.proc(i))
			}
			select {
			case ch <- gen{end: b, stmts: l.chunkStatements(procs)}:
			case <-ctx.Done():
				return
			}
		}
	}()
	last := time.Now()
	var lastN, lastR int64
	for g := range ch {
		for _, st := range g.stmts {
			if err := l.exec(st); err != nil {
				return err
			}
		}
		now := time.Now()
		dt := now.Sub(last).Seconds()
		rate := float64(l.nodes-lastN+l.rels-lastR) / dt
		if cw != nil {
			cw.Write([]string{engine, strconv.FormatBool(merge), strconv.Itoa(g.end), strconv.FormatInt(l.nodes, 10),
				strconv.FormatInt(l.rels, 10), strconv.FormatFloat(now.Sub(t0).Seconds(), 'f', 2, 64), strconv.FormatFloat(rate, 'f', 0, 64)})
			cw.Flush()
		}
		if (g.end-from)%(chunk*20) == 0 || g.end == to {
			fmt.Printf("%s: expediente %d, %d nodos, %d relaciones, %.0f s, %.0f elem/s (último bloque)\n",
				engine, g.end, l.nodes, l.rels, now.Sub(t0).Seconds(), rate)
		}
		last, lastN, lastR = now, l.nodes, l.rels
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	el := time.Since(t0).Seconds()
	mode := "create"
	if merge {
		mode = "merge"
	}
	sum := loadSummary{Engine: engine, Mode: mode, From: from, To: to, Batch: batch, Nodes: l.nodes, Rels: l.rels,
		Seconds: el, PerSecond: float64(l.nodes+l.rels) / el, PerStmtMs: l.perStmtMs}
	fmt.Printf("TOTAL %s [%d,%d): %d nodos + %d relaciones en %.1f s = %.0f elem/s\n", engine, from, to, l.nodes, l.rels, el, sum.PerSecond)
	if outJSON != "" {
		b, _ := json.MarshalIndent(sum, "", "  ")
		if err := os.WriteFile(outJSON, b, 0o644); err != nil {
			return fmt.Errorf("escribiendo %s: %w", outJSON, err)
		}
	}
	return nil
}
