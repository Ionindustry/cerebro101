package ingest

import "time"

// View es lo que se recuerda de un expediente entre ejecuciones (la «vista» del ADR 0003): basta para decidir sin leer el registro completo.
type View struct {
	Version int // versión de la entidad, monótona; la asigna el ingestor (único escritor)
	Hash    string
	Updated time.Time // atom:updated de la última versión vista
	Flags   Flags
}

// Decision es la decisión sobre una observación: qué es, la vista resultante y el tipo de evento (vacío si no hay cambio).
type Decision struct {
	Kind      Kind
	Write     bool // la vista debe guardarse (nueva, modificada o sin cambios con fecha más reciente)
	View      View // vista resultante, válida si Write
	EventType string
}

// Decide aplica la regla de la ingesta (ADR 0003, paso 4) a una observación sobre lo que había (prev, nil si el expediente es nuevo).
// Es una función pura: la usan por igual el almacén en memoria y el de Postgres.
func Decide(prev *View, o Observation) Decision {
	if o.Removed {
		if prev == nil || prev.Flags&FlagAnnulled != 0 {
			return Decision{Kind: KindUnchanged} // baja de algo desconocido o ya anulado
		}
		v := *prev
		v.Version++
		v.Flags |= FlagAnnulled
		return Decision{Kind: KindModified, Write: true, View: v, EventType: "licitacion.anulada"}
	}
	if prev == nil {
		return Decision{Kind: KindNew, Write: true, View: View{Version: 1, Hash: o.Hash, Updated: o.Updated, Flags: o.Flags}, EventType: "licitacion.nueva"}
	}
	if o.Updated.Before(prev.Updated) {
		return Decision{Kind: KindStale}
	}
	if o.Hash == prev.Hash {
		v := *prev
		v.Updated = o.Updated // el contenido no cambió; se recuerda la fecha más reciente
		return Decision{Kind: KindUnchanged, Write: true, View: v}
	}
	nuevas := o.Flags &^ prev.Flags
	v := View{Version: prev.Version + 1, Hash: o.Hash, Updated: o.Updated, Flags: prev.Flags | o.Flags}
	typ := "licitacion.modificada"
	switch {
	case nuevas&FlagAnnulled != 0:
		typ = "licitacion.anulada"
	case nuevas&FlagFormalized != 0:
		typ = "licitacion.formalizada"
	case nuevas&FlagAwarded != 0:
		typ = "licitacion.adjudicada"
	}
	return Decision{Kind: KindModified, Write: true, View: v, EventType: typ}
}

// NewEvent construye el evento de una decisión con identificador determinista.
func NewEvent(typ string, o Observation, version int) Event {
	return Event{ID: eventID(typ, o.Source, o.SourceID, version), Type: typ, Source: o.Source, SourceID: o.SourceID,
		Version: version, RawSHA256: o.RawSHA256, RawKey: o.RawKey}
}

// Outcome construye el resultado público de una decisión.
func (d Decision) Outcome(o Observation) Outcome {
	out := Outcome{Kind: d.Kind, Version: d.View.Version}
	if d.EventType != "" {
		e := NewEvent(d.EventType, o, d.View.Version)
		out.Event = &e
	}
	return out
}
