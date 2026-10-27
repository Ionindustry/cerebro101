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

// GetRaw lee un original guardado (para las pruebas de los proyectores).
func (m *MemRaw) GetRaw(_ context.Context, key string) ([]byte, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	o, ok := m.Objects[key]
	if !ok {
		return nil, fmt.Errorf("no existe %s", key)
	}
	return o.Data, nil
}

// Len devuelve cuántos originales hay.
func (m *MemRaw) Len() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return len(m.Objects)
}

// MemState es un State en memoria con outbox, para pruebas y desarrollo.
type MemState struct {
	mu          sync.Mutex
	views       map[string]View
	Outbox      []Event
	checkpoints map[string]Checkpoint
}

// NewMemState crea un estado vacío.
func NewMemState() *MemState {
	return &MemState{views: map[string]View{}, checkpoints: map[string]Checkpoint{}}
}

// Observe aplica la regla de la ingesta (Decide) sobre la memoria.
func (m *MemState) Observe(_ context.Context, o Observation) (Outcome, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	k := o.Source + "\x00" + o.SourceID
	var prev *View
	if v, ok := m.views[k]; ok {
		prev = &v
	}
	d := Decide(prev, o)
	if d.Write {
		m.views[k] = d.View
	}
	out := d.Outcome(o)
	if out.Event != nil {
		m.Outbox = append(m.Outbox, *out.Event)
	}
	if d.Kind == KindStale && prev != nil {
		out.Version = prev.Version
	}
	return out, nil
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
