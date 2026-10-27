package projector

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/nats-io/nats-server/v2/server"

	"github.com/ionindustry/cerebro101/licitaciones/internal/bus"
	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/placsp"
	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingestor"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

const muestra = "../../testdata/placsp_643/extracto_licitacionesPerfilesContratanteCompleto3_20261025_200314.atom"

type memRaw map[string][]byte

func (m memRaw) GetRaw(_ context.Context, k string) ([]byte, error) {
	if b, ok := m[k]; ok {
		return b, nil
	}
	return nil, errors.New("no existe")
}

type fakeSink struct {
	altas, bajas []string
}

func (f *fakeSink) UpsertExpediente(_ context.Context, _ ingest.Event, l *domain.Licitacion) (bool, error) {
	f.altas = append(f.altas, l.SourceID)
	return true, nil
}

func (f *fakeSink) AnularExpediente(_ context.Context, _ ingest.Event, b *domain.Baja) (bool, error) {
	f.bajas = append(f.bajas, b.Ref)
	return true, nil
}

func sha(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }

func entradasDeLaMuestra(t *testing.T) []placsp.Record {
	t.Helper()
	b, err := os.ReadFile(muestra)
	if err != nil {
		t.Fatal(err)
	}
	var recs []placsp.Record
	if _, err := placsp.ParseFeed(bytes.NewReader(b), placsp.Options{Source: "placsp-643"}, func(r placsp.Record) error { recs = append(recs, r); return nil }); err != nil {
		t.Fatal(err)
	}
	return recs
}

func TestHandleProyectaLicitacionesYBajas(t *testing.T) {
	raw, sink := memRaw{}, &fakeSink{}
	var altas, bajas int
	for i, r := range entradasDeLaMuestra(t) {
		key := fmt.Sprintf("k%d", i)
		raw[key] = r.Raw
		ev := ingest.Event{Source: "placsp-643", Version: 1, RawKey: key, RawSHA256: r.RawSHA256}
		if _, err := Handle(context.Background(), raw, sink, ev); err != nil {
			t.Fatalf("entrada %d: %v", i, err)
		}
		if r.Baja != nil {
			bajas++
		} else {
			altas++
		}
	}
	if len(sink.altas) != altas || len(sink.bajas) != bajas || altas == 0 {
		t.Fatalf("altas %d/%d, bajas %d/%d", len(sink.altas), altas, len(sink.bajas), bajas)
	}
}

func TestHandleDistingueLoPermanenteDeLoTransitorio(t *testing.T) {
	bueno := entradasDeLaMuestra(t)[1].Raw
	sink := &fakeSink{}
	// El almacén no responde: transitorio (se reintenta).
	_, err := Handle(context.Background(), memRaw{}, sink, ingest.Event{Source: "placsp-643", RawKey: "falta", RawSHA256: sha(bueno)})
	if err == nil || errors.Is(err, bus.ErrPermanent) {
		t.Fatalf("un original que no se puede leer debe ser transitorio: %v", err)
	}
	// El original no coincide con su hash: permanente (evidencia alterada).
	_, err = Handle(context.Background(), memRaw{"k": bueno}, sink, ingest.Event{Source: "placsp-643", RawKey: "k", RawSHA256: "00"})
	if !errors.Is(err, bus.ErrPermanent) {
		t.Fatalf("un SHA-256 distinto debe ser permanente: %v", err)
	}
	// El original no es una entrada legible: permanente.
	roto := []byte("<entry><id>")
	_, err = Handle(context.Background(), memRaw{"k": roto}, sink, ingest.Event{Source: "placsp-643", RawKey: "k", RawSHA256: sha(roto)})
	if !errors.Is(err, bus.ErrPermanent) {
		t.Fatalf("un XML roto debe ser permanente: %v", err)
	}
	if len(sink.altas)+len(sink.bajas) != 0 {
		t.Fatal("no debe proyectarse nada de un original dudoso")
	}
}

type fetcher struct{ body []byte }

func (f fetcher) Fetch(_ context.Context, url string, _ fetch.Validators) (fetch.Result, error) {
	b := []byte(`<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><id>x</id></feed>`)
	if url == ingestor.Catalog["placsp-643"] {
		b = f.body
	}
	return fetch.Result{URL: url, Body: b, FetchedAt: time.Now()}, nil
}

// TestDeLaFuenteAlModeloDeLectura recorre todo: la ingesta de la muestra real deja originales y eventos; el relay los publica; el proyector
// los consume, y el modelo de lectura queda con un expediente por licitación de la muestra. Necesita LICITACIONES_TEST_PG.
func TestDeLaFuenteAlModeloDeLectura(t *testing.T) {
	pgURL := os.Getenv("LICITACIONES_TEST_PG")
	if pgURL == "" {
		t.Skip("sin LICITACIONES_TEST_PG")
	}
	body, err := os.ReadFile(muestra)
	if err != nil {
		t.Fatal(err)
	}
	esperadas := map[string]bool{}
	for _, r := range entradasDeLaMuestra(t) {
		if r.Licitacion != nil {
			esperadas[r.Licitacion.SourceID] = true
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()

	admin, err := pg.Connect(ctx, pgURL)
	if err != nil {
		t.Fatal(err)
	}
	schema := fmt.Sprintf("lic_proj_%d", time.Now().UnixNano())
	if _, err := admin.Exec(ctx, "CREATE SCHEMA "+schema); err != nil {
		t.Fatal(err)
	}
	cfg, _ := pgxpool.ParseConfig(pgURL)
	cfg.ConnConfig.RuntimeParams["search_path"] = schema
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		pool.Close()
		_, _ = admin.Exec(context.Background(), "DROP SCHEMA "+schema+" CASCADE")
		admin.Close()
	})
	if err := pg.Migrate(ctx, pool); err != nil {
		t.Fatal(err)
	}
	st := pg.New(pool)

	srv, err := server.NewServer(&server.Options{Port: -1, JetStream: true, JetStreamMaxStore: 8 << 30, StoreDir: t.TempDir(), NoLog: true, NoSigs: true})
	if err != nil {
		t.Fatal(err)
	}
	go srv.Start()
	if !srv.ReadyForConnections(10 * time.Second) {
		t.Fatal("NATS no arrancó")
	}
	t.Cleanup(srv.Shutdown)
	nc, err := bus.Connect(bus.Config{URL: srv.ClientURL()})
	if err != nil {
		t.Fatal(err)
	}
	defer nc.Close()
	pub, _ := bus.NewPublisher(nc)
	if err := pub.EnsureStream(ctx); err != nil {
		t.Fatal(err)
	}

	raw := ingest.NewMemRaw()
	wctx, stop := context.WithCancel(ctx)
	defer stop()
	log := slog.New(slog.DiscardHandler)
	go func() { // ingesta + relay
		_ = ingestor.Work(wctx, ingest.Deps{Fetcher: fetcher{body}, Raw: raw, State: st}, st, pub.Publish, ingestor.Config{Sources: []string{"placsp-643"}, Interval: time.Hour, MaxPages: 3}, log)
	}()
	go func() { // proyector
		_ = bus.Consume(wctx, nc, func(ctx context.Context, ev ingest.Event) error {
			_, err := Handle(ctx, raw, st, ev)
			return err
		}, bus.ConsumerOptions{Durable: Durable, Log: log})
	}()

	var n int
	for fin := time.Now().Add(60 * time.Second); time.Now().Before(fin); time.Sleep(200 * time.Millisecond) {
		if n, _ = st.ContarExpedientes(ctx); n >= len(esperadas) {
			break
		}
	}
	if n != len(esperadas) {
		t.Fatalf("expedientes proyectados = %d, quería %d", n, len(esperadas))
	}
	// Cada fila lleva lo esencial.
	var vacios int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM expedientes WHERE titulo = '' OR estado = '' OR clave_original = '' OR documento IS NULL`).Scan(&vacios); err != nil || vacios != 0 {
		t.Fatalf("filas incompletas: %d, %v", vacios, err)
	}
}
