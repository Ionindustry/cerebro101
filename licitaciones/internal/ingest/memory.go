package ingest

import (
	"context"
	"fmt"
	"sync"
)

// MemRaw es un RawStore en memoria para pruebas y desarrollo.
type MemRaw struct {
	mu      sync.Mutex
	Objects map[string]RawObject
}

// NewMemRaw crea un almacén de originales vacío.
func NewMemRaw() *MemRaw { return &MemRaw{Objects: map[string]RawObject{}} }

// PutRaw guarda sin sobrescribir; si la clave ya existe con otro contenido es un error (la clave lleva el SHA-256: no debería pasar).
func (m *MemRaw) PutRaw(_ context.Context, o RawObject) (bool, error) {
	if o.SHA256 != sha256Hex(o.Data) {
		return false, fmt.Errorf("ingest: el SHA-256 de %s no corresponde a sus bytes", o.Key)
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if prev, ok := m.Objects[o.Key]; ok {
		if prev.SHA256 != o.SHA256 {
			return false, fmt.Errorf("ingest: la clave %s ya existe con otro contenido", o.Key)
		}
		return false, nil
	}
	cp := o
	cp.Data = append([]byte(nil), o.Data...)
	m.Objects[o.Key] = cp
	return true, nil
}

// Len devuelve cuántos originales hay.
func (m *MemRaw) Len() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return len(m.Objects)
}

type view struct {
	version int
	hash    string
	last    Observation
	flags   Flags
}

// MemState es un State en memoria con outbox, para pruebas y desarrollo.
type MemState struct {
	mu          sync.Mutex
	views       map[string]*view
	Outbox      []Event
	checkpoints map[string]Checkpoint
}

// NewMemState crea un estado vacío.
func NewMemState() *MemState {
	return &MemState{views: map[string]*view{}, checkpoints: map[string]Checkpoint{}}
}

// Observe aplica la regla de la ingesta (ADR 0003, paso 4).
func (m *MemState) Observe(_ context.Context, o Observation) (Outcome, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	k := o.Source + "\x00" + o.SourceID
	v := m.views[k]

	if o.Removed {
		if v == nil || v.flags&FlagAnnulled != 0 {
			return Outcome{Kind: KindUnchanged}, nil // baja de algo desconocido o ya anulado
		}
		v.version++
		v.flags |= FlagAnnulled
		return m.emit(o, v, "licitacion.anulada", KindModified), nil
	}
	if v == nil {
		v = &view{version: 1, hash: o.Hash, last: o, flags: o.Flags}
		m.views[k] = v
		return m.emit(o, v, "licitacion.nueva", KindNew), nil
	}
	if o.Updated.Before(v.last.Updated) {
		return Outcome{Kind: KindStale, Version: v.version}, nil
	}
	if o.Hash == v.hash {
		v.last = o // se recuerda la fecha más reciente; el contenido no cambió
		return Outcome{Kind: KindUnchanged, Version: v.version}, nil
	}
	nuevas := o.Flags &^ v.flags
	v.version++
	v.hash, v.last, v.flags = o.Hash, o, v.flags|o.Flags
	typ := "licitacion.modificada"
	switch {
	case nuevas&FlagAnnulled != 0:
		typ = "licitacion.anulada"
	case nuevas&FlagFormalized != 0:
		typ = "licitacion.formalizada"
	case nuevas&FlagAwarded != 0:
		typ = "licitacion.adjudicada"
	}
	return m.emit(o, v, typ, KindModified), nil
}

func (m *MemState) emit(o Observation, v *view, typ string, kind Kind) Outcome {
	e := Event{ID: eventID(typ, o.Source, o.SourceID, v.version), Type: typ, Source: o.Source, SourceID: o.SourceID,
		Version: v.version, RawSHA256: o.RawSHA256, RawKey: o.RawKey}
	m.Outbox = append(m.Outbox, e)
	return Outcome{Kind: kind, Version: v.version, Event: &e}
}

// Checkpoint devuelve el punto de control de una fuente (vacío si no hay).
func (m *MemState) Checkpoint(_ context.Context, source string) (Checkpoint, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.checkpoints[source], nil
}

// SaveCheckpoint guarda el punto de control de una fuente.
func (m *MemState) SaveCheckpoint(_ context.Context, source string, c Checkpoint) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.checkpoints[source] = c
	return nil
}

// Events devuelve una copia del outbox.
func (m *MemState) Events() []Event {
	m.mu.Lock()
	defer m.mu.Unlock()
	return append([]Event(nil), m.Outbox...)
}
