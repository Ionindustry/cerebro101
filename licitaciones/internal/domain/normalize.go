package domain

// Estados normalizados de una licitación (los del contrato de la API: EstadoLicitacion).
const (
	EstadoAnuncioPrevio = "anuncio_previo"
	EstadoAbierta       = "abierta"
	EstadoCerrada       = "cerrada" // plazo terminado, pendiente de adjudicar
	EstadoAdjudicada    = "adjudicada"
	EstadoFormalizada   = "formalizada"
	EstadoAnulada       = "anulada"
	EstadoDesierta      = "desierta"
)

// Estado normaliza el estado de un expediente. Manda lo que dicen los resultados (formalizado > adjudicado > desierto) y después el código de
// la sindicación (PRE, PUB, EV, ADJ, RES, ANUL). El mapeo de RES («Resuelta») a adjudicada es POR VERIFICAR con el corpus completo.
func (l *Licitacion) Estado() string {
	if l.Status == "ANUL" {
		return EstadoAnulada
	}
	var awarded, formalized, void bool
	for _, r := range l.Results {
		switch r.Code {
		case ResultFormalized:
			formalized = true
		case ResultAwarded:
			awarded = true
		case ResultVoid, ResultWithdrawn, ResultRenounced:
			void = true
		}
	}
	switch {
	case formalized:
		return EstadoFormalizada
	case awarded:
		return EstadoAdjudicada
	case void:
		return EstadoDesierta
	}
	switch l.Status {
	case "PRE":
		return EstadoAnuncioPrevio
	case "PUB":
		return EstadoAbierta
	case "EV":
		return EstadoCerrada
	case "ADJ", "RES":
		return EstadoAdjudicada
	}
	return EstadoAbierta
}

// Procedimientos normalizados (los del contrato de la API: Procedimiento).
var procedimientos = map[string]string{
	"1": "abierto", "2": "restringido", "3": "negociado_sin_publicidad", "4": "negociado_con_publicidad", "5": "dialogo_competitivo",
	"6": "menor", "7": "basado_en_acuerdo_marco", "9": "abierto_simplificado", "10": "asociacion_innovacion",
	"12": "basado_en_acuerdo_marco", "13": "licitacion_con_negociacion",
}

// ProcedimientoNormalizado traduce el código SyndicationTenderingProcessCode; lo que no conoce es «otro». El 9 de PLACSP es el abierto
// simplificado sin distinguir el abreviado (POR VERIFICAR si hace falta separarlo).
func ProcedimientoNormalizado(code string) string {
	if v, ok := procedimientos[code]; ok {
		return v
	}
	if code == "" {
		return ""
	}
	return "otro"
}
