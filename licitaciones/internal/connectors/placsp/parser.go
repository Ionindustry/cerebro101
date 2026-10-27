// Package placsp lee las sindicaciones de la Plataforma de Contratación del Sector Público (Atom + CODICE) y las convierte al modelo del
// motor. Fuentes: 643 (perfiles), 1044 (agregadas) y 1143 (contratos menores).
//
// El parser trata el XML como hostil (NORMAS): lee en streaming sin cargar la página entera, rechaza DTD y entidades, solo admite UTF-8,
// y limita el tamaño de cada entrada y de toda la página. Cada entrada se entrega con su fragmento original y su SHA-256, que es la
// evidencia que se guarda (ADR 0004): repetir una ingesta con el mismo contenido da el mismo hash.
package placsp

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"time"
	_ "time/tzdata" // zona Europe/Madrid también en la imagen distroless, que no trae base de zonas horarias

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
)

// Límites por defecto.
const (
	DefaultMaxEntryBytes = 4 << 20   // una entrada sola, con todos sus lotes y resultados
	DefaultMaxFeedBytes  = 256 << 20 // una página de la sindicación
)

// Errores que identifican la causa de un rechazo.
var (
	ErrDTD           = errors.New("placsp: el documento lleva DTD o entidades; no se admite")
	ErrEntryTooLarge = errors.New("placsp: entrada demasiado grande")
	ErrFeedTooLarge  = errors.New("placsp: página demasiado grande")
	ErrNoFeed        = errors.New("placsp: el documento no es una sindicación Atom (falta <feed>)")
)

// Options configura la lectura. Source es obligatorio (domain.SourcePLACSP643, 1044 o 1143).
type Options struct {
	Source        string
	MaxEntryBytes int
	MaxFeedBytes  int64
}

// Feed son los metadatos de la página.
type Feed struct {
	ID      string
	Self    string
	Next    string // página anterior en el tiempo (la sindicación va en orden descendente)
	Updated time.Time
}

// Record es una entrada de la página: una licitación o una baja, con su fragmento original.
type Record struct {
	Licitacion *domain.Licitacion
	Baja       *domain.Baja
	Raw        []byte // fragmento XML exacto de la entrada
	RawSHA256  string // SHA-256 de Raw, en hexadecimal
}

// ParseFeed lee una página y llama a fn por cada entrada, en el orden del documento. Si fn devuelve un error, la lectura se detiene y se
// devuelve ese error. Un XML mal formado, con DTD o por encima de los límites devuelve error; los problemas de calidad de un registro
// (importe ilegible, fecha rara) no lo detienen: quedan en Licitacion.Warnings.
func ParseFeed(r io.Reader, opt Options, fn func(Record) error) (Feed, error) {
	if opt.Source == "" {
		return Feed{}, errors.New("placsp: falta la fuente (Options.Source)")
	}
	if opt.MaxEntryBytes <= 0 {
		opt.MaxEntryBytes = DefaultMaxEntryBytes
	}
	if opt.MaxFeedBytes <= 0 {
		opt.MaxFeedBytes = DefaultMaxFeedBytes
	}
	madrid, err := time.LoadLocation("Europe/Madrid")
	if err != nil {
		return Feed{}, fmt.Errorf("placsp: zona horaria: %w", err)
	}

	rec := &recorder{r: &limitReader{r: r, left: opt.MaxFeedBytes}, max: opt.MaxEntryBytes}
	dec := xml.NewDecoder(rec)
	dec.Strict = true // sin CharsetReader: solo UTF-8

	var (
		feed    Feed
		depth   int // elementos abiertos antes del token actual
		sawFeed bool
	)
	for {
		start := dec.InputOffset()
		if depth <= 1 {
			rec.trim(start)
		}
		tok, err := dec.Token()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return feed, readError(err)
		}
		switch t := tok.(type) {
		case xml.Directive:
			return feed, ErrDTD
		case xml.EndElement:
			depth--
		case xml.StartElement:
			if depth == 0 {
				if t.Name.Local != "feed" {
					return feed, ErrNoFeed
				}
				sawFeed = true
				depth++
				continue
			}
			if depth != 1 {
				depth++
				continue
			}
			switch t.Name.Local {
			case "id":
				var s string
				if err := dec.DecodeElement(&s, &t); err != nil {
					return feed, readError(err)
				}
				feed.ID = s
			case "updated":
				var s string
				if err := dec.DecodeElement(&s, &t); err != nil {
					return feed, readError(err)
				}
				feed.Updated, _ = time.Parse(time.RFC3339Nano, s)
			case "link":
				var l xmlLink
				if err := dec.DecodeElement(&l, &t); err != nil {
					return feed, readError(err)
				}
				switch l.Rel {
				case "self":
					feed.Self = l.Href
				case "next":
					feed.Next = l.Href
				}
			case "entry":
				var e xmlEntry
				if err := dec.DecodeElement(&e, &t); err != nil {
					return feed, readError(err)
				}
				raw := rec.slice(start, dec.InputOffset())
				out := Record{Raw: raw, RawSHA256: hashHex(raw), Licitacion: e.toDomain(opt.Source, madrid)}
				if err := fn(out); err != nil {
					return feed, err
				}
			case "deleted-entry":
				var d xmlDeleted
				if err := dec.DecodeElement(&d, &t); err != nil {
					return feed, readError(err)
				}
				raw := rec.slice(start, dec.InputOffset())
				when, _ := time.Parse(time.RFC3339Nano, d.When)
				out := Record{Raw: raw, RawSHA256: hashHex(raw),
					Baja: &domain.Baja{Source: opt.Source, Ref: d.Ref, When: when, Kind: d.Comment.Type}}
				if err := fn(out); err != nil {
					return feed, err
				}
			default:
				depth++
			}
		}
	}
	if !sawFeed {
		return feed, ErrNoFeed
	}
	return feed, nil
}

func readError(err error) error {
	switch {
	case errors.Is(err, ErrEntryTooLarge), errors.Is(err, ErrFeedTooLarge):
		return err
	}
	return fmt.Errorf("placsp: XML no válido: %w", err)
}

func hashHex(b []byte) string {
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

// limitReader corta la lectura al superar el tamaño máximo de la página (a diferencia de io.LimitReader, devuelve un error).
type limitReader struct {
	r    io.Reader
	left int64
}

func (l *limitReader) Read(p []byte) (int, error) {
	if l.left <= 0 {
		return 0, ErrFeedTooLarge
	}
	if int64(len(p)) > l.left {
		p = p[:l.left]
	}
	n, err := l.r.Read(p)
	l.left -= int64(n)
	return n, err
}

// recorder guarda los bytes leídos desde la última marca para poder entregar el fragmento original de cada entrada.
// El decodificador de encoding/xml lee por adelantado, pero InputOffset cuenta solo lo consumido: ambos usan la misma base.
type recorder struct {
	r    io.Reader
	buf  []byte
	base int64 // posición absoluta del primer byte de buf
	max  int   // tope de bytes retenidos (una entrada)
}

func (c *recorder) Read(p []byte) (int, error) {
	n, err := c.r.Read(p)
	c.buf = append(c.buf, p[:n]...)
	if len(c.buf) > c.max {
		return n, ErrEntryTooLarge
	}
	return n, err
}

// slice devuelve una copia de los bytes entre dos posiciones absolutas.
func (c *recorder) slice(from, to int64) []byte {
	return append([]byte(nil), c.buf[from-c.base:to-c.base]...)
}

// trim descarta lo anterior a la posición absoluta pos.
func (c *recorder) trim(pos int64) {
	if pos <= c.base {
		return
	}
	c.buf = append(c.buf[:0], c.buf[pos-c.base:]...)
	c.base = pos
}
