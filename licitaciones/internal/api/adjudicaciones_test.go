package api

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

func TestParametrosDeAdjudicacionesYCompetidores(t *testing.T) {
	repo := &fakeRepo{}
	_, ts := servidor(t, repo)
	malos := []string{
		"/api/v1/awards?area=cctv",                                               // todavía no disponible
		"/api/v1/awards?foo=1",                                                   // desconocido
		"/api/v1/awards?adjudicatario=dir3:L01080193",                            // solo uuid o nif
		"/api/v1/awards?adjudicada_desde=2026-13-45",                             // fecha imposible
		"/api/v1/awards?adjudicada_desde=2026-05-01&adjudicada_hasta=2026-01-01", // desde > hasta
		"/api/v1/awards?resultado=otro",
		"/api/v1/awards?orden=plazo",
		"/api/v1/awards?limit=101",
		"/api/v1/awards?importe_min=abc",
		"/api/v1/competitors",                  // sin acotar el mercado
		"/api/v1/competitors?importe_min=1000", // los importes no acotan
		"/api/v1/competitors?cpv=72&orden=fecha",
		"/api/v1/competitors?cpv=72&q=algo", // q no existe aquí
		"/api/v1/competitors?cpv=7",
	}
	for _, p := range malos {
		if r := get(t, ts, p, token); r.StatusCode != 400 {
			t.Errorf("%s: esperaba 400, llegó %d: %s", p, r.StatusCode, r.Body)
		}
	}
	if r := get(t, ts, "/api/v1/awards?cpv=72&adjudicatario=nif:B12345678,0F1E2D3C-4B5A-6978-8796-A5B4C3D2E1F0&resultado=adjudicado&orden=baja&limit=5&adjudicada_desde=2026-01-01", token); r.StatusCode != 200 {
		t.Fatalf("válida: %d %s", r.StatusCode, r.Body)
	}
	f := repo.vistoAdj
	if len(f.AdjudicatarioClave) != 1 || f.AdjudicatarioClave[0] != "B12345678" || len(f.AdjudicatarioID) != 1 || f.AdjudicatarioID[0] != "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0" ||
		f.Resultado != "adjudicado" || f.Orden != pg.OrdenBaja || f.Limit != 5 || f.Desde != "2026-01-01" || len(f.CPV) != 1 {
		t.Fatalf("filtro mal traducido: %+v", f)
	}
	if r := get(t, ts, "/api/v1/competitors?nuts=ES512&desde=2025-01-01&hasta=2026-01-01&orden=contratos", token); r.StatusCode != 200 {
		t.Fatalf("competidores válida: %d %s", r.StatusCode, r.Body)
	}
	if c := repo.vistoComp; c.Orden != pg.OrdenContratos || c.Desde != "2025-01-01" || c.Hasta != "2026-01-01" || c.Limit != 20 {
		t.Fatalf("filtro de competidores mal traducido: %+v", c)
	}
	if r := get(t, ts, "/api/v1/awards", ""); r.StatusCode != 401 {
		t.Fatalf("sin token: %d", r.StatusCode)
	}
}

type paginaAdj struct {
	Items []struct {
		ID            string   `json:"id"`
		LicitacionID  string   `json:"licitacion_id"`
		Lote          string   `json:"lote"`
		Resultado     string   `json:"resultado"`
		Baja          *float64 `json:"baja"`
		Adjudicatario *struct {
			ID     string  `json:"id"`
			Nombre string  `json:"nombre"`
			NIF    *string `json:"nif"`
		} `json:"adjudicatario"`
		Importes  []Importe        `json:"importes"`
		Comprador *OrganizacionRef `json:"comprador"`
		Evidencia Evidencia        `json:"evidencia"`
	} `json:"items"`
	Sig   *string `json:"siguiente_cursor"`
	Total struct {
		Valor    int    `json:"valor"`
		Relacion string `json:"relacion"`
	} `json:"total"`
}

type paginaComp struct {
	Items []struct {
		Organizacion OrganizacionRef `json:"organizacion"`
		Contratos    int             `json:"contratos_ganados"`
		Importe      Importe         `json:"importe_adjudicado"`
		Cuota        float64         `json:"cuota"`
		BajaMedia    *float64        `json:"baja_media"`
		BajaP50      *float64        `json:"baja_p50"`
		Tendencia    string          `json:"tendencia"`
		Ultima       *string         `json:"ultima_adjudicacion"`
	} `json:"items"`
	Sig   *string `json:"siguiente_cursor"`
	Total struct {
		Valor int `json:"valor"`
	} `json:"total"`
	Muestra struct {
		Adjudicaciones int `json:"adjudicaciones"`
		Desde, Hasta   *string
	} `json:"muestra"`
}

// siembraMercado añade expedientes con adjudicaciones de tres empresas en el CPV 72 (informática):
// W1 gana 3 contratos (100k, 200k y 300k con bajas del 10, 20 y 30 %), W2 gana 2 (100k y 100k) y W3 gana 1 (100k); y un lote desierto.
func siembraMercado(t *testing.T, st *pg.Store) {
	t.Helper()
	ganador := map[string][2]string{"W1": {"B11111111", "Uno Sistemas SL"}, "W2": {"B22222222", "Dos Redes SL"}, "W3": {"A33333333", "Tres Datos SA"}}
	datos := []struct{ quien, presupuesto, adjudicado, fecha string }{
		{"W1", "111111.11", "100000", "2026-09-01"}, {"W1", "250000", "200000", "2026-06-01"}, {"W1", "428571.43", "300000", "2025-02-01"},
		{"W2", "125000", "100000", "2026-08-01"}, {"W2", "100000", "100000", "2025-03-01"},
		{"W3", "100000", "100000", "2026-07-01"},
	}
	base := time.Date(2026, 10, 1, 10, 0, 0, 0, time.UTC)
	ins := func(id string, rs []domain.Result, presupuesto string, n int) {
		l := &domain.Licitacion{Source: "placsp-643", SourceID: id, NumericID: fmt.Sprint(n), Updated: base.Add(time.Duration(n) * time.Minute), Expediente: "M-" + id, Status: "ADJ",
			Title: "Servicio informático " + id, Organism: domain.Organization{Name: "Ayuntamiento de Girona", NIF: "P1708500E"}, Procedure: "1",
			CPV: []string{"72000000"}, NUTS: []string{"ES512"}, Link: "https://x.test/" + id,
			BaseBudgetExclVAT: &domain.Money{Value: presupuesto, Currency: "EUR"}, Results: rs}
		ev := ingest.Event{Source: "placsp-643", SourceID: id, Version: 1, RawSHA256: "ab", RawKey: "k"}
		if _, err := st.UpsertExpediente(context.Background(), ev, l); err != nil {
			t.Fatal(err)
		}
	}
	for i, d := range datos {
		g := ganador[d.quien]
		ins(fmt.Sprintf("mercado/%d", i), []domain.Result{{Code: domain.ResultFormalized, WinnerName: g[1], WinnerID: g[0], WinnerScheme: "NIF",
			AwardedExclVAT: &domain.Money{Value: d.adjudicado, Currency: "EUR"}, AwardDate: domain.Date(d.fecha), TendersReceived: new(int)}}, d.presupuesto, i)
	}
	ins("mercado/desierto", []domain.Result{{LotID: "1", Code: domain.ResultVoid}}, "50000", 99)
}

func getJSON(t *testing.T, ts *httptest.Server, path string, dst any) {
	t.Helper()
	r := get(t, ts, path, token)
	if r.StatusCode != 200 {
		t.Fatalf("%s: %d %s", path, r.StatusCode, r.Body)
	}
	if err := json.Unmarshal(r.Body, dst); err != nil {
		t.Fatalf("%s: %v\n%s", path, err, r.Body)
	}
}

func TestAdjudicacionesConPostgres(t *testing.T) {
	ts, st, pool := conPostgres(t)
	siembraMercado(t, st)

	var todas paginaAdj
	getJSON(t, ts, "/api/v1/awards?cpv=72&limit=100", &todas)
	if todas.Total.Valor != 7 || todas.Total.Relacion != "eq" {
		t.Fatalf("total = %+v (6 adjudicaciones + 1 lote desierto)", todas.Total)
	}
	// Por fecha de adjudicación, la más reciente primero.
	if todas.Items[0].Adjudicatario == nil || todas.Items[0].Adjudicatario.Nombre != "Uno Sistemas SL" {
		t.Fatalf("la más reciente es la de W1 (2026-09-01): %+v", todas.Items[0])
	}
	if b := todas.Items[0].Baja; b == nil || math.Abs(*b-0.1) > 1e-4 {
		t.Fatalf("baja de 100000 sobre 111111.11 = 10 %%: %v", b)
	}

	var des paginaAdj
	getJSON(t, ts, "/api/v1/awards?cpv=72&resultado=desierto", &des)
	if des.Total.Valor != 1 || des.Items[0].Adjudicatario != nil {
		t.Fatalf("el desierto no tiene adjudicatario: %+v", des)
	}
	var w1 paginaAdj
	getJSON(t, ts, "/api/v1/awards?adjudicatario=nif:B11111111&orden=importe", &w1)
	if w1.Total.Valor != 3 || w1.Items[0].Importes[0].Valor != "300000.00" || w1.Items[0].Importes[0].Significado != "adjudicado" {
		t.Fatalf("W1 ordenado por importe: %+v", w1)
	}
	var rango paginaAdj
	getJSON(t, ts, "/api/v1/awards?cpv=72&adjudicada_desde=2026-07-01&adjudicada_hasta=2026-09-30&importe_min=100000", &rango)
	if rango.Total.Valor != 3 {
		t.Fatalf("2026-07 a 2026-09 son W1 (sep), W2 (ago) y W3 (jul): %d", rango.Total.Valor)
	}
	// Por UUID de la organización (el mismo que sale en las respuestas).
	var porID paginaAdj
	getJSON(t, ts, "/api/v1/awards?adjudicatario="+w1.Items[0].Adjudicatario.ID, &porID)
	if porID.Total.Valor != 3 {
		t.Fatalf("por uuid: %d", porID.Total.Valor)
	}

	// Paginación por cursor: de 2 en 2, sin repetir ni saltarse nada, en cada orden.
	for _, orden := range []string{"fecha", "importe", "baja"} {
		vistos := map[string]bool{}
		cursor := ""
		for i := 0; i < 10; i++ {
			q := "/api/v1/awards?cpv=72&limit=2&orden=" + orden
			if cursor != "" {
				q += "&cursor=" + url.QueryEscape(cursor)
			}
			var p paginaAdj
			getJSON(t, ts, q, &p)
			for _, it := range p.Items {
				if vistos[it.ID] {
					t.Fatalf("orden %s: %s repetido", orden, it.ID)
				}
				vistos[it.ID] = true
			}
			if p.Sig == nil {
				break
			}
			cursor = *p.Sig
		}
		if len(vistos) != 7 {
			t.Fatalf("orden %s: vistos %d de 7", orden, len(vistos))
		}
	}
	// Un cursor de otra consulta se rechaza.
	var p paginaAdj
	getJSON(t, ts, "/api/v1/awards?cpv=72&limit=2", &p)
	if r := get(t, ts, "/api/v1/awards?cpv=45&limit=2&cursor="+url.QueryEscape(*p.Sig), token); r.StatusCode != 400 {
		t.Fatalf("cursor de otra consulta: %d", r.StatusCode)
	}

	// Coherencia con la ficha del expediente: mismos identificadores de adjudicación y de adjudicatario.
	var fl Ficha
	getJSON(t, ts, "/api/v1/tenders/"+todas.Items[0].LicitacionID, &fl)
	if len(fl.Adjudicacion) != 1 || fl.Adjudicacion[0].ID != todas.Items[0].ID || fl.Adjudicacion[0].Adjudicatario == nil ||
		fl.Adjudicacion[0].Adjudicatario.ID != todas.Items[0].Adjudicatario.ID {
		t.Fatalf("la ficha y /awards deben coincidir: %+v frente a %+v", fl.Adjudicacion, todas.Items[0])
	}
	// La función SQL y la de Go calculan el mismo UUID.
	for _, nombre := range []string{"org:B11111111", "adj:x|1", "org:n:ana pérez"} {
		var sql string
		if err := pool.QueryRow(context.Background(), `SELECT lic_uuid8($1)::text`, nombre).Scan(&sql); err != nil {
			t.Fatal(err)
		}
		if sql != uuid8(nombre) {
			t.Fatalf("uuid8(%q): SQL %s ≠ Go %s", nombre, sql, uuid8(nombre))
		}
	}
}

func TestCompetidoresConPostgres(t *testing.T) {
	ts, st, _ := conPostgres(t)
	siembraMercado(t, st)

	var p paginaComp
	getJSON(t, ts, "/api/v1/competitors?cpv=72", &p)
	if p.Total.Valor != 3 || len(p.Items) != 3 {
		t.Fatalf("hay 3 competidores: %+v", p)
	}
	// Por importe: W1 (600k), W2 (200k), W3 (100k); mercado total 900k.
	nombres := []string{p.Items[0].Organizacion.Nombre, p.Items[1].Organizacion.Nombre, p.Items[2].Organizacion.Nombre}
	if strings.Join(nombres, "|") != "Uno Sistemas SL|Dos Redes SL|Tres Datos SA" {
		t.Fatalf("orden por importe: %v", nombres)
	}
	w1 := p.Items[0]
	if w1.Contratos != 3 || w1.Importe.Valor != "600000.00" || w1.Importe.Impuestos != "sin_iva" || math.Abs(w1.Cuota-600.0/900.0) > 1e-5 {
		t.Fatalf("W1: %+v", w1)
	}
	if w1.BajaMedia == nil || math.Abs(*w1.BajaMedia-0.2) > 1e-3 || w1.BajaP50 == nil || math.Abs(*w1.BajaP50-0.2) > 1e-3 {
		t.Fatalf("baja de W1 (10, 20 y 30 %%): %v %v", w1.BajaMedia, w1.BajaP50)
	}
	if w1.Ultima == nil || *w1.Ultima != "2026-09-01" || w1.Organizacion.NIF == nil || *w1.Organizacion.NIF != "B11111111" {
		t.Fatalf("W1: %+v", w1)
	}
	// Tendencia: con menos de 3 contratos no hay datos; W1 tiene 3 (2 en los últimos 12 meses y 1 antes... según «hoy»), el resultado depende de la fecha
	// de hoy: solo se comprueba que sea uno de los valores del contrato y que W2 y W3 (menos de 3) no tengan datos.
	if p.Items[1].Tendencia != "sin_datos" || p.Items[2].Tendencia != "sin_datos" {
		t.Fatalf("con menos de 3 contratos, sin datos: %+v", p.Items)
	}
	if p.Muestra.Adjudicaciones != 6 || p.Muestra.Desde == nil || *p.Muestra.Desde != "2025-02-01" || *p.Muestra.Hasta != "2026-09-01" {
		t.Fatalf("muestra: %+v", p.Muestra)
	}
	suma := 0.0
	for _, it := range p.Items {
		suma += it.Cuota
	}
	if math.Abs(suma-1) > 1e-4 {
		t.Fatalf("las cuotas del mercado suman 1: %v", suma)
	}

	// Tendencia determinista fijando «hasta»: a 2026-10-01, W1 tiene 2 contratos en los últimos 12 meses y 1 antes (2025-02-01 queda fuera: más de 24 meses
	// no, pero 20 meses sí → «previos»); sube.
	var t2 paginaComp
	getJSON(t, ts, "/api/v1/competitors?cpv=72&hasta=2026-10-01", &t2)
	if t2.Items[0].Tendencia != "sube" {
		t.Fatalf("W1 pasa de 1 a 2 contratos: %q", t2.Items[0].Tendencia)
	}

	// Por contratos y con paginación de 1 en 1.
	var vistos []string
	cursor := ""
	for i := 0; i < 5; i++ {
		q := "/api/v1/competitors?cpv=72&limit=1&orden=contratos"
		if cursor != "" {
			q += "&cursor=" + url.QueryEscape(cursor)
		}
		var pg paginaComp
		getJSON(t, ts, q, &pg)
		for _, it := range pg.Items {
			vistos = append(vistos, it.Organizacion.Nombre)
		}
		if pg.Sig == nil {
			break
		}
		cursor = *pg.Sig
	}
	if strings.Join(vistos, "|") != "Uno Sistemas SL|Dos Redes SL|Tres Datos SA" {
		t.Fatalf("paginado por contratos: %v", vistos)
	}
	// Filtrar por fechas deja solo lo adjudicado en ese periodo; sin nada en el mercado, la lista es vacía.
	var vacio paginaComp
	getJSON(t, ts, "/api/v1/competitors?cpv=72&desde=2026-08-15&hasta=2026-12-31", &vacio)
	if len(vacio.Items) != 1 || vacio.Items[0].Organizacion.Nombre != "Uno Sistemas SL" {
		t.Fatalf("desde 2026-08-15 solo gana W1 (sep): %+v", vacio.Items)
	}
	var nada paginaComp
	getJSON(t, ts, "/api/v1/competitors?cpv=90", &nada)
	if len(nada.Items) != 0 || nada.Total.Valor != 0 {
		t.Fatalf("mercado sin adjudicaciones: %+v", nada)
	}
}

func TestParametrosDeContratosQueVencen(t *testing.T) {
	repo := &fakeRepo{}
	srv, ts := servidor(t, repo)
	srv.Now = func() time.Time { return time.Date(2026, 10, 28, 12, 0, 0, 0, time.UTC) }
	malos := []string{
		"/api/v1/expiring-contracts?area=cctv",
		"/api/v1/expiring-contracts?importe_max=100", // no existe en esta ruta
		"/api/v1/expiring-contracts?vence_desde=2027-02-30",
		"/api/v1/expiring-contracts?vence_desde=2027-05-01&vence_hasta=2027-01-01",
		"/api/v1/expiring-contracts?vence_desde=2027-01-01&vence_hasta=2030-01-02", // más de 36 meses
		"/api/v1/expiring-contracts?con_prorrogas=si",
		"/api/v1/expiring-contracts?cpv=7",
		"/api/v1/expiring-contracts?limit=0",
	}
	for _, p := range malos {
		if r := get(t, ts, p, token); r.StatusCode != 400 {
			t.Errorf("%s: esperaba 400, llegó %d: %s", p, r.StatusCode, r.Body)
		}
	}
	// por defecto: de hoy + 3 meses a hoy + 12 meses, sin prórrogas
	if r := get(t, ts, "/api/v1/expiring-contracts", token); r.StatusCode != 200 {
		t.Fatalf("por defecto: %d %s", r.StatusCode, r.Body)
	}
	if f := repo.vistoVence; f.VenceDesde != "2027-01-28" || f.VenceHasta != "2027-10-28" || f.ConProrrogas || f.Limit != 20 {
		t.Fatalf("periodo por defecto: %+v", f)
	}
	if r := get(t, ts, "/api/v1/expiring-contracts?cpv=72&nuts=ES512&comprador=nif:P1708500E&importe_min=50000&vence_desde=2027-01-01&vence_hasta=2030-01-01&con_prorrogas=true&limit=7", token); r.StatusCode != 200 {
		t.Fatalf("válida: %d %s", r.StatusCode, r.Body)
	}
	if f := repo.vistoVence; f.VenceDesde != "2027-01-01" || f.VenceHasta != "2030-01-01" || !f.ConProrrogas || f.Limit != 7 || f.ImporteMin != "50000" || len(f.CompradorNIF) != 1 {
		t.Fatalf("filtro mal traducido: %+v", f)
	}
}

type paginaVence struct {
	Items []struct {
		AdjudicacionID string                   `json:"adjudicacion_id"`
		LicitacionID   string                   `json:"licitacion_id"`
		Titulo         string                   `json:"titulo"`
		Lote           string                   `json:"lote"`
		Adjudicatario  *struct{ Nombre string } `json:"adjudicatario"`
		Importe        *Importe                 `json:"importe_adjudicado"`
		Formalizacion  *string                  `json:"fecha_formalizacion"`
		Fin            string                   `json:"fecha_fin"`
		Posibles       *bool                    `json:"prorrogas_posibles"`
		FinProrrogas   *string                  `json:"fecha_fin_con_prorrogas"`
		Texto          *string                  `json:"prorrogas_texto"`
		Confianza      *float64                 `json:"confianza"`
	} `json:"items"`
	Sig   *string `json:"siguiente_cursor"`
	Total struct {
		Valor int `json:"valor"`
	} `json:"total"`
	Periodo struct {
		Desde, Hasta string `json:"-"`
	} `json:"periodo"`
}

func TestContratosQueVencenConPostgres(t *testing.T) {
	ts, st, _ := conPostgres(t)
	si := true
	// formalizados en 2025-03-01 con duración 2 años → terminan el 2027-02-28
	datos := []struct {
		id, ini, dur, unidad string
		ext                  *domain.Extension
	}{
		{"v/1", "2025-03-01", "2", "ANN", &domain.Extension{Text: "Dos prórrogas de un año", Allowed: &si, Count: 2, Each: &domain.Duration{Value: "1", Unit: "ANN"}}}, // 2027-02-28 / 2029-02-28
		{"v/2", "2025-06-01", "24", "MON", nil},                                           // 2027-05-31
		{"v/3", "2025-01-01", "12", "MON", nil},                                           // 2025-12-31: ya terminó
		{"v/4", "2026-01-01", "5", "ANN", &domain.Extension{Text: "Consultar el pliego"}}, // 2030-12-31
		{"v/5", "2025-09-01", "3", "ANN", nil},                                            // 2028-08-31
	}
	base := time.Date(2026, 10, 1, 10, 0, 0, 0, time.UTC)
	for i, d := range datos {
		l := &domain.Licitacion{Source: "placsp-643", SourceID: d.id, NumericID: fmt.Sprint(i), Updated: base.Add(time.Duration(i) * time.Minute), Expediente: "V-" + d.id, Status: "ADJ",
			Title: "Contrato " + d.id, Organism: domain.Organization{Name: "Ayuntamiento de Girona", NIF: "P1708500E"}, Procedure: "1", CPV: []string{"72000000"},
			NUTS: []string{"ES512"}, Link: "https://x.test/" + d.id, Duration: &domain.Duration{Value: d.dur, Unit: d.unidad}, Extension: d.ext,
			Results: []domain.Result{{Code: domain.ResultFormalized, WinnerName: "Uno Sistemas SL", WinnerID: "B11111111", AwardedExclVAT: &domain.Money{Value: "100000", Currency: "EUR"},
				FormalizedOn: domain.Date(d.ini)}}}
		ev := ingest.Event{Source: "placsp-643", SourceID: d.id, Version: 1, RawSHA256: "ab", RawKey: "k"}
		if _, err := st.UpsertExpediente(context.Background(), ev, l); err != nil {
			t.Fatal(err)
		}
	}
	titulos := func(p paginaVence) []string {
		var out []string
		for _, it := range p.Items {
			out = append(out, it.Titulo)
		}
		return out
	}
	// ventana de 2027 completo: v/1 (feb), v/2 (may); el que terminó en 2025 y los de 2028 y 2030 no
	var p paginaVence
	getJSON(t, ts, "/api/v1/expiring-contracts?vence_desde=2027-01-01&vence_hasta=2027-12-31", &p)
	if got := strings.Join(titulos(p), "|"); got != "Contrato v/1|Contrato v/2" || p.Total.Valor != 2 {
		t.Fatalf("2027: %s (total %d)", got, p.Total.Valor)
	}
	a := p.Items[0]
	if a.Fin != "2027-02-28" || a.Posibles == nil || !*a.Posibles || a.FinProrrogas == nil || *a.FinProrrogas != "2029-02-28" || a.Confianza == nil || *a.Confianza != 0.7 ||
		a.Adjudicatario == nil || a.Adjudicatario.Nombre != "Uno Sistemas SL" || a.Importe == nil || a.Importe.Valor != "100000.00" || a.Formalizacion == nil || *a.Formalizacion != "2025-03-01" || a.Lote != "1" {
		t.Fatalf("v/1: %+v", a)
	}
	if b := p.Items[1]; b.Posibles != nil || b.FinProrrogas != nil || b.Texto != nil {
		t.Fatalf("v/2 no dice nada de prórrogas: %+v", b)
	}
	// con prórrogas: v/1 pasa a terminar en 2029 (y sale de 2027); los que no tienen dato siguen con su fecha de fin
	var cp paginaVence
	getJSON(t, ts, "/api/v1/expiring-contracts?vence_desde=2027-01-01&vence_hasta=2027-12-31&con_prorrogas=true", &cp)
	if got := strings.Join(titulos(cp), "|"); got != "Contrato v/2" {
		t.Fatalf("2027 con prórrogas: %s", got)
	}
	var cp2 paginaVence
	getJSON(t, ts, "/api/v1/expiring-contracts?vence_desde=2029-01-01&vence_hasta=2029-12-31&con_prorrogas=true", &cp2)
	if got := strings.Join(titulos(cp2), "|"); got != "Contrato v/1" {
		t.Fatalf("2029 con prórrogas: %s", got)
	}
	// el texto que no se entiende se entrega tal cual, sin fecha con prórrogas
	var t4 paginaVence
	getJSON(t, ts, "/api/v1/expiring-contracts?vence_desde=2030-01-01&vence_hasta=2030-12-31", &t4)
	if len(t4.Items) != 1 || t4.Items[0].Texto == nil || *t4.Items[0].Texto != "Consultar el pliego" || t4.Items[0].FinProrrogas != nil {
		t.Fatalf("v/4: %+v", t4.Items)
	}
	// filtros del mercado, orden por fin y paginación de 1 en 1 sobre 2027–2029
	var otro paginaVence
	getJSON(t, ts, "/api/v1/expiring-contracts?cpv=35&vence_desde=2027-01-01&vence_hasta=2029-12-31", &otro)
	if len(otro.Items) != 0 {
		t.Fatalf("otro CPV: %v", titulos(otro))
	}
	var vistos []string
	cursor := ""
	for i := 0; i < 8; i++ {
		q := "/api/v1/expiring-contracts?vence_desde=2027-01-01&vence_hasta=2029-12-31&limit=1&cpv=72"
		if cursor != "" {
			q += "&cursor=" + url.QueryEscape(cursor)
		}
		var pg paginaVence
		getJSON(t, ts, q, &pg)
		vistos = append(vistos, titulos(pg)...)
		if pg.Sig == nil {
			break
		}
		cursor = *pg.Sig
	}
	if got := strings.Join(vistos, "|"); got != "Contrato v/1|Contrato v/2|Contrato v/5" {
		t.Fatalf("orden por fecha de fin: %s", got)
	}
	// el cursor de otro periodo se rechaza
	var pr paginaVence
	getJSON(t, ts, "/api/v1/expiring-contracts?vence_desde=2027-01-01&vence_hasta=2029-12-31&limit=1", &pr)
	if r := get(t, ts, "/api/v1/expiring-contracts?vence_desde=2027-01-01&vence_hasta=2029-11-30&limit=1&cursor="+url.QueryEscape(*pr.Sig), token); r.StatusCode != 400 {
		t.Fatalf("cursor de otro periodo: %d", r.StatusCode)
	}
}
