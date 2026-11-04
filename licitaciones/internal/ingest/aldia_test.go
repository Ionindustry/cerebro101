package ingest

import "testing"

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
