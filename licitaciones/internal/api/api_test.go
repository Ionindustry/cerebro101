package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

const token = "token-de-pruebas-con-al-menos-32-caracteres"

type fakeRepo struct {
	filas  []pg.Fila
	visto  pg.Filtro
	pingEr error

	vistoAdj   pg.FiltroAdjudicaciones
	vistoComp  pg.FiltroCompetidores
	vistoVence pg.FiltroVencimientos
	vistaOrg   pg.FiltroOrganizacion
	sinOrg     bool
}

func (f *fakeRepo) BuscarAdjudicaciones(_ context.Context, fl pg.FiltroAdjudicaciones) ([]pg.Adjudicacion, int, bool, error) {
	f.vistoAdj = fl
	return nil, 0, true, nil
}
func (f *fakeRepo) ContratosQueVencen(_ context.Context, fl pg.FiltroVencimientos) ([]pg.ContratoVence, int, bool, error) {
	f.vistoVence = fl
	return nil, 0, true, nil
}
func (f *fakeRepo) Organizacion(_ context.Context, fl pg.FiltroOrganizacion) (*pg.FichaOrganizacion, error) {
	f.vistaOrg = fl
	if f.sinOrg {
		return nil, pg.ErrOrganizacionSinDatos
	}
	return &pg.FichaOrganizacion{ID: fl.ID, Nombre: "Uno Sistemas SL", NIF: "B11111111", Proveedor: &pg.StatsRol{Contratos: 2, Importe: "300000.0000"}}, nil
}
func (f *fakeRepo) Competidores(_ context.Context, fl pg.FiltroCompetidores) ([]pg.Competidor, int, pg.MuestraMercado, error) {
	f.vistoComp = fl
	return nil, 0, pg.MuestraMercado{}, nil
}

func (f *fakeRepo) Buscar(_ context.Context, fl pg.Filtro) ([]pg.Fila, int, bool, error) {
	f.visto = fl
	return f.filas, len(f.filas), true, nil
}
func (f *fakeRepo) Expediente(context.Context, string) (pg.Fila, error) {
	return pg.Fila{}, pg.ErrNoEncontrado
}
func (f *fakeRepo) Fuentes(context.Context) ([]pg.EstadoFuente, error) { return nil, nil }
func (f *fakeRepo) Ping(context.Context) (time.Duration, error)        { return time.Millisecond, f.pingEr }

func servidor(t *testing.T, repo Repo) (*Server, *httptest.Server) {
	t.Helper()
	s, err := New(repo, token, nil)
	if err != nil {
		t.Fatal(err)
	}
	mux := http.NewServeMux()
	s.Register(mux)
	ts := httptest.NewServer(mux)
	t.Cleanup(ts.Close)
	return s, ts
}

// respuesta es una respuesta HTTP ya leída entera (y cerrada).
type respuesta struct {
	StatusCode int
	Header     http.Header
	Body       []byte
}

func get(t *testing.T, ts *httptest.Server, path, tok string, hdr ...string) respuesta {
	t.Helper()
	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, ts.URL+path, nil)
	if err != nil {
		t.Fatal(err)
	}
	if tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	for i := 0; i+1 < len(hdr); i += 2 {
		req.Header.Set(hdr[i], hdr[i+1])
	}
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	b, err := io.ReadAll(res.Body)
	if err != nil {
		t.Fatal(err)
	}
	return respuesta{StatusCode: res.StatusCode, Header: res.Header, Body: b}
}

func decode(t *testing.T, res respuesta, v any) {
	t.Helper()
	if err := json.Unmarshal(res.Body, v); err != nil {
		t.Fatalf("%v: %s", err, res.Body)
	}
}

func TestSinTokenOConTokenMalo(t *testing.T) {
	_, ts := servidor(t, &fakeRepo{})
	for nombre, tok := range map[string]string{"sin token": "", "token malo": "otro-token-que-no-es-el-bueno-pero-largo", "prefijo": token[:10]} {
		res := get(t, ts, "/api/v1/tenders", tok)
		var p problem
		decode(t, res, &p)
		if res.StatusCode != 401 || p.Codigo != codNoAuth || res.Header.Get("WWW-Authenticate") == "" || res.Header.Get("Content-Type") != "application/problem+json" {
			t.Errorf("%s: %d %+v", nombre, res.StatusCode, p)
		}
	}
	// El token nunca debe aparecer en una respuesta de error.
	res := get(t, ts, "/api/v1/tenders", "x")
	if strings.Contains(string(res.Body), token) {
		t.Fatal("la respuesta contiene el token")
	}
	if res := get(t, ts, "/api/v1/tenders", token); res.StatusCode != 200 {
		t.Fatalf("con token: %d", res.StatusCode)
	}
	if res := get(t, ts, "/api/v1/no-existe", token); res.StatusCode != 404 {
		t.Fatalf("ruta desconocida: %d", res.StatusCode)
	}
	if res := get(t, ts, "/api/v1/no-existe", ""); res.StatusCode != 401 {
		t.Fatalf("ruta desconocida sin token debe pedir autenticación: %d", res.StatusCode)
	}
}

func TestTokenCorto(t *testing.T) {
	if _, err := New(&fakeRepo{}, "corto", nil); err == nil {
		t.Fatal("un token corto debe rechazarse")
	}
}

func TestParametrosInvalidos(t *testing.T) {
	_, ts := servidor(t, &fakeRepo{})
	for _, q := range []string{
		"q=a", "q=" + strings.Repeat("x", 201), "cpv=7", "cpv=72000000x", "nuts=es51", "estado=rara", "procedimiento=x", "fuente=boe", "importe_min=abc",
		"importe_max=1,5", "actualizada_desde=ayer", "orden=relevancia", "orden=encaje", "orden=nada", "limit=0", "limit=101", "limit=x",
		"comprador=0b1f7a3e-1111-2222-3333-444444444444", "desconocido=1", "facetas=cpv", "encaje_min=50", "publicada_desde=2026-01-01T00:00:00Z",
		"cpv=" + strings.Repeat("72,", 21),
		"id_origen=x", "fuente=placsp&fuente=ted&id_origen=x", "fuente=placsp&id_origen=" + strings.Repeat("x", 501), "fuente=placsp&id_origen=a%0Ab",
	} {
		res := get(t, ts, "/api/v1/tenders?"+q, token)
		var p problem
		decode(t, res, &p)
		if res.StatusCode != 400 || p.Codigo != codParametro || len(p.Errores) != 1 {
			t.Errorf("%s: %d %+v", q, res.StatusCode, p)
		}
	}
}

func TestParametrosValidosLlegaranAlFiltro(t *testing.T) {
	repo := &fakeRepo{}
	_, ts := servidor(t, repo)
	res := get(t, ts, "/api/v1/tenders?q=videovigilancia&cpv=72,35125300&nuts=ES512&estado=abierta&estado=cerrada&fuente=placsp&importe_min=1000.50&plazo_hasta=2026-12-01T00:00:00Z&comprador=nif:P1708500E&limit=5&orden=importe", token)
	if res.StatusCode != 200 {
		t.Fatalf("status %d", res.StatusCode)
	}
	f := repo.visto
	if f.Q != "videovigilancia" || len(f.CPV) != 2 || f.NUTS[0] != "ES512" || len(f.Estados) != 2 || f.Fuentes[0] != "placsp-643" || f.ImporteMin != "1000.50" ||
		f.PlazoHasta == nil || f.CompradorNIF[0] != "P1708500E" || f.Limit != 5 || f.Orden != pg.OrdenImporte {
		t.Fatalf("filtro inesperado: %+v", f)
	}
}

func TestIDOrigenLlegaAlFiltro(t *testing.T) {
	repo := &fakeRepo{}
	_, ts := servidor(t, repo)
	res := get(t, ts, "/api/v1/tenders?fuente=placsp&id_origen="+url.QueryEscape("https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/12345"), token)
	if res.StatusCode != 200 || repo.visto.IDOrigen != "https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/12345" || repo.visto.Fuentes[0] != "placsp-643" {
		t.Fatalf("%d %+v", res.StatusCode, repo.visto)
	}
}

func TestOrdenPorDefecto(t *testing.T) {
	repo := &fakeRepo{}
	_, ts := servidor(t, repo)
	get(t, ts, "/api/v1/tenders", token)
	if repo.visto.Orden != pg.OrdenActualizacion || repo.visto.Limit != 20 {
		t.Fatalf("sin texto: %+v", repo.visto)
	}
	get(t, ts, "/api/v1/tenders?q=software", token)
	if repo.visto.Orden != pg.OrdenRelevancia {
		t.Fatalf("con texto debe ordenar por relevancia: %+v", repo.visto)
	}
}

func TestCursorFirmadoLigadoALaConsultaYConCaducidad(t *testing.T) {
	s, _ := servidor(t, &fakeRepo{})
	ahora := time.Date(2026, 10, 27, 12, 0, 0, 0, time.UTC)
	huella := huellaFiltros(map[string][]string{"q": {"a b"}})
	c := encodeCursor(s.cursor, cursorData{K: "k", I: "i", F: huella, E: ahora.Add(time.Hour).Unix()})
	if got, err := decodeCursor(s.cursor, c, huella, ahora); err != nil || got.K != "k" || got.I != "i" {
		t.Fatalf("roundtrip: %+v %v", got, err)
	}
	if _, err := decodeCursor(s.cursor, c, huellaFiltros(map[string][]string{"q": {"otro"}}), ahora); err == nil {
		t.Error("con otros filtros debe fallar")
	}
	if _, err := decodeCursor(s.cursor, c, huella, ahora.Add(2*time.Hour)); err == nil {
		t.Error("caducado debe fallar")
	}
	if _, err := decodeCursor(s.cursor, c[:len(c)-2]+"AA", huella, ahora); err == nil {
		t.Error("firma alterada debe fallar")
	}
	if _, err := decodeCursor([]byte("otra clave"), c, huella, ahora); err == nil {
		t.Error("otra clave debe fallar")
	}
	if huellaFiltros(map[string][]string{"q": {"a"}, "limit": {"5"}, "cursor": {"x"}}) != huellaFiltros(map[string][]string{"q": {"a"}, "limit": {"50"}}) {
		t.Error("limit y cursor no deben cambiar la huella")
	}
}

func TestCursorInvalidoEnLaPeticion(t *testing.T) {
	_, ts := servidor(t, &fakeRepo{})
	res := get(t, ts, "/api/v1/tenders?cursor=basura", token)
	var p problem
	decode(t, res, &p)
	if res.StatusCode != 400 || p.Codigo != codCursor {
		t.Fatalf("%d %+v", res.StatusCode, p)
	}
}

func TestFichaIdInvalidoONoEncontrado(t *testing.T) {
	_, ts := servidor(t, &fakeRepo{})
	for _, id := range []string{"no-es-uuid", "0b1f7a3e-1111-2222-3333-444444444444"} {
		if res := get(t, ts, "/api/v1/tenders/"+id, token); res.StatusCode != 404 {
			t.Errorf("%s: %d", id, res.StatusCode)
		}
	}
}

func TestEstadoConLaBaseCaida(t *testing.T) {
	_, ts := servidor(t, &fakeRepo{pingEr: errors.New("conexión rechazada a 10.0.0.5:5432 con la clave x")})
	res := get(t, ts, "/api/v1/ops/status", token)
	var out struct {
		Estado  string   `json:"estado"`
		Motivos []motivo `json:"motivos"`
	}
	decode(t, res, &out)
	if res.StatusCode != 200 || out.Estado != "caido" || len(out.Motivos) != 1 {
		t.Fatalf("%d %+v", res.StatusCode, out)
	}
	if strings.Contains(string(res.Body), "10.0.0.5") || strings.Contains(string(res.Body), "clave") {
		t.Fatalf("el estado no debe mostrar hosts ni errores crudos: %s", res.Body)
	}
}

func TestTrimDecimalYUUID(t *testing.T) {
	for in, want := range map[string]string{"125000.5000": "125000.50", "100": "100.00", "99.1234": "99.1234", "0.0000": "0.00", "5.5": "5.50"} {
		if got := trimDecimal(in); got != want {
			t.Errorf("trimDecimal(%q) = %q, quería %q", in, got, want)
		}
	}
	a, b := uuid8("org:P1708500E"), uuid8("org:P1708500E")
	if a != b || a == uuid8("org:otro") || !reUUID.MatchString(a) {
		t.Fatalf("uuid8 inestable o mal formado: %s %s", a, b)
	}
}
