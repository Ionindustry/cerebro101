package api

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/url"
	"sort"
	"strings"
	"time"
)

// cursorTTL es lo que dura un cursor (contrato: 24 h).
const cursorTTL = 24 * time.Hour

type cursorData struct {
	K string `json:"k"` // clave de ordenación del último elemento servido
	I string `json:"i"` // su identificador
	F string `json:"f"` // huella de los filtros de la consulta
	E int64  `json:"e"` // caducidad (unix)
}

var b64 = base64.RawURLEncoding

// encodeCursor firma el cursor con HMAC-SHA256: opaco para el cliente y no manipulable.
func encodeCursor(key []byte, c cursorData) string {
	body, _ := json.Marshal(c)
	p := b64.EncodeToString(body)
	return p + "." + b64.EncodeToString(sign(key, p))
}

var errCursor = errors.New("cursor no válido")

// decodeCursor comprueba firma, caducidad y que pertenezca a esta misma consulta (huella de filtros).
func decodeCursor(key []byte, s, huella string, now time.Time) (cursorData, error) {
	var c cursorData
	p, sig, ok := strings.Cut(s, ".")
	if !ok {
		return c, errCursor
	}
	got, err := b64.DecodeString(sig)
	if err != nil || !hmac.Equal(got, sign(key, p)) {
		return c, errCursor
	}
	body, err := b64.DecodeString(p)
	if err != nil || json.Unmarshal(body, &c) != nil {
		return c, errCursor
	}
	if now.Unix() > c.E || c.F != huella || c.K == "" || c.I == "" {
		return cursorData{}, errCursor
	}
	return c, nil
}

func sign(key []byte, p string) []byte {
	m := hmac.New(sha256.New, key)
	m.Write([]byte(p))
	return m.Sum(nil)
}

// huellaFiltros resume los parámetros de la consulta que definen sus resultados (todos menos cursor y limit, que pueden cambiar entre páginas).
func huellaFiltros(q url.Values) string {
	var parts []string
	for k, vs := range q {
		if k == "cursor" || k == "limit" {
			continue
		}
		vs = append([]string(nil), vs...)
		sort.Strings(vs)
		parts = append(parts, k+"="+strings.Join(vs, "\x1f"))
	}
	sort.Strings(parts)
	h := sha256.Sum256([]byte(strings.Join(parts, "\x1e")))
	return b64.EncodeToString(h[:12])
}
