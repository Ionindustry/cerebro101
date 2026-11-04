package api

import (
	"net/http"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

func TestEstadoDiceSiLaFuenteSeEstaPoniendoAlDia(t *testing.T) {
	ahora := time.Now().Add(-time.Minute)
	repo := &fakeRepo{fuentes: []pg.EstadoFuente{{Fuente: "placsp-643", UltimaOK: &ahora, Expediente: 10, AlDia: false}}}
	_, ts := servidor(t, repo)
	res := get(t, ts, "/api/v1/ops/status", token)
	if res.StatusCode != http.StatusOK {
		t.Fatalf("estado %d: %s", res.StatusCode, res.Body)
	}
	var got struct {
		Fuentes []struct {
			Fuente string `json:"fuente"`
			AlDia  *bool  `json:"al_dia"`
		} `json:"fuentes"`
	}
	decode(t, res, &got)
	if len(got.Fuentes) != 1 || got.Fuentes[0].AlDia == nil || *got.Fuentes[0].AlDia {
		t.Fatalf("debe decir al_dia=false: %+v", got)
	}
	repo.fuentes[0].AlDia = true
	decode(t, get(t, ts, "/api/v1/ops/status", token), &got)
	if got.Fuentes[0].AlDia == nil || !*got.Fuentes[0].AlDia {
		t.Fatalf("debe decir al_dia=true: %+v", got)
	}
}
