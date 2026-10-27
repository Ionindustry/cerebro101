package ingestor

import (
	"context"
	"log/slog"
	"os"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

func TestSoloUnLiderALaVez(t *testing.T) {
	url := os.Getenv("LICITACIONES_TEST_PG")
	if url == "" {
		t.Skip("sin LICITACIONES_TEST_PG")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	pool, err := pg.Connect(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	log := slog.New(slog.DiscardHandler)

	release, err := acquireLeader(ctx, pool, log)
	if err != nil || release == nil {
		t.Fatalf("el primero debía ser líder: %v", err)
	}
	// El segundo espera; al cancelarse vuelve sin cerrojo y sin error.
	wctx, stop := context.WithTimeout(ctx, 500*time.Millisecond)
	defer stop()
	if r2, err := acquireLeader(wctx, pool, log); r2 != nil || err != nil {
		t.Fatalf("el segundo no debía ser líder (r2 nil = %v, err = %v)", r2 == nil, err)
	}
	release()
	r3, err := acquireLeader(ctx, pool, log)
	if err != nil || r3 == nil {
		t.Fatalf("liberado el cerrojo, otro debía poder tomarlo: %v", err)
	}
	r3()
}
