package ingestor

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/nats-io/nats-server/v2/server"
	"github.com/nats-io/nats.go/jetstream"

	"github.com/ionindustry/cerebro101/licitaciones/internal/bus"
	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/s3"
)

// fetcher sirve la muestra real en la primera página de placsp-643 y páginas vacías en las demás.
type fetcher struct{ body []byte }

func (f fetcher) Fetch(_ context.Context, url string, _ fetch.Validators) (fetch.Result, error) {
	b := []byte(`<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><id>x</id></feed>`)
	if url == Catalog["placsp-643"] {
		b = f.body
	}
	return fetch.Result{URL: url, Body: b, FetchedAt: time.Now()}, nil
}

// TestDeLaFuenteAlBus recorre el camino completo con Postgres y NATS reales y, si hay servidor de pruebas, almacén S3 real: la ingesta guarda los originales, deja los
// eventos en el outbox y el relay los publica en JetStream sin dejar nada pendiente. Sin las variables de prueba se omite.
func TestDeLaFuenteAlBus(t *testing.T) {
	pgURL, ep := os.Getenv("LICITACIONES_TEST_PG"), os.Getenv("LICITACIONES_TEST_S3")
	if pgURL == "" {
		t.Skip("sin LICITACIONES_TEST_PG: prueba de extremo a extremo omitida")
	}
	muestra, err := os.ReadFile(filepath.Join("..", "..", "testdata", "placsp_643", "extracto_licitacionesPerfilesContratanteCompleto3_20261025_200314.atom"))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()

	// Postgres, en un esquema propio.
	admin, err := pg.Connect(ctx, pgURL)
	if err != nil {
		t.Fatal(err)
	}
	schema := fmt.Sprintf("lic_e2e_%d", time.Now().UnixNano())
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

	// Almacén de originales: S3 real si hay servidor de pruebas; si no, en memoria.
	var raw ingest.RawStore = ingest.NewMemRaw()
	if ep != "" {
		r, err := s3.New(s3.Config{Endpoint: ep, AccessKey: os.Getenv("LICITACIONES_TEST_S3_USER"), SecretKey: os.Getenv("LICITACIONES_TEST_S3_KEY")})
		if err != nil {
			t.Fatal(err)
		}
		if err := r.EnsureBuckets(ctx); err != nil {
			t.Fatal(err)
		}
		raw = r
	}

	// NATS embebido con JetStream.
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
	pub, err := bus.NewPublisher(nc)
	if err != nil {
		t.Fatal(err)
	}
	if err := pub.EnsureStream(ctx); err != nil {
		t.Fatal(err)
	}

	wctx, stop := context.WithCancel(ctx)
	done := make(chan error, 1)
	c := Config{Sources: []string{"placsp-643"}, Interval: time.Hour, MaxPages: 3}
	go func() {
		done <- Work(wctx, ingest.Deps{Fetcher: fetcher{muestra}, Raw: raw, State: st}, st, pub.Publish, c, slog.New(slog.DiscardHandler))
	}()

	js, _ := jetstream.New(nc)
	stream, err := js.Stream(ctx, bus.StreamName)
	if err != nil {
		t.Fatal(err)
	}
	var msgs uint64
	for deadline := time.Now().Add(60 * time.Second); time.Now().Before(deadline); time.Sleep(200 * time.Millisecond) {
		info, err := stream.Info(ctx)
		if err != nil {
			t.Fatal(err)
		}
		pend, _, _ := st.Pending(ctx)
		if msgs = info.State.Msgs; msgs > 0 && pend == 0 {
			break
		}
	}
	stop()
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	pend, _, err := st.Pending(ctx)
	if err != nil || pend != 0 || msgs == 0 {
		t.Fatalf("mensajes en el bus = %d, pendientes en el outbox = %d, %v", msgs, pend, err)
	}
	t.Logf("%d eventos publicados desde la muestra real", msgs)
}
