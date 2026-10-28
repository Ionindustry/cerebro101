// Package domain define el modelo normalizado del motor, independiente de la fuente (PLACSP, TED, Cataluña).
//
// Reglas (NORMAS): los importes llevan siempre moneda y significado (el nombre del campo dice si es con o sin IVA,
// presupuesto base o valor estimado); los organismos y las empresas se identifican por NIF o DIR3, nunca por nombre;
// no se guardan datos de contacto de personas.
package domain

import "time"

// Fuentes de PLACSP (sindicaciones de la Plataforma de Contratación del Sector Público).
const (
	SourcePLACSP643  = "placsp-643"  // perfiles del contratante, sin menores
	SourcePLACSP1044 = "placsp-1044" // plataformas agregadas, sin menores (incluye Cataluña)
	SourcePLACSP1143 = "placsp-1143" // contratos menores de perfiles alojados en PLACSP
)

// Date es una fecha sin hora, «AAAA-MM-DD».
type Date string

// Money es un importe decimal con su moneda. Value conserva los decimales de origen sin pasar por coma flotante.
type Money struct {
	Value    string `json:"value"`    // «481075» o «582100.75»
	Currency string `json:"currency"` // «EUR»
}

// Licitacion es un expediente de contratación tal como lo publica una fuente, con sus lotes y resultados.
type Licitacion struct {
	Source    string    `json:"source"`
	SourceID  string    `json:"source_id"`  // identificador de origen completo (atom:id)
	NumericID string    `json:"numeric_id"` // último tramo numérico de SourceID, estable por expediente
	Link      string    `json:"link"`
	Updated   time.Time `json:"updated"` // atom:updated: la versión más reciente de la entrada gana

	Expediente     string `json:"expediente"`
	Status         string `json:"status"` // PRE, PUB, EV, ADJ, RES, ANUL (SyndicationContractFolderStatusCode)
	TEDProcedureID string `json:"ted_procedure_id,omitempty"`

	Organism Organization `json:"organism"`

	Title           string `json:"title"`
	ContractType    string `json:"contract_type,omitempty"`     // ContractCode: 1 suministros, 2 servicios, 3 obras…
	ContractSubType string `json:"contract_sub_type,omitempty"` //
	Procedure       string `json:"procedure,omitempty"`         // SyndicationTenderingProcessCode
	Urgency         string `json:"urgency,omitempty"`           // DiligenceTypeCode
	System          string `json:"system,omitempty"`            // ContractingSystemTypeCode (acuerdo marco, SDA…)
	OverThreshold   *bool  `json:"over_threshold,omitempty"`
	Funding         string `json:"funding,omitempty"` // FundingProgramCode

	EstimatedValue    *Money `json:"estimated_value,omitempty"`      // valor estimado del contrato
	BaseBudgetExclVAT *Money `json:"base_budget_excl_vat,omitempty"` // presupuesto base de licitación sin IVA
	BaseBudgetInclVAT *Money `json:"base_budget_incl_vat,omitempty"` // presupuesto base de licitación con IVA

	CPV  []string `json:"cpv,omitempty"`  // 8 dígitos, sin dígito de control
	NUTS []string `json:"nuts,omitempty"` // niveles mezclados: ES, ES51, ES511…

	Duration       *Duration  `json:"duration,omitempty"`
	Extension      *Extension `json:"extension,omitempty"` // prórrogas previstas del contrato
	TenderDeadline *time.Time `json:"tender_deadline,omitempty"`

	Notices       []Notice         `json:"notices,omitempty"`
	Criteria      []AwardCriterion `json:"criteria,omitempty"`
	Lots          []Lot            `json:"lots,omitempty"`
	Results       []Result         `json:"results,omitempty"`
	Modifications []Modification   `json:"modifications,omitempty"`
	Documents     []Document       `json:"documents,omitempty"`

	// Warnings son problemas de calidad de datos que no impiden usar el registro (importe ilegible, fecha rara…).
	Warnings []string `json:"warnings,omitempty"`
}

// Organization es el órgano de contratación. Sin datos de contacto.
type Organization struct {
	Name         string   `json:"name,omitempty"`
	NIF          string   `json:"nif,omitempty"`
	DIR3         string   `json:"dir3,omitempty"`
	PlatformID   string   `json:"platform_id,omitempty"` // ID_PLATAFORMA (643, 1143) o ID_OC_PLAT (1044)
	PartyType    string   `json:"party_type,omitempty"`  // ContractingAuthorityCode
	Activities   []string `json:"activities,omitempty"`
	Parents      []string `json:"parents,omitempty"` // nombres de la jerarquía, de abajo arriba
	AggregatorID string   `json:"aggregator_id,omitempty"`
}

// Duration es la duración prevista; Unit es el código de origen (DAY, MON, ANN).
type Duration struct {
	Value string `json:"value"`
	Unit  string `json:"unit"`
}

// Extension son las prórrogas que prevé el pliego. Text es el texto libre de origen (lo único seguro); Count, Each y Allowed solo se rellenan
// cuando el texto lo dice con claridad: «tres (3) prórrogas de un (1) año cada una», «Número de prórrogas: 1 / Duración máxima de cada prórroga: 2 años».
type Extension struct {
	Text    string    `json:"text"`
	Allowed *bool     `json:"allowed,omitempty"` // true si se admiten, false si el texto dice que no; ausente si no se sabe
	Count   int       `json:"count,omitempty"`
	Each    *Duration `json:"each,omitempty"`
}

// Notice es una publicación del expediente (anuncio de licitación, de adjudicación, de formalización…).
type Notice struct {
	Type        string `json:"type"`                   // DOC_CN, DOC_CAN_ADJ, DOC_FORM, DESISTIMIENTO…
	PublishedOn Date   `json:"published_on,omitempty"` //
	Media       string `json:"media,omitempty"`        // «Perfil del contratante», «DOUE»…
}

// AwardCriterion es un criterio de adjudicación. Type: OBJ (automático) o SUBJ (juicio de valor).
type AwardCriterion struct {
	Type        string `json:"type"`
	SubType     string `json:"sub_type,omitempty"`
	Description string `json:"description,omitempty"`
	Weight      string `json:"weight,omitempty"`
}

// Lot es un lote del expediente. En la fuente 1044 solo vienen el identificador y el nombre.
type Lot struct {
	ID                string     `json:"id"`
	Name              string     `json:"name,omitempty"`
	BaseBudgetExclVAT *Money     `json:"base_budget_excl_vat,omitempty"`
	BaseBudgetInclVAT *Money     `json:"base_budget_incl_vat,omitempty"`
	CPV               []string   `json:"cpv,omitempty"`
	NUTS              []string   `json:"nuts,omitempty"`
	Duration          *Duration  `json:"duration,omitempty"`  // la del lote, si el lote la trae (manda sobre la del expediente)
	Extension         *Extension `json:"extension,omitempty"` // ídem
}

// Códigos de resultado de una licitación (TenderResultCode-2.09); en las muestras solo se han visto estos.
const (
	ResultAwarded    = "8" // adjudicado
	ResultFormalized = "9" // formalizado
	ResultVoid       = "3" // desierto
	ResultWithdrawn  = "4" // desistimiento
	ResultRenounced  = "5" // renuncia
)

// Result es el resultado de un lote para un adjudicatario (hay uno por lote y por adjudicatario).
type Result struct {
	LotID       string `json:"lot_id,omitempty"`
	Code        string `json:"code"`
	Description string `json:"description,omitempty"`

	WinnerName   string `json:"winner_name,omitempty"`
	WinnerID     string `json:"winner_id,omitempty"`        // NIF, UTE u otro identificador
	WinnerScheme string `json:"winner_id_scheme,omitempty"` // NIF, UTE, OTROS
	WinnerIsSME  *bool  `json:"winner_is_sme,omitempty"`

	AwardedExclVAT *Money `json:"awarded_excl_vat,omitempty"` // importe adjudicado sin IVA
	AwardedInclVAT *Money `json:"awarded_incl_vat,omitempty"` // importe adjudicado con IVA
	LowestOffer    *Money `json:"lowest_offer,omitempty"`     // POR VERIFICAR si incluye IVA
	HighestOffer   *Money `json:"highest_offer,omitempty"`    // POR VERIFICAR si incluye IVA

	TendersReceived *int  `json:"tenders_received,omitempty"`
	AbnormallyLow   *bool `json:"abnormally_low,omitempty"` // se excluyeron ofertas por anormalmente bajas

	AwardDate        Date   `json:"award_date,omitempty"`
	FormalizedOn     Date   `json:"formalized_on,omitempty"`
	ContractNumber   string `json:"contract_number,omitempty"`
	ContractStartsOn Date   `json:"contract_starts_on,omitempty"`
}

// Modification es una modificación del contrato (las prórrogas ejecutadas llegan como modificaciones con nota PRORROGA).
type Modification struct {
	ID            string `json:"id,omitempty"`
	ContractID    string `json:"contract_id,omitempty"`
	Note          string `json:"note,omitempty"`
	AmountExclVAT *Money `json:"amount_excl_vat,omitempty"` // importe de la modificación
	FinalExclVAT  *Money `json:"final_excl_vat,omitempty"`  // importe del contrato tras modificar
}

// Document es una referencia a un documento del expediente (pliegos). Solo la referencia: nunca se descarga aquí.
type Document struct {
	Kind string `json:"kind"` // legal, technical, additional
	Name string `json:"name,omitempty"`
	URI  string `json:"uri,omitempty"`
	Hash string `json:"hash,omitempty"` // DocumentHash de origen (base64)
}

// Baja es una entrada retirada de la sindicación (at:deleted-entry).
type Baja struct {
	Source string    `json:"source"`
	Ref    string    `json:"ref"`
	When   time.Time `json:"when"`
	Kind   string    `json:"kind"` // ANULADA o CERRADA
}
