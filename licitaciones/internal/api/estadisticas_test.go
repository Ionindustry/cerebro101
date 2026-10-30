package api

import (
	"errors"
	"net/http"
	"strings"
	"testing"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

func TestEstadisticasUsaLosMismosFiltrosQueLaBusqueda(t *testing.T) {
	repo := &fakeRepo{estad: pg.Estadisticas{
		Total: 3, ConImporte: 2, ImporteTotal: "300000", ImporteMedio: "150000.5", Abiertas: 2, VencenSemana: 1,
		Estados:     []pg.Cuenta{{Valor: "abierta", Cuenta: 2}, {Valor: "cerrada", Cuenta: 1}},
		Compradores: []pg.Cuenta{{Valor: "Ajuntament", NIF: "P1234567A", Cuenta: 3, Importe: "300000"}},
		Plazos:      []pg.Cuenta{{Valor: "2026-11-02", Cuenta: 1}},
	}}
	_, ts := servidor(t, repo)
	res := get(t, ts, "/api/v1/tenders/estadisticas?q=c%C3%A1maras&estado=abierta&nuts=ES512&importe_min=1000", token)
	if res.StatusCode != http.StatusOK {
		t.Fatalf("estado %d: %s", res.StatusCode, res.Body)
	}
	if repo.visto.Q != "cámaras" || len(repo.visto.Estados) != 1 || len(repo.visto.NUTS) != 1 || repo.visto.ImporteMin != "1000" {
		t.Fatalf("el filtro no llegó entero: %+v", repo.visto)
	}
	var got struct {
		Total    int `json:"total"`
		Abiertas int `json:"abiertas"`
		Vencen   int `json:"vencen_7_dias"`
		Importe  struct {
			Total, Medio, Moneda, Impuestos string
			ConImporte                      int `json:"con_importe"`
		} `json:"importe"`
		Estados     []Grupo `json:"estados"`
		Zonas       []Grupo `json:"zonas"`
		Compradores []Grupo `json:"compradores"`
	}
	decode(t, res, &got)
	if got.Total != 3 || got.Abiertas != 2 || got.Vencen != 1 || got.Importe.ConImporte != 2 {
		t.Fatalf("cifras: %+v", got)
	}
	if got.Importe.Total != "300000.00" || got.Importe.Medio != "150000.50" || got.Importe.Moneda != "EUR" || got.Importe.Impuestos != "sin_iva" {
		t.Fatalf("importe: %+v", got.Importe)
	}
	if len(got.Estados) != 2 || got.Estados[0].Valor != "abierta" || len(got.Zonas) != 0 {
		t.Fatalf("repartos: %+v", got)
	}
	if got.Compradores[0].NIF != "P1234567A" || got.Compradores[0].Importe != "300000.00" || got.Estados[0].Importe != "" {
		t.Fatalf("compradores: %+v", got.Compradores)
	}
}

func TestEstadisticasSinResultadosDevuelveRepartosVacios(t *testing.T) {
	_, ts := servidor(t, &fakeRepo{})
	res := get(t, ts, "/api/v1/tenders/estadisticas", token)
	if res.StatusCode != http.StatusOK {
		t.Fatalf("estado %d: %s", res.StatusCode, res.Body)
	}
	var got map[string]any
	decode(t, res, &got)
	for _, k := range []string{"estados", "zonas", "cpv", "importes", "compradores", "plazos"} {
		if v, ok := got[k].([]any); !ok || len(v) != 0 {
			t.Fatalf("%s debería ser una lista vacía, no nula: %v", k, got[k])
		}
	}
}

func TestEstadisticasRechazaFiltrosInvalidosYSinTokenYErrores(t *testing.T) {
	_, ts := servidor(t, &fakeRepo{})
	if res := get(t, ts, "/api/v1/tenders/estadisticas?cpv=zz", token); res.StatusCode != http.StatusBadRequest {
		t.Fatalf("filtro inválido: %d", res.StatusCode)
	}
	if res := get(t, ts, "/api/v1/tenders/estadisticas", ""); res.StatusCode != http.StatusUnauthorized {
		t.Fatalf("sin token: %d", res.StatusCode)
	}
	_, ts2 := servidor(t, &fakeRepo{estadErr: errors.New("boom")})
	res := get(t, ts2, "/api/v1/tenders/estadisticas", token)
	if res.StatusCode != http.StatusInternalServerError || strings.Contains(string(res.Body), "boom") {
		t.Fatalf("error interno sin detalles: %d %s", res.StatusCode, res.Body)
	}
}
