package pg

import (
	"context"
	"errors"
	"fmt"
	"os"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

// Estas pruebas necesitan un PostgreSQL de pruebas: LICITACIONES_TEST_PG=postgres://usuario:clave@host/base. Sin la variable se omiten.
// Cada prueba trabaja en un esquema propio (search_path), que se borra al terminar.
func conectar(t *testing.T) (*pgxpool.Pool, *Store) {
	t.Helper()
	url := os.Getenv("LICITACIONES_TEST_PG")
	if url == "" {
		t.Skip("sin LICITACIONES_TEST_PG: pruebas de PostgreSQL omitidas")
	}
	ctx := context.Background()
	admin, err := Connect(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	schema := fmt.Sprintf("lic_test_%d_%d", time.Now().UnixNano(), os.Getpid())
	if _, err := admin.Exec(ctx, "CREATE SCHEMA "+schema); err != nil {
		t.Fatal(err)
	}
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		t.Fatal(err)
	}
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
	if err := Migrate(ctx, pool); err != nil {
		t.Fatal(err)
	}
	return pool, New(pool)
}

var t0 = time.Date(2026, 10, 25, 10, 0, 0, 0, time.UTC)

func obs(id, hash string, updated time.Time, flags ingest.Flags) ingest.Observation {
	return ingest.Observation{Source: "placsp-643", SourceID: id, Hash: hash, RawSHA256: "raw-" + hash, RawKey: "clave/" + hash, Updated: updated, Flags: flags}
}

func TestMigrarEsIdempotente(t *testing.T) {
	pool, _ := conectar(t)
	ctx := context.Background()
	if err := Migrate(ctx, pool); err != nil {
		t.Fatalf("segunda vez: %v", err)
	}
	var n int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM schema_migraciones`).Scan(&n); err != nil || n != 1 {
		t.Fatalf("migraciones aplicadas = %d, %v", n, err)
	}
	for _, tabla := range []string{"vistas", "outbox", "puntos_control"} {
		if _, err := pool.Exec(ctx, "SELECT 1 FROM "+tabla); err != nil {
			t.Fatalf("falta la tabla %s: %v", tabla, err)
		}
	}
}

func TestMigrarEnParaleloNoSePisa(t *testing.T) {
	url := os.Getenv("LICITACIONES_TEST_PG")
	if url == "" {
		t.Skip("sin LICITACIONES_TEST_PG")
	}
	pool, _ := conectar(t) // ya migrado: las migraciones simultáneas deben ser inofensivas
	var wg sync.WaitGroup
	errs := make(chan error, 6)
	for i := 0; i < 6; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); errs <- Migrate(context.Background(), pool) }()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
}

// La versión de Postgres y la de memoria deben decidir exactamente igual: se les da la misma secuencia y se comparan.
func TestIgualQueLaVersionEnMemoria(t *testing.T) {
	_, pgStore := conectar(t)
	mem := ingest.NewMemState()
	ctx := context.Background()
	secuencia := []ingest.Observation{
		obs("1", "a", t0, 0),
		obs("1", "a", t0, 0),                 // repetida
		obs("1", "a", t0.Add(time.Hour), 0),  // solo cambia la fecha
		obs("1", "a", t0.Add(-time.Hour), 0), // anterior
		obs("1", "b", t0.Add(time.Hour), 0),  // corrección con el mismo updated
		obs("1", "c", t0.Add(2*time.Hour), ingest.FlagAwarded),
		obs("1", "d", t0.Add(3*time.Hour), ingest.FlagAwarded|ingest.FlagFormalized),
		obs("1", "e", t0.Add(4*time.Hour), ingest.FlagAnnulled),
		{Source: "placsp-643", SourceID: "1", Removed: true, Updated: t0.Add(5 * time.Hour), RawSHA256: "r", RawKey: "k"}, // baja de algo ya anulado
		{Source: "placsp-643", SourceID: "2", Removed: true, Updated: t0, RawSHA256: "r", RawKey: "k"},                    // baja de algo desconocido
		obs("3", "x", t0, 0),
		{Source: "placsp-643", SourceID: "3", Removed: true, Updated: t0.Add(time.Hour), RawSHA256: "r", RawKey: "k"}, // baja de algo conocido
		obs("4", "y", t0, ingest.FlagAwarded),
	}
	for i, o := range secuencia {
		a, err := mem.Observe(ctx, o)
		if err != nil {
			t.Fatal(err)
		}
		b, err := pgStore.Observe(ctx, o)
		if err != nil {
			t.Fatalf("paso %d: %v", i, err)
		}
		if a.Kind != b.Kind || a.Version != b.Version || (a.Event == nil) != (b.Event == nil) || (a.Event != nil && *a.Event != *b.Event) {
			t.Fatalf("paso %d: memoria = %+v, postgres = %+v", i, a, b)
		}
	}
	var n int
	_ = pgStore.pool.QueryRow(ctx, `SELECT count(*) FROM outbox`).Scan(&n)
	if n != len(mem.Events()) || n == 0 {
		t.Fatalf("outbox: postgres %d, memoria %d", n, len(mem.Events()))
	}
}

func TestLaVistaGuardaLoQueDiceElCiclo(t *testing.T) {
	pool, s := conectar(t)
	ctx := context.Background()
	if _, err := s.Observe(ctx, obs("9", "h1", t0, ingest.FlagAwarded)); err != nil {
		t.Fatal(err)
	}
	var version int
	var hash, clave string
	var flags int16
	var upd time.Time
	if err := pool.QueryRow(ctx, `SELECT version_entidad, hash_normalizado, banderas, clave_original, actualizado_origen FROM vistas WHERE id_origen = '9'`).
		Scan(&version, &hash, &flags, &clave, &upd); err != nil {
		t.Fatal(err)
	}
	if version != 1 || hash != "h1" || ingest.Flags(flags) != ingest.FlagAwarded || clave != "clave/h1" || !upd.Equal(t0) {
		t.Fatalf("vista inesperada: %d %s %d %s %v", version, hash, flags, clave, upd)
	}
}

func TestRepetirNoDuplicaElEventoYUnEscritorPerdedorReintenta(t *testing.T) {
	pool, s := conectar(t)
	ctx := context.Background()
	var nuevas, errores atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			out, err := s.Observe(ctx, obs("carrera", "h", t0, 0))
			switch {
			case err != nil:
				errores.Add(1)
			case out.Kind == ingest.KindNew:
				nuevas.Add(1)
			}
		}()
	}
	wg.Wait()
	var eventos int
	_ = pool.QueryRow(ctx, `SELECT count(*) FROM outbox`).Scan(&eventos)
	if nuevas.Load() != 1 || errores.Load() != 0 || eventos != 1 {
		t.Fatalf("nuevas = %d, errores = %d, eventos = %d (esperaba 1, 0, 1)", nuevas.Load(), errores.Load(), eventos)
	}
}

func TestPuntoDeControl(t *testing.T) {
	_, s := conectar(t)
	ctx := context.Background()
	if c, err := s.Checkpoint(ctx, "placsp-643"); err != nil || !c.LastRun.IsZero() {
		t.Fatalf("sin punto de control debe venir vacío: %+v %v", c, err)
	}
	cp := ingest.Checkpoint{LastRun: t0, Validators: fetch.Validators{ETag: `"v1"`, LastModified: "Mon, 26 Oct 2026 10:35:32 GMT"}}
	for i := 0; i < 2; i++ { // guardar dos veces sustituye
		cp.LastRun = t0.Add(time.Duration(i) * time.Hour)
		if err := s.SaveCheckpoint(ctx, "placsp-643", cp); err != nil {
			t.Fatal(err)
		}
	}
	got, err := s.Checkpoint(ctx, "placsp-643")
	if err != nil || !got.LastRun.Equal(t0.Add(time.Hour)) || got.Validators != cp.Validators {
		t.Fatalf("punto de control = %+v, %v", got, err)
	}
	if other, _ := s.Checkpoint(ctx, "placsp-1044"); !other.LastRun.IsZero() {
		t.Fatal("los puntos de control son por fuente")
	}
}

func sembrar(t *testing.T, s *Store, n int) {
	t.Helper()
	for i := 0; i < n; i++ {
		if _, err := s.Observe(context.Background(), obs(fmt.Sprint("e", i), fmt.Sprint("h", i), t0, 0)); err != nil {
			t.Fatal(err)
		}
	}
}

func TestDrainPublicaEnOrdenYBorra(t *testing.T) {
	_, s := conectar(t)
	sembrar(t, s, 5)
	var vistos []string
	n, err := s.Drain(context.Background(), 3, func(_ context.Context, e ingest.Event) error { vistos = append(vistos, e.SourceID); return nil })
	if err != nil || n != 3 || fmt.Sprint(vistos) != "[e0 e1 e2]" {
		t.Fatalf("n = %d, vistos = %v, err = %v", n, vistos, err)
	}
	if c, _, _ := s.Pending(context.Background()); c != 2 {
		t.Fatalf("pendientes = %d, quería 2", c)
	}
	n, err = s.Drain(context.Background(), 10, func(context.Context, ingest.Event) error { return nil })
	if err != nil || n != 2 {
		t.Fatalf("segunda tanda: %d %v", n, err)
	}
	if c, old, _ := s.Pending(context.Background()); c != 0 || old != 0 {
		t.Fatalf("el outbox debe quedar vacío: %d %v", c, old)
	}
}

func TestDrainTrasUnFalloConservaLoPendienteYAnotaElIntento(t *testing.T) {
	pool, s := conectar(t)
	sembrar(t, s, 4)
	caida := errors.New("NATS caído")
	llamadas := 0
	n, err := s.Drain(context.Background(), 10, func(_ context.Context, e ingest.Event) error {
		llamadas++
		if e.SourceID == "e2" {
			return caida
		}
		return nil
	})
	if !errors.Is(err, caida) || n != 2 || llamadas != 3 {
		t.Fatalf("n = %d, llamadas = %d, err = %v", n, llamadas, err)
	}
	var restantes, intentos int
	_ = pool.QueryRow(context.Background(), `SELECT count(*), COALESCE(max(intentos), 0) FROM outbox`).Scan(&restantes, &intentos)
	if restantes != 2 || intentos != 1 {
		t.Fatalf("quedan %d eventos con %d intentos; esperaba 2 y 1", restantes, intentos)
	}
	// Recuperado el destino, salen los que faltaban, empezando por el que falló.
	var vistos []string
	if _, err := s.Drain(context.Background(), 10, func(_ context.Context, e ingest.Event) error { vistos = append(vistos, e.SourceID); return nil }); err != nil || fmt.Sprint(vistos) != "[e2 e3]" {
		t.Fatalf("reintento: %v %v", vistos, err)
	}
}

func TestDosDrainSimultaneosNoPublicanLoMismo(t *testing.T) {
	_, s := conectar(t)
	sembrar(t, s, 6)
	ctx := context.Background()
	enCurso := make(chan struct{})
	soltar := make(chan struct{})
	var mu sync.Mutex
	vistos := map[string]int{}
	registrar := func(e ingest.Event) { mu.Lock(); vistos[e.ID]++; mu.Unlock() }

	hecho := make(chan struct{})
	go func() {
		defer close(hecho)
		_, _ = s.Drain(ctx, 3, func(_ context.Context, e ingest.Event) error {
			registrar(e)
			select {
			case enCurso <- struct{}{}:
			default:
			}
			<-soltar // el primero se queda con sus 3 eventos bloqueados
			return nil
		})
	}()
	<-enCurso
	if _, err := s.Drain(ctx, 10, func(_ context.Context, e ingest.Event) error { registrar(e); return nil }); err != nil {
		t.Fatal(err)
	}
	close(soltar)
	<-hecho
	if len(vistos) != 6 {
		t.Fatalf("eventos distintos publicados = %d, quería 6", len(vistos))
	}
	for id, n := range vistos {
		if n != 1 {
			t.Fatalf("el evento %s se publicó %d veces", id, n)
		}
	}
}

func TestPendingSinEventos(t *testing.T) {
	_, s := conectar(t)
	if c, old, err := s.Pending(context.Background()); err != nil || c != 0 || old != 0 {
		t.Fatalf("%d %v %v", c, old, err)
	}
}

func TestSinBaseEmpiezaConError(t *testing.T) {
	if _, err := Connect(context.Background(), "postgres://nadie:mal@127.0.0.1:1/x?connect_timeout=1"); err == nil {
		t.Fatal("una base inalcanzable debe dar error")
	}
	if _, err := Connect(context.Background(), "esto no es una url"); err == nil {
		t.Fatal("una dirección no válida debe dar error")
	}
}
