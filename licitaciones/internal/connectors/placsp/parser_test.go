package placsp

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
)

// Las pruebas de contrato leen las muestras reales de licitaciones/testdata (NORMAS: ningún parser se toca sin una muestra que lo justifique).
const testdata = "../../../testdata"

func abrir(t *testing.T, ruta string) []byte {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(testdata, ruta))
	if err != nil {
		t.Fatalf("no se puede leer la muestra %s: %v", ruta, err)
	}
	return b
}

type lectura struct {
	feed   Feed
	lics   []*domain.Licitacion
	bajas  []*domain.Baja
	hashes []string
}

func leer(t *testing.T, datos []byte, fuente string) lectura {
	t.Helper()
	var out lectura
	feed, err := ParseFeed(bytes.NewReader(datos), Options{Source: fuente}, func(r Record) error {
		if (r.Licitacion == nil) == (r.Baja == nil) {
			t.Fatal("cada registro debe ser una licitación o una baja")
		}
		if r.RawSHA256 != hashHex(r.Raw) || len(r.Raw) == 0 {
			t.Fatal("el fragmento original y su hash no cuadran")
		}
		out.hashes = append(out.hashes, r.RawSHA256)
		if r.Licitacion != nil {
			out.lics = append(out.lics, r.Licitacion)
		} else {
			out.bajas = append(out.bajas, r.Baja)
		}
		return nil
	})
	if err != nil {
		t.Fatalf("ParseFeed: %v", err)
	}
	out.feed = feed
	return out
}

func buscar(t *testing.T, ls []*domain.Licitacion, expediente string) *domain.Licitacion {
	t.Helper()
	for _, l := range ls {
		if l.Expediente == expediente {
			return l
		}
	}
	t.Fatalf("no está el expediente %s", expediente)
	return nil
}

func TestPLACSP643PaginaCompleta(t *testing.T) {
	datos := abrir(t, "placsp_643/licitacionesPerfilesContratanteCompleto3_20261026T103532Z.atom")
	r := leer(t, datos, domain.SourcePLACSP643)
	if want := bytes.Count(datos, []byte("<entry>")); len(r.lics) != want || want != 68 {
		t.Fatalf("entradas leídas = %d, en el documento = %d (la página de la muestra tiene 68)", len(r.lics), want)
	}
	for _, l := range r.lics {
		if l.Source != domain.SourcePLACSP643 || l.SourceID == "" || l.NumericID == "" || l.Expediente == "" || l.Updated.IsZero() {
			t.Fatalf("entrada sin identidad completa: %+v", l)
		}
	}
	if r.feed.Next == "" || r.feed.Self == "" || r.feed.Updated.IsZero() {
		t.Fatalf("faltan metadatos de la página: %+v", r.feed)
	}
}

// Caso con 4 lotes, resultados mezclados (desistimiento, desiertos y formalizado) y un adjudicatario con importes con y sin IVA.
func TestPLACSP643ExpedienteConLotesYResultados(t *testing.T) {
	r := leer(t, abrir(t, "placsp_643/licitacionesPerfilesContratanteCompleto3_20261026T103532Z.atom"), domain.SourcePLACSP643)
	l := buscar(t, r.lics, "2026-01223")

	if l.Status != "RES" || l.TEDProcedureID != "0d066996-e161-481f-9e1e-d111c411dfa0" || l.Title != "Suministro de zapatas y guarniciones 2026-03" {
		t.Fatalf("cabecera inesperada: %+v", l)
	}
	o := l.Organism
	if o.NIF != "A86868239" || o.DIR3 != "EA0008560" || o.PlatformID != "50404410076062" || o.PartyType != "9" || len(o.Parents) < 2 {
		t.Fatalf("organismo inesperado: %+v", o)
	}
	if l.ContractType != "1" || l.ContractSubType != "2" || l.Procedure != "1" || l.Urgency != "1" || l.System != "0" {
		t.Fatalf("clasificación inesperada: %+v", l)
	}
	if *l.EstimatedValue != (domain.Money{Value: "694160", Currency: "EUR"}) ||
		*l.BaseBudgetExclVAT != (domain.Money{Value: "694160", Currency: "EUR"}) ||
		*l.BaseBudgetInclVAT != (domain.Money{Value: "839933.6", Currency: "EUR"}) {
		t.Fatalf("importes inesperados: %+v %+v %+v", l.EstimatedValue, l.BaseBudgetExclVAT, l.BaseBudgetInclVAT)
	}
	if !reflect.DeepEqual(l.CPV, []string{"34322500"}) || !reflect.DeepEqual(l.NUTS, []string{"ES"}) {
		t.Fatalf("CPV/NUTS inesperados: %v %v", l.CPV, l.NUTS)
	}
	if l.Duration == nil || *l.Duration != (domain.Duration{Value: "2", Unit: "ANN"}) {
		t.Fatalf("duración inesperada: %+v", l.Duration)
	}
	// Plazo sin zona en la hora: se interpreta en Europe/Madrid (CEST, +02:00 el 11/05/2026).
	if l.TenderDeadline == nil || !l.TenderDeadline.Equal(time.Date(2026, 5, 11, 12, 0, 0, 0, time.UTC)) {
		t.Fatalf("plazo inesperado: %v", l.TenderDeadline)
	}

	if len(l.Lots) != 4 || l.Lots[3].ID != "4" || l.Lots[3].BaseBudgetExclVAT.Value != "612500" || l.Lots[3].BaseBudgetInclVAT.Value != "741125" {
		t.Fatalf("lotes inesperados: %+v", l.Lots)
	}
	codes := []string{}
	for _, res := range l.Results {
		codes = append(codes, res.Code)
	}
	if !reflect.DeepEqual(codes, []string{"4", "3", "3", "9"}) {
		t.Fatalf("resultados inesperados: %v", codes)
	}
	w := l.Results[3]
	if w.LotID != "4" || w.WinnerID != "A96598917" || w.WinnerScheme != "NIF" || w.WinnerName != "EUROPART HISPANO ALEMANA S.A." ||
		w.AwardedExclVAT.Value != "481075" || w.AwardedInclVAT.Value != "582100.75" || w.AwardDate != "2026-07-14" ||
		w.FormalizedOn != "2026-08-20" || w.ContractNumber != "4900000770" || w.ContractStartsOn != "2026-08-22" ||
		w.TendersReceived == nil || *w.TendersReceived != 3 || w.WinnerIsSME == nil || !*w.WinnerIsSME || w.AbnormallyLow == nil || *w.AbnormallyLow {
		t.Fatalf("adjudicatario inesperado: %+v", w)
	}
	if len(l.Criteria) != 2 || l.Criteria[1].Type != "OBJ" || l.Criteria[1].Weight != "90" {
		t.Fatalf("criterios inesperados: %+v", l.Criteria)
	}
	if len(l.Documents) < 3 || l.Documents[0].Kind != "legal" || l.Documents[0].Hash == "" {
		t.Fatalf("documentos inesperados: %+v", l.Documents)
	}
	if len(l.Notices) != 5 || l.Notices[0].Type != "DOC_CN" || l.Notices[0].Media != "DOUE" || l.Notices[0].PublishedOn != "2026-04-13" {
		t.Fatalf("anuncios inesperados: %+v", l.Notices)
	}
	if len(l.Warnings) != 0 {
		t.Fatalf("no debería haber avisos: %v", l.Warnings)
	}
}

func TestPLACSP643ExtractoConBajaYPaginacion(t *testing.T) {
	r := leer(t, abrir(t, "placsp_643/extracto_licitacionesPerfilesContratanteCompleto3_20261025_200314.atom"), domain.SourcePLACSP643)
	if len(r.lics) != 19 || len(r.bajas) != 1 {
		t.Fatalf("entradas = %d y bajas = %d; la muestra trae 19 y 1", len(r.lics), len(r.bajas))
	}
	b := r.bajas[0]
	if b.Kind != "ANULADA" || !strings.HasSuffix(b.Ref, "/licitacionesPerfilContratante/20757390") || b.When.IsZero() || b.Source != domain.SourcePLACSP643 {
		t.Fatalf("baja inesperada: %+v", b)
	}
	if !strings.HasSuffix(r.feed.Next, "licitacionesPerfilesContratanteCompleto3_20261023_202231.atom") {
		t.Fatalf("enlace a la página siguiente inesperado: %q", r.feed.Next)
	}
}

// 1044 es un CODICE reducido (INVENTARIO_CAMPOS §8): sin presupuesto con IVA, con plataforma agregadora y bajas CERRADA.
func TestPLACSP1044Reducido(t *testing.T) {
	r := leer(t, abrir(t, "placsp_1044/extracto_PlataformasAgregadasSinMenores_20261024_030059.atom"), domain.SourcePLACSP1044)
	if len(r.lics) == 0 {
		t.Fatal("la muestra no trae entradas")
	}
	agregadas := 0
	for _, l := range r.lics {
		if l.BaseBudgetInclVAT != nil {
			t.Fatalf("1044 no trae presupuesto con IVA y el parser lo ha inventado en %s: %+v", l.Expediente, l.BaseBudgetInclVAT)
		}
		if l.Organism.AggregatorID != "" {
			agregadas++
		}
		for _, res := range l.Results {
			if res.AwardedInclVAT != nil || res.AwardDate != "" {
				t.Fatalf("1044 no trae importe con IVA ni fecha de adjudicación: %+v", res)
			}
		}
	}
	if agregadas == 0 {
		t.Fatal("ninguna entrada de 1044 trae la plataforma agregadora")
	}
	for _, b := range r.bajas {
		if b.Kind != "CERRADA" && b.Kind != "ANULADA" {
			t.Fatalf("tipo de baja inesperado: %q", b.Kind)
		}
	}
}

// 1143: contratos menores; procedimiento siempre 6 y todo adjudicado con importes con y sin IVA.
func TestPLACSP1143Menores(t *testing.T) {
	r := leer(t, abrir(t, "placsp_menores_1143/extracto_contratosMenoresPerfilesContratantes_20261026.atom"), domain.SourcePLACSP1143)
	if len(r.lics) == 0 {
		t.Fatal("la muestra no trae entradas")
	}
	for _, l := range r.lics {
		if l.Procedure != "6" {
			t.Fatalf("los menores tienen procedimiento 6, no %q (%s)", l.Procedure, l.Expediente)
		}
		for _, res := range l.Results {
			if res.Code != domain.ResultAwarded || res.AwardedExclVAT == nil || res.AwardedInclVAT == nil {
				t.Fatalf("resultado de menor incompleto en %s: %+v", l.Expediente, res)
			}
		}
	}
}

func TestLasMuestrasNoGeneranAvisosInesperados(t *testing.T) {
	for _, f := range []struct{ ruta, fuente string }{
		{"placsp_643/licitacionesPerfilesContratanteCompleto3_20261026T103532Z.atom", domain.SourcePLACSP643},
		{"placsp_643/extracto_licitacionesPerfilesContratanteCompleto3_20261025_200314.atom", domain.SourcePLACSP643},
		{"placsp_1044/extracto_PlataformasAgregadasSinMenores_20261024_030059.atom", domain.SourcePLACSP1044},
		{"placsp_1044/extracto_PlataformasAgregadasSinMenores_20261026.atom", domain.SourcePLACSP1044},
		{"placsp_menores_1143/extracto_contratosMenoresPerfilesContratantes_20261026.atom", domain.SourcePLACSP1143},
	} {
		for _, l := range leer(t, abrir(t, f.ruta), f.fuente).lics {
			if len(l.Warnings) != 0 {
				t.Errorf("%s · %s: avisos %v", f.ruta, l.Expediente, l.Warnings)
			}
		}
	}
}

// El fragmento original basta para volver a leer la entrada, con el mismo resultado y el mismo hash (ADR 0004).
func TestElFragmentoOriginalSeVuelveALeerIgual(t *testing.T) {
	datos := abrir(t, "placsp_643/licitacionesPerfilesContratanteCompleto3_20261026T103532Z.atom")
	cabecera := regexp.MustCompile(`<feed[^>]*>`).Find(datos)
	var originales []Record
	if _, err := ParseFeed(bytes.NewReader(datos), Options{Source: domain.SourcePLACSP643}, func(r Record) error {
		originales = append(originales, r)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	for _, o := range originales[:10] {
		pagina := append(append(append([]byte(`<?xml version="1.0" encoding="UTF-8"?>`), cabecera...), o.Raw...), []byte("</feed>")...)
		var otra []Record
		if _, err := ParseFeed(bytes.NewReader(pagina), Options{Source: domain.SourcePLACSP643}, func(r Record) error {
			otra = append(otra, r)
			return nil
		}); err != nil {
			t.Fatal(err)
		}
		if len(otra) != 1 || otra[0].RawSHA256 != o.RawSHA256 || !reflect.DeepEqual(otra[0].Licitacion, o.Licitacion) {
			t.Fatalf("la entrada %s no se reproduce desde su fragmento", o.Licitacion.Expediente)
		}
	}
}

func TestMismoContenidoMismoHash(t *testing.T) {
	datos := abrir(t, "placsp_1044/extracto_PlataformasAgregadasSinMenores_20261026.atom")
	a, b := leer(t, datos, domain.SourcePLACSP1044), leer(t, datos, domain.SourcePLACSP1044)
	if !reflect.DeepEqual(a.hashes, b.hashes) || len(a.hashes) == 0 {
		t.Fatal("dos lecturas del mismo documento deben dar los mismos hashes")
	}
}

const cabeceraMinima = `<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2" xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2" xmlns:cac-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2" xmlns:cbc-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2">`

func entradaMinima(cfs string) string {
	return `<entry><id>https://x.test/sindicacion/licitacionesPerfilContratante/77</id><title>T</title><updated>2026-10-25T13:56:59.348+01:00</updated>` +
		`<cac-place-ext:ContractFolderStatus><cbc:ContractFolderID>E-1</cbc:ContractFolderID>` + cfs + `</cac-place-ext:ContractFolderStatus></entry>`
}

func TestImportesIlegiblesSeDescartanConAviso(t *testing.T) {
	doc := cabeceraMinima + entradaMinima(`<cac:ProcurementProject><cbc:Name>N</cbc:Name><cac:BudgetAmount>`+
		`<cbc:EstimatedOverallContractAmount currencyID="EUR">1,5</cbc:EstimatedOverallContractAmount>`+
		`<cbc:TaxExclusiveAmount currencyID="EUR">1e3</cbc:TaxExclusiveAmount>`+
		`<cbc:TotalAmount>12.50</cbc:TotalAmount></cac:BudgetAmount></cac:ProcurementProject>`) + `</feed>`
	r := leer(t, []byte(doc), domain.SourcePLACSP643)
	l := r.lics[0]
	if l.EstimatedValue != nil || l.BaseBudgetExclVAT != nil {
		t.Fatalf("los importes ilegibles no deben guardarse: %+v %+v", l.EstimatedValue, l.BaseBudgetExclVAT)
	}
	if l.BaseBudgetInclVAT == nil || l.BaseBudgetInclVAT.Value != "12.50" || l.BaseBudgetInclVAT.Currency != "" {
		t.Fatalf("el importe válido debe conservar sus decimales: %+v", l.BaseBudgetInclVAT)
	}
	if len(l.Warnings) != 3 { // dos importes ilegibles y una moneda ausente
		t.Fatalf("avisos esperados = 3, llegaron %v", l.Warnings)
	}
}

func TestUnaEntradaSinContractFolderStatusSeAvisa(t *testing.T) {
	r := leer(t, []byte(cabeceraMinima+`<entry><id>https://x.test/9</id><updated>2026-10-25T13:56:59+01:00</updated></entry></feed>`), domain.SourcePLACSP643)
	if len(r.lics) != 1 || len(r.lics[0].Warnings) == 0 {
		t.Fatalf("debería leerse con un aviso: %+v", r.lics)
	}
}

func TestDocumentosHostilesSeRechazan(t *testing.T) {
	casos := map[string]struct {
		doc  string
		opt  Options
		want error
	}{
		"DTD con entidad": {`<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY x SYSTEM "file:///etc/passwd">]><feed xmlns="http://www.w3.org/2005/Atom"></feed>`, Options{}, ErrDTD},
		"no es un feed":   {`<html><body/></html>`, Options{}, ErrNoFeed},
		"vacío":           {``, Options{}, ErrNoFeed},
		"entrada enorme": {cabeceraMinima + entradaMinima(`<cbc:Note>`+strings.Repeat("a", 4000)+`</cbc:Note>`) + `</feed>`,
			Options{MaxEntryBytes: 2048}, ErrEntryTooLarge},
		"página enorme": {cabeceraMinima + entradaMinima(``) + `</feed>`, Options{MaxFeedBytes: 100}, ErrFeedTooLarge},
	}
	for nombre, c := range casos {
		t.Run(nombre, func(t *testing.T) {
			c.opt.Source = domain.SourcePLACSP643
			_, err := ParseFeed(strings.NewReader(c.doc), c.opt, func(Record) error { return nil })
			if !errors.Is(err, c.want) {
				t.Fatalf("error = %v, quería %v", err, c.want)
			}
		})
	}
}

func TestEntidadesYCodificacionesNoUTF8(t *testing.T) {
	for nombre, doc := range map[string]string{
		"entidad no declarada": cabeceraMinima + `<entry><id>&xxe;</id></entry></feed>`,
		"ISO-8859-1":           `<?xml version="1.0" encoding="ISO-8859-1"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>`,
		"sin cerrar":           cabeceraMinima + `<entry><id>1</id>`,
		"mal formado":          cabeceraMinima + `<entry><id>1</entry></feed>`,
	} {
		t.Run(nombre, func(t *testing.T) {
			_, err := ParseFeed(strings.NewReader(doc), Options{Source: domain.SourcePLACSP643}, func(Record) error { return nil })
			if err == nil {
				t.Fatal("debería rechazarse")
			}
		})
	}
}

func TestSinFuenteYErrorDelCallback(t *testing.T) {
	if _, err := ParseFeed(strings.NewReader(cabeceraMinima+`</feed>`), Options{}, nil); err == nil {
		t.Fatal("sin fuente debe fallar")
	}
	parar := errors.New("parar")
	_, err := ParseFeed(strings.NewReader(cabeceraMinima+entradaMinima(``)+entradaMinima(``)+`</feed>`), Options{Source: domain.SourcePLACSP643},
		func(Record) error { return parar })
	if !errors.Is(err, parar) {
		t.Fatalf("el error del callback debe devolverse tal cual, llegó %v", err)
	}
}

// La memoria de la lectura no crece con el nº de entradas: el recorder suelta lo ya entregado.
func TestMemoriaConstanteEnPaginasGrandes(t *testing.T) {
	var sb strings.Builder
	sb.WriteString(cabeceraMinima)
	for i := 0; i < 2000; i++ {
		sb.WriteString(entradaMinima(`<cbc:ContractFolderStatusCode>PUB</cbc:ContractFolderStatusCode>`))
	}
	sb.WriteString(`</feed>`)
	n := 0
	// Con un tope de 16 KiB por entrada, la página (varios cientos de KiB) solo pasa si se descarta lo ya entregado.
	if _, err := ParseFeed(strings.NewReader(sb.String()), Options{Source: domain.SourcePLACSP643, MaxEntryBytes: 16 << 10}, func(Record) error { n++; return nil }); err != nil {
		t.Fatal(err)
	}
	if n != 2000 {
		t.Fatalf("entradas = %d, quería 2000", n)
	}
}
