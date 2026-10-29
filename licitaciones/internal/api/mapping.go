package api

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"strconv"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

// Importe es un importe con moneda, impuestos y significado (NORMAS: nunca un número suelto).
type Importe struct {
	Valor       string `json:"valor"`
	Moneda      string `json:"moneda"`
	Impuestos   string `json:"impuestos"`
	Significado string `json:"significado"`
}

// OrganizacionRef es la referencia a un organismo o empresa. El id es un UUID estable (v8) derivado del NIF (o DIR3, o el nombre).
type OrganizacionRef struct {
	ID     string  `json:"id"`
	Nombre string  `json:"nombre"`
	NIF    *string `json:"nif"`
	DIR3   *string `json:"dir3"`
}

// Resumen es LicitacionResumen del contrato.
type Resumen struct {
	ID                string           `json:"id"`
	Expediente        string           `json:"expediente,omitempty"`
	Titulo            string           `json:"titulo"`
	Comprador         *OrganizacionRef `json:"comprador,omitempty"`
	CPV               []string         `json:"cpv"`
	NUTS              []string         `json:"nuts"`
	Procedimiento     string           `json:"procedimiento,omitempty"`
	Estado            string           `json:"estado"`
	Importe           *Importe         `json:"importe,omitempty"`
	ActualizadaEn     time.Time        `json:"actualizada_en"`
	PlazoPresentacion *time.Time       `json:"plazo_presentacion"`
	Fuentes           []string         `json:"fuentes"`
	URLOrigen         string           `json:"url_origen,omitempty"`
	VersionEntidad    int              `json:"version_entidad"`
	Cercania          *float64         `json:"cercania,omitempty"` // 0 a 1: cuánto se parece a lo buscado (solo búsqueda por significado y «parecidas»)
	Motivos           []string         `json:"motivos,omitempty"`  // solo «parecidas»: mismo_comprador, cpv_comun
}

// uuid8 deriva un UUID v8 (RFC 9562, uso propio) estable del nombre con SHA-256: el mismo nombre da siempre el mismo identificador.
func uuid8(name string) string {
	h := sha256.Sum256([]byte("licitaciones.101.cat|" + name))
	s := h[:16]
	s[6] = (s[6] & 0x0f) | 0x80
	s[8] = (s[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", s[0:4], s[4:6], s[6:8], s[8:10], s[10:16])
}

func orgRef(nombre, nif, dir3 string) *OrganizacionRef {
	clave := nif
	if clave == "" {
		clave = dir3
	}
	if clave == "" {
		clave = nombre
	}
	if clave == "" {
		return nil
	}
	o := &OrganizacionRef{ID: uuid8("org:" + clave), Nombre: nombre}
	if nif != "" {
		o.NIF = &nif
	}
	if dir3 != "" {
		o.DIR3 = &dir3
	}
	return o
}

func resumen(f pg.Fila) Resumen {
	r := Resumen{
		ID: f.ID, Expediente: f.Expediente, Titulo: f.Titulo, Comprador: orgRef(f.CompradorNombre, f.CompradorNIF, f.CompradorDIR3),
		CPV: nonNil(f.CPV), NUTS: nonNil(f.NUTS), Procedimiento: f.Procedimiento, Estado: f.Estado, ActualizadaEn: f.Actualizada.UTC(),
		PlazoPresentacion: f.Plazo, Fuentes: []string{fuenteExterna(f.Fuente)}, URLOrigen: f.Enlace, VersionEntidad: f.Version,
	}
	if f.Valor != nil {
		// El valor estimado de un contrato público no incluye IVA (LCSP art. 101).
		r.Importe = &Importe{Valor: trimDecimal(*f.Valor), Moneda: f.Moneda, Impuestos: "sin_iva", Significado: "valor_estimado"}
	}
	return r
}

func nonNil(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}

// trimDecimal quita ceros de más de numeric(18,4) («125000.5000» → «125000.50»), dejando al menos 2 decimales como en el contrato.
func trimDecimal(v string) string {
	dot := -1
	for i, c := range v {
		if c == '.' {
			dot = i
		}
	}
	if dot < 0 {
		return v + ".00"
	}
	end := len(v)
	for end > dot+3 && v[end-1] == '0' {
		end--
	}
	if end == dot+2 {
		return v[:end] + "0"
	}
	return v[:end]
}

// Ficha es LicitacionFicha del contrato (lo que se sabe hoy del expediente).
type Ficha struct {
	Resumen
	EstadoOrigen string         `json:"estado_origen,omitempty"`
	Lotes        []Lote         `json:"lotes"`
	Importes     []Importe      `json:"importes"`
	Plazos       Plazos         `json:"plazos"`
	Criterios    []Criterio     `json:"criterios"`
	Documentos   []Documento    `json:"documentos"`
	Adjudicacion []Adjudicacion `json:"adjudicaciones"`
	Evidencia    Evidencia      `json:"evidencia"`
}

// Lote es Lote del contrato.
type Lote struct {
	Numero   string    `json:"numero"`
	Objeto   string    `json:"objeto,omitempty"`
	CPV      []string  `json:"cpv"`
	NUTS     []string  `json:"nuts"`
	Importes []Importe `json:"importes"`
}

// Plazos son las fechas del expediente que se conocen hoy.
type Plazos struct {
	Presentacion *time.Time `json:"presentacion"`
}

// Criterio es un criterio de adjudicación.
type Criterio struct {
	Descripcion string   `json:"descripcion,omitempty"`
	Tipo        string   `json:"tipo"`
	Peso        *float64 `json:"peso"`
}

// Documento es la referencia a un documento del expediente (nunca se descarga aquí).
type Documento struct {
	Nombre     string `json:"nombre"`
	Tipo       string `json:"tipo,omitempty"`
	URLOrigen  string `json:"url_origen"`
	Descargado bool   `json:"descargado"`
}

// Adjudicacion es Adjudicacion del contrato (una por lote y adjudicatario).
type Adjudicacion struct {
	ID                 string           `json:"id"`
	LicitacionID       string           `json:"licitacion_id"`
	Expediente         string           `json:"expediente,omitempty"`
	Titulo             string           `json:"titulo,omitempty"`
	Lote               string           `json:"lote"`
	Resultado          string           `json:"resultado"`
	Adjudicatario      *OrganizacionRef `json:"adjudicatario,omitempty"`
	Importes           []Importe        `json:"importes"`
	Baja               *float64         `json:"baja"`
	OfertasRecibidas   *int             `json:"ofertas_recibidas"`
	BajaAnormal        *bool            `json:"baja_anormal"`
	FechaAdjudicacion  *string          `json:"fecha_adjudicacion"`
	FechaFormalizacion *string          `json:"fecha_formalizacion"`
}

// Evidencia es Evidencia del contrato: dónde está el original y cómo se obtuvo.
type Evidencia struct {
	Fuente        string    `json:"fuente"`
	IDOrigen      string    `json:"id_origen"`
	URLOrigen     string    `json:"url_origen,omitempty"`
	CapturadoEn   time.Time `json:"capturado_en"`
	SHA256        string    `json:"sha256"`
	ClaveRaw      string    `json:"clave_raw"`
	VersionParser string    `json:"version_parser"`
}

func money(m *domain.Money, impuestos, significado string) *Importe {
	if m == nil || m.Value == "" {
		return nil
	}
	cur := m.Currency
	if len(cur) != 3 {
		cur = "EUR"
	}
	return &Importe{Valor: m.Value, Moneda: cur, Impuestos: impuestos, Significado: significado}
}

func importes(ms ...*Importe) []Importe {
	out := []Importe{}
	for _, m := range ms {
		if m != nil {
			out = append(out, *m)
		}
	}
	return out
}

func tipoCriterio(c domain.AwardCriterion) string {
	// POR VERIFICAR con la lista de subtipos: de momento solo se distingue el juicio de valor; el precio no se separa del resto de lo automático.
	if c.Type == "SUBJ" {
		return "calidad_juicio_valor"
	}
	return "otro"
}

func ficha(f pg.Fila) (Ficha, error) {
	var l domain.Licitacion
	if err := json.Unmarshal(f.Documento, &l); err != nil {
		return Ficha{}, fmt.Errorf("leer el registro del expediente: %w", err)
	}
	out := Ficha{
		Resumen: resumen(f), EstadoOrigen: f.EstadoOrigen, Plazos: Plazos{Presentacion: f.Plazo},
		Lotes: []Lote{}, Criterios: []Criterio{}, Documentos: []Documento{}, Adjudicacion: []Adjudicacion{},
		Importes: importes(money(l.EstimatedValue, "sin_iva", "valor_estimado"), money(l.BaseBudgetExclVAT, "sin_iva", "presupuesto_base"),
			money(l.BaseBudgetInclVAT, "con_iva", "presupuesto_base")),
		Evidencia: Evidencia{Fuente: fuenteExterna(f.Fuente), IDOrigen: f.IDOrigen, URLOrigen: f.Enlace, CapturadoEn: f.Capturado.UTC(),
			SHA256: f.SHA256, ClaveRaw: f.ClaveRaw, VersionParser: ingest.ParserVersion},
	}
	budgets := map[string]*domain.Money{}
	for _, lot := range l.Lots {
		budgets[lot.ID] = lot.BaseBudgetExclVAT
		out.Lotes = append(out.Lotes, Lote{Numero: lot.ID, Objeto: lot.Name, CPV: nonNil(lot.CPV), NUTS: nonNil(lot.NUTS),
			Importes: importes(money(lot.BaseBudgetExclVAT, "sin_iva", "presupuesto_base"), money(lot.BaseBudgetInclVAT, "con_iva", "presupuesto_base"))})
	}
	for _, c := range l.Criteria {
		cr := Criterio{Descripcion: c.Description, Tipo: tipoCriterio(c)}
		if w, err := strconv.ParseFloat(c.Weight, 64); err == nil {
			cr.Peso = &w
		}
		out.Criterios = append(out.Criterios, cr)
	}
	for _, d := range l.Documents {
		if d.URI == "" {
			continue
		}
		tipo := map[string]string{"legal": "pliego_administrativo", "technical": "pliego_tecnico"}[d.Kind]
		out.Documentos = append(out.Documentos, Documento{Nombre: d.Name, Tipo: tipo, URLOrigen: d.URI})
	}
	for i, r := range l.Results {
		out.Adjudicacion = append(out.Adjudicacion, adjudicacion(f, l, r, i, budgets[r.LotID]))
	}
	return out, nil
}

func adjudicacion(f pg.Fila, l domain.Licitacion, r domain.Result, i int, presupuesto *domain.Money) Adjudicacion {
	resultado := "adjudicado"
	if r.Code != domain.ResultAwarded && r.Code != domain.ResultFormalized {
		resultado = "desierto"
	}
	lote := r.LotID
	if lote == "" {
		lote = "1"
	}
	a := Adjudicacion{
		ID: uuid8(fmt.Sprintf("adj:%s|%d", f.ID, i+1)), LicitacionID: f.ID, Expediente: f.Expediente, Titulo: f.Titulo, Lote: lote,
		Resultado: resultado, Importes: importes(money(r.AwardedExclVAT, "sin_iva", "adjudicado"), money(r.AwardedInclVAT, "con_iva", "adjudicado"),
			money(r.LowestOffer, "desconocido", "oferta_mas_baja"), money(r.HighestOffer, "desconocido", "oferta_mas_alta")),
		OfertasRecibidas: r.TendersReceived, BajaAnormal: r.AbnormallyLow,
	}
	clave, nif := claveAdjudicatario(r)
	a.Adjudicatario = orgAdjudicatario(r.WinnerName, clave, nif)
	if r.AwardDate != "" {
		d := string(r.AwardDate)
		a.FechaAdjudicacion = &d
	}
	if r.FormalizedOn != "" {
		d := string(r.FormalizedOn)
		a.FechaFormalizacion = &d
	}
	if r.AwardedExclVAT != nil && presupuesto != nil {
		adj, e1 := strconv.ParseFloat(r.AwardedExclVAT.Value, 64)
		base, e2 := strconv.ParseFloat(presupuesto.Value, 64)
		if e1 == nil && e2 == nil && base > 0 {
			b := 1 - adj/base
			a.Baja = &b
		}
	}
	return a
}
