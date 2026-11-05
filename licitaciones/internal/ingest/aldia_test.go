package ingest

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestAlDia(t *testing.T) {
	cadena := func(urls ...string) map[string]string { // cada página apunta a la siguiente; la última, a ""
		m := map[string]string{}
		for i, u := range urls {
			next := ""
			if i+1 < len(urls) {
				next = urls[i+1]
			}
			m[u] = next
		}
		return m
	}
	casos := []struct {
		nombre    string
		done      map[string]string
		siguiente string
		quiero    bool
	}{
		{"estado estable: todo ingerido desde la cabecera", cadena("a", "b", "c"), "a", true},
		{"sin archivo y sin siguiente (fuente nueva con una sola página)", map[string]string{}, "", true},
		{"tras una parada: la primera página de archivo aún no está ingerida", cadena("viejaA", "viejaB"), "nueva1", false},
		{"a medias: las nuevas ingeridas no enlazan todavía con las antiguas", func() map[string]string {
			m := cadena("n1", "n2")
			m["n2"] = "n3" // la siguiente (n3) aún no está ingerida
			for k, v := range cadena("viejaA", "viejaB") {
				m[k] = v
			}
			return m
		}(), "n1", false},
		{"hueco rellenado: las nuevas enlazan con las antiguas", func() map[string]string {
			m := cadena("n1", "n2", "viejaA", "viejaB")
			return m
		}(), "n1", true},
		{"fuente nueva: cabecera ingerida pero ninguna página de archivo", map[string]string{}, "p1", false},
		{"ciclo en la fuente: no se queda dando vueltas", map[string]string{"a": "b", "b": "a"}, "a", true},
	}
	for _, c := range casos {
		if got := AlDia(c.done, c.siguiente); got != c.quiero {
			t.Errorf("%s: AlDia = %v, quiero %v", c.nombre, got, c.quiero)
		}
	}
}

// Tras una parada (el equipo apagado) aparecen páginas nuevas que no se conocen: mientras se rellena el hueco NO está al día, aunque la cabeza ya se haya mirado.
func TestAlDiaSeRecuperaCuandoSeRellenaElHuecoDeUnaParada(t *testing.T) {
	f := cadena() // inicio → p2 → p3
	d, _, st := deps(f)
	ctx := context.Background()
	s0, err := Run(ctx, d, src, inicio, RunOptions{})
	if err != nil || !s0.CaughtUp {
		t.Fatalf("la primera carga completa deja la fuente al día: %+v %v", s0, err)
	}

	// Mientras estuvo apagado la plataforma publicó dos páginas nuevas (n1 → n2) delante de p2.
	n1, n2 := "https://contrataciondelestado.es/n1.atom", "https://contrataciondelestado.es/n2.atom"
	f.etag = ""
	f.paginas[inicio] = conEnlace(pagina(entrada("10", "2026-10-29T10:00:00.000+01:00", "PUB")), n1)
	f.paginas[n1] = conEnlace(pagina(entrada("11", "2026-10-28T10:00:00.000+01:00", "PUB")), n2)
	f.paginas[n2] = conEnlace(pagina(entrada("12", "2026-10-27T11:00:00.000+01:00", "PUB")), u2)

	s1, err := Run(ctx, d, src, inicio, RunOptions{MaxPages: 2}) // cabeza + n1: aún falta n2
	if err != nil || s1.CaughtUp {
		t.Fatalf("con n2 por ingerir NO está al día: %+v %v", s1, err)
	}
	s2, err := Run(ctx, d, src, inicio, RunOptions{MaxPages: 5})
	if err != nil || !s2.CaughtUp {
		t.Fatalf("relleno el hueco, vuelve a estar al día: %+v %v", s2, err)
	}
	if cp, _ := st.Checkpoint(ctx, src); cp.Next != n1 {
		t.Fatalf("la cabeza apunta ahora a n1: %+v", cp)
	}
}

// Un fallo en una página ANTIGUA del relleno no debe impedir saber que lo reciente está completo (ni se queda sin anotar).
func TestAlDiaSeCalculaAunqueLaVueltaAcabeEnError(t *testing.T) {
	f := cadena()
	f.errs = map[string]error{u3: errors.New("entrada demasiado grande")}
	d, _, _ := deps(f)
	s, err := Run(context.Background(), d, src, inicio, RunOptions{})
	if err == nil {
		t.Fatal("la vuelta debe acabar en error")
	}
	if !s.CaughtUp || s.Pages == 0 {
		t.Fatalf("lo reciente (cabeza y p2) está ingerido y encadenado: debe contar como al día aunque falle p3: %+v", s)
	}
}

// Lo que importa es lo RECIENTE: si el primer hueco de la cadena es de hace meses (relleno del histórico), la fuente está al día aunque falte pasado; si el hueco es reciente (el equipo estuvo apagado),
// no; y sin fecha en el nombre se exige lo mismo que AlDia.
func TestAlDiaRecienteIgnoraLosHuecosDelHistorico(t *testing.T) {
	base := "https://contrataciondelestado.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3_"
	pag := func(fecha string, n int) string { // 20251114_224748 + sufijo
		u := base + fecha
		if n > 0 {
			u += "_" + string(rune('0'+n))
		}
		return u + ".atom"
	}
	ahora := time.Date(2026, 11, 5, 10, 0, 0, 0, time.UTC)
	reciente1, reciente2 := pag("20261104_190734", 0), pag("20261103_190511", 0)
	viejo1, hueco, viejoSuelto := pag("20260101_120000", 0), pag("20250926_183504", 4), pag("20250920_100000", 0)

	casos := []struct {
		nombre    string
		done      map[string]string
		siguiente string
		quiero    bool
	}{
		{"hueco antiguo (histórico): lo reciente está completo", map[string]string{reciente1: reciente2, reciente2: viejo1, viejo1: hueco, viejoSuelto: ""}, reciente1, true},
		{"hueco de hace 2 días: el equipo estuvo apagado, no está al día", map[string]string{reciente2: viejo1}, reciente1, false},
		{"hueco reciente en medio de la cadena", map[string]string{reciente1: reciente2, viejoSuelto: ""}, reciente1, false},
		{"sin fecha en el nombre se exige lo estricto", map[string]string{"a": "b", "z": ""}, "a", false},
		{"todo ingerido: al día", map[string]string{reciente1: reciente2, reciente2: ""}, reciente1, true},
		{"la cabecera apunta a una página aún sin ingerir y es antigua (instalación nueva con histórico por llenar)", map[string]string{}, hueco, true},
	}
	for _, c := range casos {
		if got := AlDiaReciente(c.done, c.siguiente, ahora, VentanaAlDia); got != c.quiero {
			t.Errorf("%s: AlDiaReciente = %v, quiero %v", c.nombre, got, c.quiero)
		}
	}
	if _, ok := fechaDePagina(pag("20250926_183504", 4)); !ok {
		t.Error("la fecha de una página de archivo se tiene que poder leer")
	}
	if _, ok := fechaDePagina("https://x/inicio.atom"); ok {
		t.Error("una dirección sin fecha no tiene fecha")
	}
}
