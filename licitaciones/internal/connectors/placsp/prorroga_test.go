package placsp

import "testing"

// Textos reales de las muestras (extension del pliego): lo que se reconoce con claridad y, sobre todo, lo que NO se debe inventar.
func TestExtensionConTextosReales(t *testing.T) {
	si, no := true, false
	casos := []struct {
		texto   string
		allowed *bool
		count   int
		valor   string // duración de cada prórroga, «2 ANN»
	}{
		{"Se admite prórroga: Sí, de forma obligatoria para el contratista.\r\nNúmero de prórrogas: 1\r\nDuración máxima de cada prorroga: 2 años.", &si, 1, "2 ANN"},
		{"Cabe la opción de tres (3) prórrogas de un (1) año cada una", &si, 3, "1 ANN"},
		{"Según las cláusulas 7.2 y 10.1 del PCAP, se contempla una prórroga de doce (12) meses, en las mismas condiciones económicas", &si, 1, "12 MON"},
		{"Dos prórrogas de un año cada una (1+1), con una duración total máxima del contrato de cuatro años.", &si, 2, "1 ANN"},
		{"PRÓRROGA: SI. Duración de la prórroga: 4 prórrogas de hasta un año de duración cada una.", &si, 4, "1 ANN"},
		{"Número de prórrogas: 0", &no, 0, ""},
		// ambigua: dos cláusulas distintas; no se suma por adivinación
		{"Dos prórrogas de 4 años y una prórroga de 3 años", nil, 0, ""},
		// se sabe que se puede, pero no cuánto
		{"Podrá ser prorrogado por un año más de duración.", &si, 0, ""},
		{"El contrato podrá ser prorrogado una o varias veces antes de la finalización del mismo, hasta un máximo de 24 meses", &si, 0, ""},
		{"Prorrogable un año, desde el 1 de enero de 2028 hasta el 31 de diciembre de 2028.", &si, 0, ""},
		// negaciones
		{"No se preven prórrogas", &no, 0, ""},
		{"NO SE CONTEMPLA LA POSIBILIDAD DE PRÓRROGA", &no, 0, ""},
		{"No Se prevén modificaciones del contrato ni prórrogas", &no, 0, ""},
		{"Ver apartado letra D. del PCAP: no se admite", &no, 0, ""},
		{"Sin prórroga", &no, 0, ""},
		// no dicen nada
		{"Consultar detalle de las prórrogas en el pliego de cláusulas administrativas", nil, 0, ""},
		{"Según clausulas del PCAP", nil, 0, ""},
		{"Un curso escolar: 2028/2029", nil, 0, ""},
	}
	for _, c := range casos {
		e := extension(c.texto)
		if e == nil {
			t.Errorf("%q: sin extensión", c.texto)
			continue
		}
		got := ""
		if e.Each != nil {
			got = e.Each.Value + " " + e.Each.Unit
		}
		if (e.Allowed == nil) != (c.allowed == nil) || (e.Allowed != nil && *e.Allowed != *c.allowed) || e.Count != c.count || got != c.valor {
			var a any = "nil"
			if e.Allowed != nil {
				a = *e.Allowed
			}
			t.Errorf("%q → allowed=%v count=%d cada=%q; esperaba allowed=%v count=%d cada=%q", c.texto, a, e.Count, got, c.allowed != nil && *c.allowed, c.count, c.valor)
		}
	}
	if extension("   ") != nil {
		t.Error("un texto vacío no es una extensión")
	}
	largo := make([]rune, 3000)
	for i := range largo {
		largo[i] = 'á'
	}
	if e := extension(string(largo)); e == nil || len([]rune(e.Text)) > maxTextoProrroga {
		t.Error("el texto de origen se acota")
	}
}
