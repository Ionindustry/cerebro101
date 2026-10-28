package placsp

import (
	"regexp"
	"strconv"
	"strings"

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
)

// maxTextoProrroga acota el texto de origen que se guarda: es texto libre de un tercero y solo hace falta para leerlo, no para calcular.
const maxTextoProrroga = 1000

var (
	// «Número de prórrogas: 1 … Duración máxima de cada prórroga: 2 años»
	reNumeroProrrogas = regexp.MustCompile(`(?i)n[úu]mero de pr[óo]rrogas?\s*:\s*(\d{1,2})\b`)
	reDuracionCadaUna = regexp.MustCompile(`(?i)duraci[óo]n m[áa]xima de cada pr[óo]rroga\s*:\s*(\d{1,3})\s*(a[ñn]os?|mes(?:es)?|d[íi]as?)\b`)
	// «tres (3) prórrogas de un (1) año cada una», «2 prórrogas de 12 meses», «una prórroga de un año»
	reProrrogasDe = regexp.MustCompile(`(?i)\b(\d{1,2}|un|una|dos|tres|cuatro|cinco|seis)\b\s*(?:\(\s*(\d{1,2})\s*\))?\s*pr[óo]rrogas?\s+(?:sucesivas?\s+)?de\s+(?:hasta\s+)?(\d{1,3}|un|una|dos|tres|cuatro|cinco|seis|doce|veinticuatro)\b\s*(?:\(\s*(\d{1,3})\s*\))?\s*(a[ñn]os?|mes(?:es)?|d[íi]as?)\b`)
	// Negaciones: «No se preven prórrogas», «NO SE CONTEMPLA LA POSIBILIDAD DE PRÓRROGA», «sin prórroga», «Prórroga: NO», «Se admite prórroga: No».
	reNoHay = regexp.MustCompile(`(?i)(\bno\s+(?:se\s+)?(?:admite|admiten|cabe|caben|prev[eé]n?|hay|existe|existen|procede|contempla|contemplan)\b[^.;]{0,60}?pr[óo]rrog|\bsin\s+pr[óo]rrogas?|pr[óo]rrogas?\s*:\s*no\b|:\s*no\s+se\s+admite)`)
	// Afirmaciones: solo formas que dicen que SE PUEDE prorrogar. «Consultar detalle de las prórrogas en el pliego» no dice nada.
	reSiHay = regexp.MustCompile(`(?i)(pr[óo]rrogas?\s*:\s*s[ií]\b|\bprorrogables?\b|\bpodr[áa]\s+ser\s+(?:objeto\s+de\s+)?(?:\w+\s+)?prorrog|\bposible\s+pr[óo]rroga|\bposibilidad\s+de\s+(?:pr[óo]rrogas?|prorrogar)|\bcabe\s+(?:la\s+opci[óo]n\s+de\s+)?(?:\w+\s+)?(?:\(\d+\)\s+)?pr[óo]rrogas?|\bse\s+admitir[áa]n?\s+pr[óo]rrogas?|\bse\s+contempla\s+(?:una\s+)?pr[óo]rroga|\bse\s+prev[eé]\s+(?:la\s+)?(?:posibilidad\s+de\s+)?pr[óo]rroga)`)
	numeros = map[string]int{"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "doce": 12, "veinticuatro": 24}
)

func cuenta(palabra, entreParentesis string) (int, bool) {
	if entreParentesis != "" {
		n, err := strconv.Atoi(entreParentesis)
		return n, err == nil
	}
	if n, ok := numeros[strings.ToLower(palabra)]; ok {
		return n, true
	}
	n, err := strconv.Atoi(palabra)
	return n, err == nil
}

func unidad(u string) string {
	switch strings.ToLower(u)[0] {
	case 'a':
		return "ANN"
	case 'm':
		return "MON"
	default:
		return "DAY"
	}
}

// extension interpreta el texto de las prórrogas con reglas conservadoras: solo rellena lo que el texto dice sin ambigüedad. Si el texto es de otro
// estilo, queda solo el texto (Count = 0) y el motor no calculará la fecha de fin con prórrogas.
func extension(raw string) *domain.Extension {
	t := clean(raw)
	if t == "" {
		return nil
	}
	if r := []rune(t); len(r) > maxTextoProrroga {
		t = string(r[:maxTextoProrroga-1]) + "…"
	}
	e := &domain.Extension{Text: t}
	yes, no := true, false
	switch {
	case reNoHay.MatchString(t):
		e.Allowed = &no
		return e
	case reSiHay.MatchString(t):
		e.Allowed = &yes
	}
	// Más de una cláusula («Dos prórrogas de 4 años y una prórroga de 3 años») no se suma por adivinación: queda solo el texto.
	if ms := reProrrogasDe.FindAllStringSubmatch(t, 2); len(ms) == 1 {
		m := ms[0]
		n, ok1 := cuenta(m[1], m[2])
		v, ok2 := cuenta(m[3], m[4])
		if ok1 && ok2 && n > 0 && v > 0 {
			e.Count, e.Each = n, &domain.Duration{Value: strconv.Itoa(v), Unit: unidad(m[5])}
			e.Allowed = &yes
			return e
		}
	}
	if n := reNumeroProrrogas.FindStringSubmatch(t); n != nil {
		c, err := strconv.Atoi(n[1])
		if err == nil && c == 0 {
			e.Allowed = &no
		} else if d := reDuracionCadaUna.FindStringSubmatch(t); err == nil && d != nil {
			if v, err := strconv.Atoi(d[1]); err == nil && v > 0 {
				e.Count, e.Each = c, &domain.Duration{Value: strconv.Itoa(v), Unit: unidad(d[2])}
				e.Allowed = &yes
			}
		}
	}
	return e
}
