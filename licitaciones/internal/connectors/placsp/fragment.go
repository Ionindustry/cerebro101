package placsp

import (
	"bytes"
	"errors"
	"fmt"
)

// ErrNotOneEntry se devuelve si el fragmento no contiene exactamente una entrada.
var ErrNotOneEntry = errors.New("placsp: el fragmento no contiene exactamente una entrada")

// ParseFragment vuelve a leer un original guardado (el fragmento exacto de una entrada, tal como lo devuelve Record.Raw) y devuelve el mismo
// registro que dio la página. Es lo que usan los proyectores: parten del original en el almacén, no de la página. Los mismos límites y
// garantías que ParseFeed (sin DTD, sin entidades).
func ParseFragment(raw []byte, opt Options) (Record, error) {
	doc := make([]byte, 0, len(raw)+16)
	doc = append(append(append(doc, "<feed>"...), raw...), "</feed>"...)
	var out []Record
	if _, err := ParseFeed(bytes.NewReader(doc), opt, func(r Record) error { out = append(out, r); return nil }); err != nil {
		return Record{}, fmt.Errorf("placsp: leer el fragmento: %w", err)
	}
	if len(out) != 1 {
		return Record{}, fmt.Errorf("%w (hay %d)", ErrNotOneEntry, len(out))
	}
	return out[0], nil
}
