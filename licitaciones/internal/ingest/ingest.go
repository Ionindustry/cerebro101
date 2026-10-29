package ingest

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/placsp"
	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
)

// ParserVersion identifica la versión del parser que produjo el registro normalizado; entra en los metadatos del original.
const ParserVersion = "placsp-v1"

// Deps son las dependencias de la ingesta.
type Deps struct {
	Fetcher Fetcher
	Raw     RawStore
	State   State
	Now     func() time.Time
	Log     *slog.Logger
	// Backfill marca lo que se ingiere como carga del histórico: sus eventos no van al flujo en vivo (los consumidores del Cerebro no deben recibir millones de «nuevas»).
	Backfill bool
}

func (d Deps) now() time.Time {
	if d.Now != nil {
		return d.Now().UTC()
	}
	return time.Now().UTC()
}

func (d Deps) log() *slog.Logger {
	if d.Log != nil {
		return d.Log
	}
	return slog.New(slog.DiscardHandler)
}

// Stats cuenta lo que ha pasado en una ejecución.
type Stats struct {
	Pages       int
	Entries     int // licitaciones leídas
	Removed     int // bajas leídas
	New         int
	Modified    int
	Unchanged   int
	Stale       int
	RawCreated  int // originales nuevos guardados
	RawExisting int // originales que ya estaban
	Warnings    int // avisos de calidad de datos
	NotModified bool
	Skipped     int  // páginas de archivo ya ingeridas que no hizo falta descargar
	Pending     bool // quedan páginas por ingerir (se alcanzó el tope de la ejecución): seguir pronto
	// Dónde se va el tiempo de una página: guardar los originales en el almacén y anotar cada observación en el estado (el resto es leer y normalizar el XML).
	// Solo sirve para diagnosticar una ingesta lenta; sale en el registro de cada página.
	TiempoAlmacen time.Duration
	TiempoEstado  time.Duration
}

func (s *Stats) add(o Stats) {
	s.Pages += o.Pages
	s.Entries += o.Entries
	s.Removed += o.Removed
	s.New += o.New
	s.Modified += o.Modified
	s.Unchanged += o.Unchanged
	s.Stale += o.Stale
	s.RawCreated += o.RawCreated
	s.RawExisting += o.RawExisting
	s.Warnings += o.Warnings
	s.TiempoAlmacen += o.TiempoAlmacen
	s.TiempoEstado += o.TiempoEstado
}

// NormalizedHash es el SHA-256 del registro normalizado sin metadatos de captura ni de versión de origen: dos publicaciones con el mismo
// contenido dan el mismo hash aunque cambie atom:updated, y una corrección sin cambio de fecha (spec §3.3.1) da otro.
func NormalizedHash(l *domain.Licitacion) (string, error) {
	c := *l
	c.Updated = time.Time{}
	c.Warnings = nil
	b, err := json.Marshal(&c)
	if err != nil {
		return "", fmt.Errorf("ingest: serializar el registro: %w", err)
	}
	return sha256Hex(b), nil
}

// FlagsOf resume el ciclo de vida de un expediente a partir de sus resultados y su estado.
func FlagsOf(l *domain.Licitacion) Flags {
	var f Flags
	for _, r := range l.Results {
		switch r.Code {
		case domain.ResultAwarded:
			f |= FlagAwarded
		case domain.ResultFormalized:
			f |= FlagAwarded | FlagFormalized
		}
	}
	if l.Status == "ANUL" {
		f |= FlagAnnulled
	}
	return f
}

// ingestPage lee una página ya descargada, guarda cada original y registra cada observación.
func ingestPage(ctx context.Context, d Deps, source string, page fetch.Result) (placsp.Feed, Stats, error) {
	var st Stats
	st.Pages = 1
	pageSHA := sha256Hex(page.Body)
	meta := func(id, rawSHA string) map[string]string {
		return map[string]string{
			"fuente": source, "id-origen": id, "url-origen": page.URL, "capturado-en": page.FetchedAt.Format(time.RFC3339),
			"etag-origen": page.Validators.ETag, "pagina-sha256": pageSHA, "version-parser": ParserVersion, "sha256": rawSHA,
		}
	}
	// La página entera también es evidencia de la descarga.
	if created, err := d.Raw.PutRaw(ctx, RawObject{Key: PageKey(source, page.FetchedAt, pageSHA), Data: page.Body, SHA256: pageSHA, Meta: meta("", pageSHA)}); err != nil {
		return placsp.Feed{}, st, err
	} else if created {
		st.RawCreated++
	} else {
		st.RawExisting++
	}

	feed, err := placsp.ParseFeed(bytes.NewReader(page.Body), placsp.Options{Source: source}, func(r placsp.Record) error {
		var o Observation
		switch {
		case r.Licitacion != nil:
			l := r.Licitacion
			st.Entries++
			st.Warnings += len(l.Warnings)
			h, err := NormalizedHash(l)
			if err != nil {
				return err
			}
			o = Observation{Source: source, SourceID: l.SourceID, Hash: h, RawSHA256: r.RawSHA256, Updated: l.Updated, Flags: FlagsOf(l), Backfill: d.Backfill}
			o.RawKey = RawKey(source, idFor(l.NumericID, l.SourceID), l.Updated, r.RawSHA256)
		default:
			b := r.Baja
			st.Removed++
			o = Observation{Source: source, SourceID: b.Ref, RawSHA256: r.RawSHA256, Updated: b.When, Removed: true, Backfill: d.Backfill}
			o.RawKey = RawKey(source, idFor(lastSegment(b.Ref), b.Ref), b.When, r.RawSHA256)
		}
		o.ObservedAt = page.FetchedAt
		// Primero la evidencia, después el estado (ADR 0003): si se cae entre medias queda un original sin evento, que es inofensivo.
		t0 := time.Now()
		created, err := d.Raw.PutRaw(ctx, RawObject{Key: o.RawKey, Data: r.Raw, SHA256: r.RawSHA256, Meta: meta(o.SourceID, r.RawSHA256)})
		st.TiempoAlmacen += time.Since(t0)
		if err != nil {
			return err
		}
		if created {
			st.RawCreated++
		} else {
			st.RawExisting++
		}
		t1 := time.Now()
		out, err := d.State.Observe(ctx, o)
		st.TiempoEstado += time.Since(t1)
		if err != nil {
			return err
		}
		switch out.Kind {
		case KindNew:
			st.New++
		case KindModified:
			st.Modified++
		case KindUnchanged:
			st.Unchanged++
		case KindStale:
			st.Stale++
		}
		return nil
	})
	return feed, st, err
}

func idFor(numeric, full string) string {
	if numeric != "" {
		return numeric
	}
	return full
}

func lastSegment(ref string) string {
	ref = strings.TrimRight(ref, "/")
	if i := strings.LastIndex(ref, "/"); i >= 0 {
		return ref[i+1:]
	}
	return ref
}
