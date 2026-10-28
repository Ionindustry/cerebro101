package ingest

import (
	"archive/zip"
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
)

const zipURL = "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3_202609.zip"

// hacerZip escribe un ZIP con los ficheros dados (nombre → contenido) en un directorio temporal.
func hacerZip(t *testing.T, ficheros map[string][]byte) string {
	t.Helper()
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for n, c := range ficheros {
		w, err := zw.Create(n)
		if err != nil {
			t.Fatal(err)
		}
		_, _ = w.Write(c)
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	p := filepath.Join(t.TempDir(), "h.zip")
	if err := os.WriteFile(p, buf.Bytes(), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestZipIngiereTodasLasPaginasYLasAnota(t *testing.T) {
	d, raw, st := deps(nil)
	p := hacerZip(t, map[string][]byte{
		"licitacionesPerfilesContratanteCompleto3.atom":   pagina(entrada("1", "2026-09-30T10:00:00.000+02:00", "PUB")),
		"licitacionesPerfilesContratanteCompleto3_1.atom": pagina(entrada("2", "2026-09-29T10:00:00.000+02:00", "PUB"), entrada("3", "2026-09-28T10:00:00.000+02:00", "ADJ", "8")),
		"leeme.txt": []byte("no es una página"),
	})
	got, err := RunZip(context.Background(), d, src, "202609", zipURL, p, ZipLimits{})
	if err != nil {
		t.Fatal(err)
	}
	if got.Pages != 2 || got.New != 3 || got.Entries != 3 {
		t.Fatalf("estadísticas: %+v", got)
	}
	if len(st.Events()) != 3 || raw.Len() == 0 {
		t.Fatalf("eventos=%d originales=%d", len(st.Events()), raw.Len())
	}
	done, _ := st.DonePages(context.Background(), src)
	for _, k := range []string{"zip:202609", "zip:202609/licitacionesPerfilesContratanteCompleto3.atom", "zip:202609/licitacionesPerfilesContratanteCompleto3_1.atom"} {
		if _, ok := done[k]; !ok {
			t.Fatalf("falta anotar %s: %v", k, done)
		}
	}
}

func TestLosEventosDelZipSonDelHistoricoYLosEnVivoNo(t *testing.T) {
	d, _, st := deps(nil)
	p := hacerZip(t, map[string][]byte{"a.atom": pagina(entrada("1", "2026-09-30T10:00:00.000+02:00", "PUB"), entrada("2", "2026-09-29T10:00:00.000+02:00", "ADJ", "8"))})
	if _, err := RunZip(context.Background(), d, src, "202609", zipURL, p, ZipLimits{}); err != nil {
		t.Fatal(err)
	}
	if len(st.Events()) != 2 {
		t.Fatalf("eventos = %d", len(st.Events()))
	}
	for _, e := range st.Events() {
		if !e.Backfill {
			t.Fatalf("un evento del ZIP debe ser del histórico: %+v", e)
		}
	}
	if d.Backfill {
		t.Fatal("RunZip no debe cambiar los Deps de quien lo llama (la ingesta en vivo comparte esos Deps)")
	}
	d2, _, st2 := deps(nil)
	if _, st, err := ingestPage(context.Background(), d2, src, fetch.Result{URL: inicio, Body: pagina(entrada("9", "2026-09-30T10:00:00.000+02:00", "PUB")), FetchedAt: ahora}); err != nil || st.New != 1 {
		t.Fatalf("página en vivo: %+v %v", st, err)
	}
	if ev := st2.Events(); len(ev) != 1 || ev[0].Backfill {
		t.Fatalf("un evento en vivo no es del histórico: %+v", ev)
	}
}

func TestZipRetomaDondeSeQuedoSinRepetirNada(t *testing.T) {
	d, _, st := deps(nil)
	buena := pagina(entrada("1", "2026-09-30T10:00:00.000+02:00", "PUB"))
	rota := []byte("<feed><esto no es xml cerrado")
	p := hacerZip(t, map[string][]byte{"a.atom": buena, "b.atom": rota})
	if _, err := RunZip(context.Background(), d, src, "202609", zipURL, p, ZipLimits{}); err == nil {
		t.Fatal("esperaba un error con la página rota")
	}
	done, _ := st.DonePages(context.Background(), src)
	if _, ok := done["zip:202609/a.atom"]; !ok {
		t.Fatal("la página buena debería estar anotada")
	}
	if _, ok := done["zip:202609"]; ok {
		t.Fatal("el ZIP entero no debe anotarse si falló una página")
	}
	// Se corrige la página rota y se vuelve a ejecutar: solo se ingiere b.atom.
	p = hacerZip(t, map[string][]byte{"a.atom": buena, "b.atom": pagina(entrada("2", "2026-09-29T10:00:00.000+02:00", "PUB"))})
	got, err := RunZip(context.Background(), d, src, "202609", zipURL, p, ZipLimits{})
	if err != nil {
		t.Fatal(err)
	}
	if got.Skipped != 1 || got.Pages != 1 || got.New != 1 || len(st.Events()) != 2 {
		t.Fatalf("estadísticas: %+v eventos=%d", got, len(st.Events()))
	}
}

func TestZipVolverACargarNoDuplicaNada(t *testing.T) {
	d, _, st := deps(nil)
	ficheros := map[string][]byte{"a.atom": pagina(entrada("1", "2026-09-30T10:00:00.000+02:00", "PUB"))}
	for range 2 {
		if _, err := RunZip(context.Background(), d, src, "202609", zipURL, hacerZip(t, ficheros), ZipLimits{}); err != nil {
			t.Fatal(err)
		}
	}
	if len(st.Events()) != 1 {
		t.Fatalf("eventos = %d, quería 1", len(st.Events()))
	}
}

func TestZipConVersionAntiguaNoPisaLaNueva(t *testing.T) {
	d, _, st := deps(nil)
	observar(t, d, pagina(entrada("1", "2026-10-20T10:00:00.000+02:00", "ADJ", "8")))
	got, err := RunZip(context.Background(), d, src, "202609", zipURL,
		hacerZip(t, map[string][]byte{"a.atom": pagina(entrada("1", "2026-09-01T10:00:00.000+02:00", "PUB"))}), ZipLimits{})
	if err != nil {
		t.Fatal(err)
	}
	if got.Stale != 1 || len(st.Events()) != 1 {
		t.Fatalf("estadísticas: %+v eventos=%d", got, len(st.Events()))
	}
}

func TestZipNoValidoOSinPaginas(t *testing.T) {
	d, _, _ := deps(nil)
	p := filepath.Join(t.TempDir(), "x.zip")
	_ = os.WriteFile(p, []byte("esto no es un zip"), 0o600)
	if _, err := RunZip(context.Background(), d, src, "1", zipURL, p, ZipLimits{}); !errors.Is(err, ErrZipInvalid) {
		t.Fatalf("err = %v", err)
	}
	if _, err := RunZip(context.Background(), d, src, "1", zipURL, hacerZip(t, map[string][]byte{"x.txt": []byte("hola")}), ZipLimits{}); !errors.Is(err, ErrZipInvalid) {
		t.Fatalf("sin .atom: err = %v", err)
	}
}

func TestZipLimites(t *testing.T) {
	d, _, _ := deps(nil)
	grande := pagina(entrada("1", "2026-09-30T10:00:00.000+02:00", "PUB"), strings.Repeat("<!-- relleno -->", 1000))
	casos := []struct {
		nombre string
		zip    map[string][]byte
		lim    ZipLimits
	}{
		{"fichero grande", map[string][]byte{"a.atom": grande}, ZipLimits{MaxFileBytes: 1000}},
		{"muchos ficheros", map[string][]byte{"a.atom": pagina(), "b.atom": pagina(), "c.atom": pagina()}, ZipLimits{MaxFiles: 2}},
		{"total", map[string][]byte{"a.atom": grande, "b.atom": grande}, ZipLimits{MaxTotalBytes: int64(len(grande)) + 10}},
	}
	for _, c := range casos {
		if _, err := RunZip(context.Background(), d, src, "1", zipURL, hacerZip(t, c.zip), c.lim); !errors.Is(err, ErrZipTooLarge) {
			t.Fatalf("%s: err = %v", c.nombre, err)
		}
	}
}
