package projector

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

func conectarPG(t *testing.T) (*pgxpool.Pool, *pg.Store) {
	t.Helper()
	url := os.Getenv("LICITACIONES_TEST_PG")
	if url == "" {
		t.Skip("sin LICITACIONES_TEST_PG")
	}
	ctx := context.Background()
	admin, err := pg.Connect(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	schema := fmt.Sprintf("lic_repro_%d", time.Now().UnixNano())
	if _, err := admin.Exec(ctx, "CREATE SCHEMA "+schema); err != nil {
		t.Fatal(err)
	}
	cfg, _ := pgxpool.ParseConfig(url)
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
	return pool, pg.New(pool)
}

// proyectada deja en la base todos los expedientes de la muestra (con el parser actual) y devuelve el almacén de sus originales.
func proyectada(t *testing.T, st *pg.Store) memRaw {
	t.Helper()
	raw := memRaw{}
	for i, r := range entradasDeLaMuestra(t) {
		if r.Licitacion == nil {
			continue
		}
		key := fmt.Sprintf("k%d", i)
		raw[key] = r.Raw
		ev := ingest.Event{Source: "placsp-643", SourceID: r.Licitacion.SourceID, Version: 1, RawKey: key, RawSHA256: r.RawSHA256}
		if _, err := Handle(context.Background(), raw, st, ev); err != nil {
			t.Fatal(err)
		}
	}
	return raw
}

func contar(t *testing.T, pool *pgxpool.Pool, sql string) int {
	t.Helper()
	var n int
	if err := pool.QueryRow(context.Background(), sql).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

// Como un expediente proyectado con un parser anterior: se le quita lo que el parser actual añade (la extensión), y la reproyección lo recupera de su original, también
// en las adjudicaciones, que se rehacen solas. Repetirla no cambia nada.
func TestReproyectarRecuperaLoQueElParserAprendioDespues(t *testing.T) {
	pool, st := conectarPG(t)
	ctx := context.Background()
	raw := proyectada(t, st)
	conExtension := contar(t, pool, `SELECT count(*) FROM expedientes WHERE documento ? 'extension'`)
	if conExtension == 0 {
		t.Fatal("la muestra debería tener expedientes con extensión (prórrogas)")
	}
	conPosibles := contar(t, pool, `SELECT count(*) FROM adjudicaciones WHERE prorrogas_posibles IS NOT NULL`)
	// «Parser antiguo»: sin extensión ni en el expediente ni en los lotes.
	if _, err := pool.Exec(ctx, `UPDATE expedientes SET documento = jsonb_set(documento - 'extension', '{lots}',
		coalesce((SELECT jsonb_agg(l - 'extension') FROM jsonb_array_elements(documento -> 'lots') l), '[]'::jsonb))`); err != nil {
		t.Fatal(err)
	}
	if n := contar(t, pool, `SELECT count(*) FROM adjudicaciones WHERE prorrogas_posibles IS NOT NULL`); n != 0 {
		t.Fatalf("sin extensión no hay prórrogas en las adjudicaciones: %d", n)
	}
	total := contar(t, pool, `SELECT count(*) FROM expedientes`)
	log := slog.New(slog.DiscardHandler)

	// Simulación: cuenta pero no escribe.
	r, err := Reproyectar(ctx, raw, st, OpcionesReproyeccion{Simular: true, Pagina: 3}, log)
	if err != nil || !r.Terminado || r.Revisados != total || r.Cambiados == 0 || r.Errores != 0 {
		t.Fatalf("simulación: %v %+v", err, r)
	}
	if n := contar(t, pool, `SELECT count(*) FROM expedientes WHERE documento ? 'extension'`); n != 0 {
		t.Fatalf("la simulación no debe escribir nada: %d con extensión", n)
	}
	cambiarian := r.Cambiados

	// De verdad.
	r, err = Reproyectar(ctx, raw, st, OpcionesReproyeccion{Pagina: 3}, log)
	if err != nil || r.Cambiados != cambiarian || r.Cambiados+r.Iguales != total {
		t.Fatalf("reproyección: %v %+v (en la simulación cambiaban %d de %d)", err, r, cambiarian, total)
	}
	if n := contar(t, pool, `SELECT count(*) FROM expedientes WHERE documento ? 'extension'`); n != conExtension {
		t.Fatalf("expedientes con extensión: %d, antes %d", n, conExtension)
	}
	if n := contar(t, pool, `SELECT count(*) FROM adjudicaciones WHERE prorrogas_posibles IS NOT NULL`); n != conPosibles {
		t.Fatalf("las adjudicaciones se rehacen solas: %d con prórrogas sí/no, antes %d", n, conPosibles)
	}
	// La versión, el original y la fecha de actualización no se tocan.
	if n := contar(t, pool, `SELECT count(*) FROM expedientes WHERE version_entidad <> 1`); n != 0 {
		t.Fatalf("la versión no cambia: %d", n)
	}
	// Idempotente.
	r, err = Reproyectar(ctx, raw, st, OpcionesReproyeccion{}, log)
	if err != nil || r.Cambiados != 0 || r.Iguales != total {
		t.Fatalf("repetir no cambia nada: %v %+v", err, r)
	}
}

func TestReproyectarRespetaLimiteFuenteYContinuacion(t *testing.T) {
	_, st := conectarPG(t)
	raw := proyectada(t, st)
	ctx := context.Background()
	log := slog.New(slog.DiscardHandler)
	r, err := Reproyectar(ctx, raw, st, OpcionesReproyeccion{Limite: 2, Simular: true, Pagina: 1}, log)
	if err != nil || r.Revisados != 2 || r.Terminado || r.UltimoID == "" {
		t.Fatalf("con límite: %v %+v", err, r)
	}
	resto, err := Reproyectar(ctx, raw, st, OpcionesReproyeccion{Despues: r.UltimoID, Simular: true}, log)
	if err != nil || !resto.Terminado {
		t.Fatalf("seguir: %v %+v", err, resto)
	}
	todo, _ := Reproyectar(ctx, raw, st, OpcionesReproyeccion{Simular: true}, log)
	if r.Revisados+resto.Revisados != todo.Revisados {
		t.Fatalf("las dos partes suman el total: %d + %d ≠ %d", r.Revisados, resto.Revisados, todo.Revisados)
	}
	otra, err := Reproyectar(ctx, raw, st, OpcionesReproyeccion{Fuente: "ted", Simular: true}, log)
	if err != nil || otra.Revisados != 0 || !otra.Terminado {
		t.Fatalf("otra fuente: %v %+v", err, otra)
	}
}

// Los originales que no se pueden fiar no se proyectan, los anulados no se resucitan y un cambio que llega mientras tanto no se pisa.
func TestReproyectarNoPisaNiResucitaNiSeFiaDeOriginalesDudosos(t *testing.T) {
	pool, st := conectarPG(t)
	ctx := context.Background()
	raw := proyectada(t, st)
	total := contar(t, pool, `SELECT count(*) FROM expedientes`)
	if _, err := pool.Exec(ctx, `UPDATE expedientes SET documento = documento - 'extension'`); err != nil {
		t.Fatal(err)
	}
	log := slog.New(slog.DiscardHandler)

	// Uno falta en el almacén, a otro le cambian el original: errores, no se tocan.
	var faltante, alterado string
	_ = pool.QueryRow(ctx, `SELECT clave_original FROM expedientes ORDER BY id LIMIT 1`).Scan(&faltante)
	_ = pool.QueryRow(ctx, `SELECT clave_original FROM expedientes ORDER BY id DESC LIMIT 1`).Scan(&alterado)
	delete(raw, faltante)
	raw[alterado] = append([]byte(nil), raw[alterado]...)
	raw[alterado][len(raw[alterado])/2] ^= 0xff
	// Uno anulado después: no se resucita.
	var anulado string
	_ = pool.QueryRow(ctx, `SELECT id_origen FROM expedientes WHERE clave_original NOT IN ($1, $2) ORDER BY id LIMIT 1`, faltante, alterado).Scan(&anulado)
	baja := []byte(`<deleted-entry ref="` + anulado + `" when="2026-10-28T10:00:00Z"><comment type="ANULADA"/></deleted-entry>`)
	raw["baja"] = baja
	if ok, err := st.AnularExpediente(ctx, ingest.Event{Source: "placsp-643", Version: 2, RawSHA256: sha(baja), RawKey: "baja"}, bajaDe(anulado)); err != nil || !ok {
		t.Fatalf("anular: %v %v", ok, err)
	}
	// Y uno al que llega una versión nueva entre el listado y la escritura.
	r, err := Reproyectar(ctx, raw, &conCambioIntermedio{Store: st, pool: pool}, OpcionesReproyeccion{Pagina: 100}, log)
	if err != nil {
		t.Fatal(err)
	}
	// El anulado apunta ya al original de su baja: se reconoce como baja y se deja como está.
	if r.Errores != 2 || r.Bajas != 1 || r.Movidos != 1 || r.Revisados != total {
		t.Fatalf("2 errores (falta y alterado), 1 baja y 1 movido (versión nueva): %+v de %d", r, total)
	}
	if n := contar(t, pool, `SELECT count(*) FROM expedientes WHERE estado = 'anulada'`); n != 1 {
		t.Fatalf("el anulado sigue anulado: %d", n)
	}
	if n := contar(t, pool, `SELECT count(*) FROM expedientes WHERE version_entidad > 1 AND documento ? 'extension'`); n != 0 {
		t.Fatalf("lo que cambió mientras tanto no se pisa con el original viejo: %d", n)
	}
}

// conCambioIntermedio simula que, tras listar los expedientes, llega una versión nueva de uno de ellos (el proyector normal trabaja a la vez).
type conCambioIntermedio struct {
	*pg.Store
	pool  *pgxpool.Pool
	hecho bool
}

func (c *conCambioIntermedio) ExpedientesParaReproyectar(ctx context.Context, fuente, despues string, limite int) ([]pg.FilaReproyeccion, error) {
	filas, err := c.Store.ExpedientesParaReproyectar(ctx, fuente, despues, limite)
	if err == nil && !c.hecho && len(filas) > 2 {
		c.hecho = true
		_, err = c.pool.Exec(ctx, `UPDATE expedientes SET version_entidad = 5, sha256_original = 'otro' WHERE id = $1::uuid`, filas[len(filas)-2].ID)
	}
	return filas, err
}

func bajaDe(ref string) *domain.Baja {
	return &domain.Baja{Source: "placsp-643", Ref: ref, When: time.Now(), Kind: "ANULADA"}
}
