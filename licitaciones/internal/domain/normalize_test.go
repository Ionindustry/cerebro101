package domain

import "testing"

func TestEstado(t *testing.T) {
	r := func(codes ...string) []Result {
		var out []Result
		for _, c := range codes {
			out = append(out, Result{Code: c})
		}
		return out
	}
	for nombre, c := range map[string]struct {
		l    Licitacion
		want string
	}{
		"anulada manda":            {Licitacion{Status: "ANUL", Results: r(ResultAwarded)}, EstadoAnulada},
		"formalizada sobre adjud.": {Licitacion{Status: "ADJ", Results: r(ResultAwarded, ResultFormalized)}, EstadoFormalizada},
		"adjudicada por resultado": {Licitacion{Status: "PUB", Results: r(ResultAwarded)}, EstadoAdjudicada},
		"desierta":                 {Licitacion{Status: "EV", Results: r(ResultVoid)}, EstadoDesierta},
		"previo":                   {Licitacion{Status: "PRE"}, EstadoAnuncioPrevio},
		"en plazo":                 {Licitacion{Status: "PUB"}, EstadoAbierta},
		"evaluación":               {Licitacion{Status: "EV"}, EstadoCerrada},
		"resuelta":                 {Licitacion{Status: "RES"}, EstadoAdjudicada},
		"sin estado conocido":      {Licitacion{Status: "XX"}, EstadoAbierta},
	} {
		if got := c.l.Estado(); got != c.want {
			t.Errorf("%s: %q, quería %q", nombre, got, c.want)
		}
	}
}

func TestProcedimientoNormalizado(t *testing.T) {
	for in, want := range map[string]string{"1": "abierto", "6": "menor", "9": "abierto_simplificado", "100": "otro", "999": "otro", "": ""} {
		if got := ProcedimientoNormalizado(in); got != want {
			t.Errorf("%q → %q, quería %q", in, got, want)
		}
	}
}
