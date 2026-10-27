package ingest

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
)

const (
	src      = domain.SourcePLACSP643
	testdata = "../../testdata/placsp_643/"
	inicio   = "https://contrataciondelestado.es/sindicacion/sindicacion_643/inicio.atom"
)

var ahora = time.Date(2026, 10, 27, 12, 0, 0, 0, time.UTC)

// fakeFetcher sirve páginas en memoria: URL → cuerpo. Con etag informado, responde 304 a quien lo presenta.
type fakeFetcher struct {
	paginas  map[string][]byte
	etag     string
	errs     map[string]error
	llamadas []string
}

func (f *fakeFetcher) Fetch(_ context.Context, url string, v fetch.Validators) (fetch.Result, error) {
	f.llamadas = append(f.llamadas, url)
	if err := f.errs[url]; err != nil {
		return fetch.Result{}, err
	}
	if f.etag != "" && v.ETag == f.etag && url == inicio {
		return fetch.Result{URL: url, NotModified: true, FetchedAt: ahora}, nil
	}
	body, ok := f.paginas[url]
	if !ok { // lo que no se ha preparado es una página vacía y sin enlace: fin de la sindicación
		body = []byte(cabecera + `<id>x</id></feed>`)
	}
	return fetch.Result{URL: url, Body: body, FetchedAt: ahora, Validators: fetch.Validators{ETag: f.etag}}, nil
}

func deps(f Fetcher) (Deps, *MemRaw, *MemState) {
	raw, st := NewMemRaw(), NewMemState()
	return Deps{Fetcher: f, Raw: raw, State: st, Now: func() time.Time { return ahora }}, raw, st
}

func leerMuestra(t *testing.T, nombre string) []byte {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(testdata, nombre))
	if err != nil {
		t.Fatal(err)
	}
	return b
}

const cabecera = `<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2" xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2" xmlns:cac-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2" xmlns:cbc-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2" xmlns:at="http://purl.org/atompub/tombstones/1.0">`

// entrada genera una entrada mínima con estado y resultados.
func entrada(id, updated, estado string, resultados ...string) string {
	var rs strings.Builder
	for _, c := range resultados {
		fmt.Fprintf(&rs, `<cac:TenderResult><cbc:ResultCode>%s</cbc:ResultCode><cac:AwardedTenderedProject><cbc:ProcurementProjectLotID>1</cbc:ProcurementProjectLotID></cac:AwardedTenderedProject></cac:TenderResult>`, c)
	}
	return fmt.Sprintf(`<entry><id>https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/%s</id><title>T</title><updated>%s</updated>`+
		`<cac-place-ext:ContractFolderStatus><cbc:ContractFolderID>EXP-%s</cbc:ContractFolderID><cbc-place-ext:ContractFolderStatusCode>%s</cbc-place-ext:ContractFolderStatusCode>%s</cac-place-ext:ContractFolderStatus></entry>`,
		id, updated, id, estado, rs.String())
}

func baja(id, cuando, tipo string) string {
	return fmt.Sprintf(`<at:deleted-entry ref="https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/%s" when="%s"><at:comment type="%s"/></at:deleted-entry>`, id, cuando, tipo)
}

func pagina(partes ...string) []byte { return []byte(cabecera + strings.Join(partes, "") + `</feed>`) }

// observar ingiere una página suelta con el mismo camino que Run.
func observar(t *testing.T, d Deps, body []byte) Stats {
	t.Helper()
	_, st, err := ingestPage(context.Background(), d, src, fetch.Result{URL: inicio, Body: body, FetchedAt: ahora})
	if err != nil {
		t.Fatal(err)
	}
	return st
}

func tipos(st *MemState) []string {
	var out []string
	for _, e := range st.Events() {
		out = append(out, fmt.Sprintf("%s v%d", e.Type, e.Version))
	}
	return out
}

func TestCicloDeVidaDeUnExpediente(t *testing.T) {
	d, raw, st := deps(nil)
	pasos := []struct {
		nombre string
		body   []byte
		kind   func(Stats) int
		evento string
	}{
		{"nueva", pagina(entrada("77", "2026-10-25T10:00:00.000+01:00", "PUB")), func(s Stats) int { return s.New }, "licitacion.nueva v1"},
		{"repetida idéntica", pagina(entrada("77", "2026-10-25T10:00:00.000+01:00", "PUB")), func(s Stats) int { return s.Unchanged }, ""},
		{"solo cambia updated", pagina(entrada("77", "2026-10-25T12:00:00.000+01:00", "PUB")), func(s Stats) int { return s.Unchanged }, ""},
		{"versión anterior", pagina(entrada("77", "2026-10-24T09:00:00.000+01:00", "PUB")), func(s Stats) int { return s.Stale }, ""},
		{"corrección con el mismo updated", pagina(entrada("77", "2026-10-25T12:00:00.000+01:00", "EV")), func(s Stats) int { return s.Modified }, "licitacion.modificada v2"},
		{"adjudicada", pagina(entrada("77", "2026-10-26T08:00:00.000+01:00", "ADJ", "8")), func(s Stats) int { return s.Modified }, "licitacion.adjudicada v3"},
		{"formalizada", pagina(entrada("77", "2026-10-27T08:00:00.000+01:00", "RES", "8", "9")), func(s Stats) int { return s.Modified }, "licitacion.formalizada v4"},
		{"anulada por estado", pagina(entrada("77", "2026-10-27T09:00:00.000+01:00", "ANUL", "8", "9")), func(s Stats) int { return s.Modified }, "licitacion.anulada v5"},
		{"baja de algo ya anulado", pagina(baja("77", "2026-10-27T10:00:00.000+01:00", "ANULADA")), func(s Stats) int { return s.Unchanged }, ""},
		{"baja de algo desconocido", pagina(baja("999", "2026-10-27T10:00:00.000+01:00", "CERRADA")), func(s Stats) int { return s.Unchanged }, ""},
	}
	for _, p := range pasos {
		antes := len(st.Events())
		stats := observar(t, d, p.body)
		if p.kind(stats) != 1 {
			t.Fatalf("%s: estadísticas inesperadas %+v", p.nombre, stats)
		}
		got := ""
		if nuevos := st.Events()[antes:]; len(nuevos) > 0 {
			got = tipos(&MemState{Outbox: nuevos})[0]
		}
		if got != p.evento {
			t.Fatalf("%s: evento = %q, quería %q", p.nombre, got, p.evento)
		}
	}
	if len(st.Events()) != 5 {
		t.Fatalf("eventos = %v", tipos(st))
	}
	if raw.Len() == 0 {
		t.Fatal("no se guardó ningún original")
	}
}

func TestUnaBajaDeUnExpedienteConocidoLoAnula(t *testing.T) {
	d, _, st := deps(nil)
	observar(t, d, pagina(entrada("5", "2026-10-25T10:00:00.000+01:00", "PUB")))
	stats := observar(t, d, pagina(baja("5", "2026-10-26T10:00:00.000+01:00", "CERRADA")))
	if stats.Removed != 1 || stats.Modified != 1 || strings.Join(tipos(st), ",") != "licitacion.nueva v1,licitacion.anulada v2" {
		t.Fatalf("stats = %+v, eventos = %v", stats, tipos(st))
	}
}

func TestRepetirTodoEnUnEstadoNuevoDaLosMismosIdentificadoresDeEvento(t *testing.T) {
	body := pagina(entrada("1", "2026-10-25T10:00:00.000+01:00", "PUB"), entrada("2", "2026-10-25T11:00:00.000+01:00", "ADJ", "8"))
	d1, _, s1 := deps(nil)
	d2, _, s2 := deps(nil)
	observar(t, d1, body)
	observar(t, d2, body)
	a, b := s1.Events(), s2.Events()
	if len(a) != 2 || len(b) != 2 {
		t.Fatalf("eventos = %d y %d", len(a), len(b))
	}
	for i := range a {
		if a[i] != b[i] || a[i].ID == "" {
			t.Fatalf("el evento %d no es determinista: %+v frente a %+v", i, a[i], b[i])
		}
	}
	if a[0].ID == a[1].ID {
		t.Fatal("eventos distintos con el mismo identificador")
	}
}

func TestLosOriginalesSeGuardanConClaveDeterministaYProcedencia(t *testing.T) {
	d, raw, _ := deps(nil)
	observar(t, d, pagina(entrada("77", "2026-10-25T10:00:00.000+01:00", "PUB")))
	var clave string
	for k, o := range raw.Objects {
		if !strings.Contains(k, "/_paginas/") {
			clave = k
			re := regexp.MustCompile(`^placsp-643/2026/10/77/[0-9a-f]{64}\.xml$`)
			if !re.MatchString(k) {
				t.Fatalf("clave inesperada: %s", k)
			}
			if o.Meta["fuente"] != src || o.Meta["url-origen"] != inicio || o.Meta["version-parser"] != ParserVersion || o.Meta["sha256"] != o.SHA256 || o.Meta["capturado-en"] == "" {
				t.Fatalf("metadatos inesperados: %v", o.Meta)
			}
		}
	}
	if clave == "" {
		t.Fatal("no se guardó el original de la entrada")
	}
	if !strings.HasPrefix(PageKey(src, ahora, "abc"), "placsp-643/_paginas/2026/10/27/") {
		t.Fatalf("clave de página inesperada: %s", PageKey(src, ahora, "abc"))
	}
}

func TestClaveConIdentificadorNoSeguro(t *testing.T) {
	for _, id := range []string{"a/b", "..", "con espacio", strings.Repeat("9", 80), ""} {
		k := RawKey(src, id, ahora, "ff")
		if !strings.Contains(k, "/h-") || strings.Count(k, "/") != 4 {
			t.Errorf("RawKey(%q) = %s", id, k)
		}
	}
	if k := RawKey(src, "20757390", ahora, "ff"); k != "placsp-643/2026/10/20757390/ff.xml" {
		t.Fatalf("clave inesperada: %s", k)
	}
}

func TestMemRaw(t *testing.T) {
	m := NewMemRaw()
	o := RawObject{Key: "k", Data: []byte("hola"), SHA256: sha256Hex([]byte("hola"))}
	if c, err := m.PutRaw(context.Background(), o); !c || err != nil {
		t.Fatalf("primera vez: %v %v", c, err)
	}
	if c, err := m.PutRaw(context.Background(), o); c || err != nil {
		t.Fatalf("segunda vez no debe crear: %v %v", c, err)
	}
	otro := RawObject{Key: "k", Data: []byte("adiós"), SHA256: sha256Hex([]byte("adiós"))}
	if _, err := m.PutRaw(context.Background(), otro); err == nil {
		t.Fatal("la misma clave con otro contenido debe fallar")
	}
	if _, err := m.PutRaw(context.Background(), RawObject{Key: "x", Data: []byte("a"), SHA256: "mal"}); err == nil {
		t.Fatal("un SHA-256 que no corresponde debe fallar")
	}
	o.Data[0] = 'X' // la copia guardada no depende del búfer de quien llama
	if string(m.Objects["k"].Data) != "hola" {
		t.Fatal("el almacén debe copiar los bytes")
	}
}

func TestNormalizedHash(t *testing.T) {
	a := &domain.Licitacion{Expediente: "E", Updated: ahora, Warnings: []string{"x"}}
	b := &domain.Licitacion{Expediente: "E", Updated: ahora.Add(time.Hour)}
	c := &domain.Licitacion{Expediente: "F", Updated: ahora}
	ha, _ := NormalizedHash(a)
	hb, _ := NormalizedHash(b)
	hc, _ := NormalizedHash(c)
	if ha != hb || ha == hc || len(ha) != 64 {
		t.Fatalf("hashes: %s %s %s", ha, hb, hc)
	}
}

// Con las muestras reales: primera ingesta completa, segunda con 304, tercera sin validadores (todo conocido).
func TestIngestaDeLaMuestraRealEsIdempotente(t *testing.T) {
	extracto := leerMuestra(t, "extracto_licitacionesPerfilesContratanteCompleto3_20261025_200314.atom")
	completa := leerMuestra(t, "licitacionesPerfilesContratanteCompleto3_20261026T103532Z.atom")
	next := regexp.MustCompile(`<link href="([^"]+)" rel="next"/>`).FindSubmatch(extracto)[1]
	f := &fakeFetcher{paginas: map[string][]byte{inicio: extracto, string(next): completa}, etag: `"v1"`}
	d, raw, st := deps(f)

	s1, err := Run(context.Background(), d, src, inicio, RunOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if s1.Pages != 3 || s1.New == 0 || s1.Entries != 19+68 || s1.Removed != 1 || s1.Warnings != 0 {
		t.Fatalf("primera ingesta: %+v", s1)
	}
	if cp, _ := st.Checkpoint(context.Background(), src); cp.Validators.ETag != `"v1"` || !cp.LastRun.Equal(ahora) {
		t.Fatalf("punto de control inesperado tras la primera ingesta: %+v", cp)
	}
	eventos, originales := len(st.Events()), raw.Len()
	if eventos != s1.New+s1.Modified {
		t.Fatalf("hay %d eventos y %d cambios", eventos, s1.New+s1.Modified)
	}

	// Segunda: el servidor responde 304 a los validadores guardados.
	s2, err := Run(context.Background(), d, src, inicio, RunOptions{})
	if err != nil || !s2.NotModified || s2.Pages != 0 {
		t.Fatalf("segunda ingesta: %+v %v", s2, err)
	}

	// Tercera: sin 304 se descarga la primera página, todo es conocido y se para en ella.
	f.etag = ""
	s3, err := Run(context.Background(), d, src, inicio, RunOptions{})
	if err != nil {
		t.Fatal(err)
	}
	// La sindicación repite entradas con fechas distintas en la misma página: las repetidas más antiguas cuentan como «antigua».
	if s3.Pages != 1 || s3.New != 0 || s3.Modified != 0 || s3.Unchanged+s3.Stale != 19+1 || s3.RawCreated != 0 || s3.RawExisting == 0 {
		t.Fatalf("tercera ingesta: %+v", s3)
	}
	if len(st.Events()) != eventos || raw.Len() != originales {
		t.Fatalf("repetir la ingesta cambió eventos (%d→%d) u originales (%d→%d)", eventos, len(st.Events()), originales, raw.Len())
	}
}

func TestUnaPaginaConNovedadesSigueHaciaAtras(t *testing.T) {
	p2 := pagina(entrada("1", "2026-10-20T10:00:00.000+01:00", "PUB"))
	p1 := pagina(entrada("2", "2026-10-25T10:00:00.000+01:00", "PUB")) // su enlace next se añade abajo
	p1 = bytes.Replace(p1, []byte(`<entry>`), []byte(`<link href="https://contrataciondelestado.es/p2.atom" rel="next"/><entry>`), 1)
	f := &fakeFetcher{paginas: map[string][]byte{inicio: p1, "https://contrataciondelestado.es/p2.atom": p2}}
	d, _, st := deps(f)
	s, err := Run(context.Background(), d, src, inicio, RunOptions{})
	if err != nil || s.Pages != 2 || s.New != 2 || len(st.Events()) != 2 {
		t.Fatalf("stats = %+v, err = %v", s, err)
	}
}

func TestTopeDePaginas(t *testing.T) {
	var sb strings.Builder
	f := &fakeFetcher{paginas: map[string][]byte{}}
	for i := 0; i < 10; i++ {
		url := fmt.Sprintf("https://contrataciondelestado.es/p%d.atom", i)
		sb.Reset()
		fmt.Fprintf(&sb, `<link href="https://contrataciondelestado.es/p%d.atom" rel="next"/>`, i+1)
		sb.WriteString(entrada(fmt.Sprint(100+i), "2026-10-25T10:00:00.000+01:00", "PUB"))
		f.paginas[url] = pagina(sb.String())
	}
	f.paginas[inicio] = pagina(`<link href="https://contrataciondelestado.es/p0.atom" rel="next"/>`, entrada("99", "2026-10-25T10:00:00.000+01:00", "PUB"))
	d, _, _ := deps(f)
	s, err := Run(context.Background(), d, src, inicio, RunOptions{MaxPages: 4})
	if err != nil || s.Pages != 4 {
		t.Fatalf("stats = %+v, err = %v", s, err)
	}
}

func TestUnFalloDeDescargaNoAvanzaElPuntoDeControl(t *testing.T) {
	p1 := bytes.Replace(pagina(entrada("2", "2026-10-25T10:00:00.000+01:00", "PUB")), []byte(`<entry>`),
		[]byte(`<link href="https://contrataciondelestado.es/p2.atom" rel="next"/><entry>`), 1)
	caida := errors.New("caído")
	f := &fakeFetcher{paginas: map[string][]byte{inicio: p1}, etag: `"v2"`, errs: map[string]error{"https://contrataciondelestado.es/p2.atom": caida}}
	d, _, st := deps(f)
	s, err := Run(context.Background(), d, src, inicio, RunOptions{})
	if !errors.Is(err, caida) || s.New != 1 {
		t.Fatalf("stats = %+v, err = %v", s, err)
	}
	if cp, _ := st.Checkpoint(context.Background(), src); !cp.LastRun.IsZero() {
		t.Fatalf("no debe avanzar el punto de control tras un fallo: %+v", cp)
	}
	// La siguiente ejecución, ya recuperado el servidor, repite sin duplicar lo que ya estaba.
	delete(f.errs, "https://contrataciondelestado.es/p2.atom")
	s2, err := Run(context.Background(), d, src, inicio, RunOptions{})
	if err != nil || s2.New != 0 || s2.Unchanged != 1 {
		t.Fatalf("reintento: %+v %v", s2, err)
	}
}

// Regresión: tras un fallo a mitad de camino, la ejecución siguiente debe llegar a las páginas que quedaron sin ingerir aunque la primera
// ya sea conocida (y aunque la fuente responda 304 a los validadores de la ejecución buena anterior).
func TestTrasUnFalloSeRecuperanLasPaginasQueQuedaronAtras(t *testing.T) {
	const p2url = "https://contrataciondelestado.es/p2.atom"
	conNext := func(b []byte) []byte {
		return bytes.Replace(b, []byte(`<entry>`), []byte(`<link href="`+p2url+`" rel="next"/><entry>`), 1)
	}
	f := &fakeFetcher{paginas: map[string][]byte{inicio: pagina(entrada("1", "2026-10-25T10:00:00.000+01:00", "PUB"))}, etag: `"v1"`}
	d, _, st := deps(f)
	if _, err := Run(context.Background(), d, src, inicio, RunOptions{}); err != nil { // ejecución buena: queda punto de control con validadores
		t.Fatal(err)
	}
	// Llegan novedades: la primera página trae una nueva y enlaza a otra con dos más, que se cae al descargarla.
	f.etag = `"v2"`
	f.paginas[inicio] = conNext(pagina(entrada("2", "2026-10-26T10:00:00.000+01:00", "PUB"), entrada("1", "2026-10-25T10:00:00.000+01:00", "PUB")))
	f.paginas[p2url] = pagina(entrada("3", "2026-10-24T10:00:00.000+01:00", "PUB"), entrada("4", "2026-10-23T10:00:00.000+01:00", "PUB"))
	caida := errors.New("tiempo de espera agotado")
	f.errs = map[string]error{p2url: caida}
	if _, err := Run(context.Background(), d, src, inicio, RunOptions{}); !errors.Is(err, caida) {
		t.Fatalf("debía fallar: %v", err)
	}
	if cp, _ := st.Checkpoint(context.Background(), src); !cp.LastRun.IsZero() || cp.Validators.ETag != "" {
		t.Fatalf("tras el fallo el punto de control debe quedar vacío: %+v", cp)
	}
	// Recuperado el servidor, la siguiente ejecución llega a la segunda página y no deja nada atrás.
	delete(f.errs, p2url)
	s, err := Run(context.Background(), d, src, inicio, RunOptions{})
	if err != nil || s.Pages != 2 || s.New != 2 {
		t.Fatalf("recuperación: %+v %v", s, err)
	}
	if n := len(st.Events()); n != 4 {
		t.Fatalf("eventos = %d, quería 4 (uno por expediente)", n)
	}
	// Y ahora sí vuelve a bastar con la primera página.
	s, err = Run(context.Background(), d, src, inicio, RunOptions{})
	if err != nil || !s.NotModified {
		t.Fatalf("ejecución en régimen: %+v %v", s, err)
	}
}

func TestXMLNoValidoEnLaPaginaDevuelveError(t *testing.T) {
	f := &fakeFetcher{paginas: map[string][]byte{inicio: []byte(`<feed><entry>`)}}
	d, _, _ := deps(f)
	if _, err := Run(context.Background(), d, src, inicio, RunOptions{}); err == nil {
		t.Fatal("un XML roto debe devolver error")
	}
}

func TestSinDireccionInicial(t *testing.T) {
	d, _, _ := deps(&fakeFetcher{})
	if _, err := Run(context.Background(), d, src, "", RunOptions{}); !errors.Is(err, ErrNoStartURL) {
		t.Fatalf("error = %v", err)
	}
}
