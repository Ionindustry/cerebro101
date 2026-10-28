package ingestor

import (
	"archive/zip"
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

func labels(items []Item) []string {
	var out []string
	for _, it := range items {
		out = append(out, it.Label)
	}
	return out
}

func fecha(s string) time.Time {
	t, err := time.Parse("2006-01-02", s)
	if err != nil {
		panic(err)
	}
	return t
}

func TestPlanDelHistorico(t *testing.T) {
	casos := []struct {
		ahora, desde string
		want         []string
	}{
		// Los meses cerrados del año en curso (de más reciente a más antiguo) y después los años completos.
		{"2026-10-28", "2024-01-01", []string{"202609", "202608", "202607", "202606", "202605", "202604", "202603", "202602", "202601", "2025", "2024"}},
		{"2026-10-28", "2026-07-01", []string{"202609", "202608", "202607"}},
		{"2026-10-28", "2025-11-01", []string{"202609", "202608", "202607", "202606", "202605", "202604", "202603", "202602", "202601", "2025"}},
		{"2026-01-15", "2025-01-01", []string{"2025"}}, // en enero no hay meses cerrados del año en curso
		{"2026-10-28", "2026-10-01", nil}, // el mes en curso lo cubre la sindicación en vivo
	}
	for _, c := range casos {
		if got := labels(Plan(fecha(c.ahora), fecha(c.desde))); !slices.Equal(got, c.want) {
			t.Fatalf("%s desde %s: %v, quería %v", c.ahora, c.desde, got, c.want)
		}
	}
}

func TestParseSince(t *testing.T) {
	ahora := fecha("2026-10-28")
	if got, err := ParseSince("2023", ahora); err != nil || !got.Equal(fecha("2023-01-01")) {
		t.Fatalf("%v %v", got, err)
	}
	if got, err := ParseSince(" 2024-06 ", ahora); err != nil || !got.Equal(fecha("2024-06-01")) {
		t.Fatalf("%v %v", got, err)
	}
	for _, mal := range []string{"ayer", "2023-13", "2011", "2027", "23"} {
		if _, err := ParseSince(mal, ahora); err == nil || !strings.Contains(err.Error(), EnvHistoricoDesde) {
			t.Fatalf("%q: err = %v", mal, err)
		}
	}
}

func TestConfigDelHistorico(t *testing.T) {
	m := base()
	if c, err := FromEnv(env(m)); err != nil || c.Historico != nil {
		t.Fatalf("sin variable no debe haber histórico: %+v %v", c.Historico, err)
	}
	m[EnvHistoricoDesde], m[EnvHistoricoDir], m[EnvTimeoutZip] = "2024-03", "/scratch", "2h"
	c, err := FromEnv(env(m))
	if err != nil || c.Historico == nil || c.Historico.Dir != "/scratch" || c.Historico.Timeout != 2*time.Hour || !c.Historico.Since.Equal(fecha("2024-03-01")) {
		t.Fatalf("config = %+v err=%v", c.Historico, err)
	}
	for nombre, cambio := range map[string]map[string]string{
		"desde":        {EnvHistoricoDesde: "mañana"},
		"timeout":      {EnvTimeoutZip: "5s"},
		"timeout raro": {EnvTimeoutZip: "mucho"},
	} {
		m := base()
		m[EnvHistoricoDesde] = "2024"
		for k, v := range cambio {
			m[k] = v
		}
		if _, err := FromEnv(env(m)); err == nil {
			t.Fatalf("%s: esperaba error", nombre)
		}
	}
}

// fakeDL sirve ZIP por dirección. Lo que no está responde 404; fallos fuerza un error de red en la primera descarga de esa dirección.
type fakeDL struct {
	zips    map[string][]byte
	fallos  map[string]bool
	llamado []string
}

func (f *fakeDL) Download(_ context.Context, url, path string, _ fetch.DownloadOptions) (int64, error) {
	f.llamado = append(f.llamado, url)
	b, ok := f.zips[url]
	if !ok {
		return 0, fetch.ErrNotFound
	}
	if f.fallos[url] {
		delete(f.fallos, url)
		_ = os.WriteFile(path, b[:len(b)/2], 0o600) // queda a medias, como una descarga cortada
		return int64(len(b) / 2), errors.New("fetch: conexión cortada")
	}
	return int64(len(b)), os.WriteFile(path, b, 0o600)
}

func zipDe(t *testing.T, ficheros map[string][]byte) []byte {
	t.Helper()
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for n, c := range ficheros {
		w, _ := zw.Create(n)
		_, _ = w.Write(c)
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func urlZip(host, label string) string {
	return fmt.Sprintf("https://%s/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3_%s.zip", host, label)
}

func nuevoHistorico(t *testing.T, dl Downloader, desde, ahora string) (*Historico, *ingest.MemState) {
	t.Helper()
	st := ingest.NewMemState()
	d := ingest.Deps{Raw: ingest.NewMemRaw(), State: st}
	return &Historico{
		Source: domain.SourcePLACSP643, Deps: d, DL: dl, Now: func() time.Time { return fecha(ahora) },
		Cfg: HistoricoConfig{Since: fecha(desde), Dir: filepath.Join(t.TempDir(), "trabajo"), Timeout: time.Minute},
	}, st
}

func muestra(t *testing.T) []byte {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("..", "..", "testdata", "placsp_643", "extracto_licitacionesPerfilesContratanteCompleto3_20261025_200314.atom"))
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestHistoricoCargaUnZipPorVueltaDelMasRecienteAlMasAntiguo(t *testing.T) {
	a := muestra(t)
	h1, h2 := zipHosts[0], zipHosts[1]
	dl := &fakeDL{zips: map[string][]byte{
		urlZip(h1, "202609"): zipDe(t, map[string][]byte{"p.atom": a}),
		urlZip(h2, "202608"): zipDe(t, map[string][]byte{"p.atom": a}), // el primer servidor da 404 y el segundo lo tiene
	}}
	h, st := nuevoHistorico(t, dl, "2026-08-01", "2026-10-28")

	pend, err := h.Step(context.Background())
	if err != nil || !pend {
		t.Fatalf("1.ª vuelta: pending=%v err=%v", pend, err)
	}
	if len(st.Events()) == 0 {
		t.Fatal("no se ingirió nada")
	}
	pend, err = h.Step(context.Background())
	if err != nil || !pend {
		t.Fatalf("2.ª vuelta: pending=%v err=%v", pend, err)
	}
	if want := []string{urlZip(h1, "202609"), urlZip(h1, "202608"), urlZip(h2, "202608")}; !slices.Equal(dl.llamado, want) {
		t.Fatalf("descargas = %v", dl.llamado)
	}
	// Ya está todo lo que existe (el ZIP de julio no está publicado): ni pendiente ni error, y no vuelve a bajar lo hecho.
	pend, err = h.Step(context.Background())
	if err != nil || pend {
		t.Fatalf("3.ª vuelta: pending=%v err=%v", pend, err)
	}
	for _, u := range dl.llamado {
		if strings.Contains(u, "202609") && u != dl.llamado[0] {
			t.Fatalf("volvió a bajar un ZIP ya cargado: %v", dl.llamado)
		}
	}
	if left, _ := os.ReadDir(h.Cfg.Dir); len(left) != 0 {
		t.Fatalf("quedaron ficheros en la carpeta de trabajo: %v", left)
	}
}

func TestHistoricoTrasUnFalloDeRedContinuaYNoDuplica(t *testing.T) {
	u := urlZip(zipHosts[0], "202609")
	dl := &fakeDL{zips: map[string][]byte{u: zipDe(t, map[string][]byte{"p.atom": muestra(t)})}, fallos: map[string]bool{u: true}}
	h, st := nuevoHistorico(t, dl, "2026-09-01", "2026-10-28")
	if _, err := h.Step(context.Background()); err == nil {
		t.Fatal("esperaba el fallo de red")
	}
	if _, err := os.Stat(filepath.Join(h.Cfg.Dir, domain.SourcePLACSP643+"_202609.zip.part")); err != nil {
		t.Fatal("la descarga a medias debe conservarse para continuarla")
	}
	if _, err := h.Step(context.Background()); err != nil {
		t.Fatal(err)
	}
	n := len(st.Events())
	if n == 0 {
		t.Fatal("no se ingirió nada")
	}
	if pend, err := h.Step(context.Background()); err != nil || pend || len(st.Events()) != n {
		t.Fatalf("pending=%v err=%v eventos=%d→%d", pend, err, n, len(st.Events()))
	}
}

func TestHistoricoUnZipCorruptoSeDescartaYSeVuelveAPedir(t *testing.T) {
	u := urlZip(zipHosts[0], "202609")
	dl := &fakeDL{zips: map[string][]byte{u: append([]byte("PK\x03\x04"), []byte("no es de verdad")...)}}
	h, _ := nuevoHistorico(t, dl, "2026-09-01", "2026-10-28")
	if _, err := h.Step(context.Background()); err == nil {
		t.Fatal("esperaba error")
	}
	if left, _ := os.ReadDir(h.Cfg.Dir); len(left) != 0 {
		t.Fatalf("el ZIP corrupto debe borrarse: %v", left)
	}
	// Una página web de error servida como si fuera el ZIP tampoco se acepta.
	dl.zips[u] = []byte("<html>error</html>")
	if _, err := h.Step(context.Background()); err == nil {
		t.Fatal("esperaba error con un HTML")
	}
}

func TestHistoricoFuenteSinZipNoHaceNada(t *testing.T) {
	h, _ := nuevoHistorico(t, &fakeDL{}, "2024-01-01", "2026-10-28")
	h.Source = domain.SourcePLACSP1044
	if pend, err := h.Step(context.Background()); pend || err != nil {
		t.Fatalf("pending=%v err=%v", pend, err)
	}
}
