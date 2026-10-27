package ingest

import (
	"context"
	"errors"
	"fmt"

	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
)

// RunOptions configura una ejecución.
type RunOptions struct {
	MaxPages int // tope de páginas por ejecución; 0 = 50
}

const defaultMaxPages = 50

// ErrNoStartURL se devuelve si no se indica la dirección de la primera página.
var ErrNoStartURL = errors.New("ingest: falta la dirección de la primera página")

// Run ingiere una fuente: descarga la primera página (con los validadores de la ejecución anterior) y sigue los enlaces `next` hacia atrás
// en el tiempo hasta llegar a una página en la que todo es ya conocido. La sindicación va en orden descendente por fecha, así que en
// régimen normal solo hace falta la primera página; si ha habido muchos cambios desde la última vez, recorre las que hagan falta.
//
// Si una página falla, devuelve el error con lo ingerido hasta entonces (todo ello ya consistente: cada entrada es idempotente) y deja el punto
// de control vacío. Vacío significa «la última ejecución no terminó»: la siguiente ejecución no se fía de los validadores (un 304 la dejaría en
// la primera página) ni se detiene en la primera página ya conocida, sino que recorre hacia atrás hasta el final o hasta el tope, de modo
// que lo que quedó sin ingerir se recupera sin duplicar lo ya hecho. Así también arranca la primera ejecución de una fuente.
func Run(ctx context.Context, d Deps, source, startURL string, opt RunOptions) (Stats, error) {
	var total Stats
	if startURL == "" {
		return total, ErrNoStartURL
	}
	if opt.MaxPages <= 0 {
		opt.MaxPages = defaultMaxPages
	}
	cp, err := d.State.Checkpoint(ctx, source)
	if err != nil {
		return total, fmt.Errorf("ingest: leer el punto de control: %w", err)
	}

	complete := !cp.LastRun.IsZero() // la ejecución anterior terminó: basta con llegar a lo ya conocido
	url, validators := startURL, cp.Validators
	var first Checkpoint
	progressed := false
	// fail devuelve el error; si ya se había ingerido algo, deja el punto de control vacío (ver arriba).
	fail := func(err error) (Stats, error) {
		if progressed && complete {
			if serr := d.State.SaveCheckpoint(context.WithoutCancel(ctx), source, Checkpoint{}); serr != nil {
				d.log().Error("no se pudo invalidar el punto de control", "fuente", source, "error", serr)
			}
		}
		return total, err
	}
	for page := 0; page < opt.MaxPages; page++ {
		res, err := d.Fetcher.Fetch(ctx, url, validators)
		if err != nil {
			return fail(fmt.Errorf("ingest: descargar %s: %w", url, err))
		}
		if res.NotModified {
			if page == 0 {
				total.NotModified = true
				d.log().Info("fuente sin cambios", "fuente", source)
			}
			break
		}
		progressed = true
		feed, st, err := ingestPage(ctx, d, source, res)
		total.add(st)
		if err != nil {
			return fail(fmt.Errorf("ingest: página %s: %w", url, err))
		}
		d.log().Info("página ingerida", "fuente", source, "url", res.URL, "entradas", st.Entries, "bajas", st.Removed,
			"nuevas", st.New, "modificadas", st.Modified, "sin_cambios", st.Unchanged)
		if page == 0 {
			first = Checkpoint{LastRun: d.now(), Validators: res.Validators}
		}
		// Página sin ninguna novedad: se ha llegado a lo ya conocido (solo si la ejecución anterior terminó).
		if feed.Next == "" || (complete && st.New+st.Modified == 0) {
			break
		}
		url, validators = feed.Next, fetch.Validators{}
	}
	if !first.LastRun.IsZero() {
		if err := d.State.SaveCheckpoint(ctx, source, first); err != nil {
			return total, fmt.Errorf("ingest: guardar el punto de control: %w", err)
		}
	}
	return total, nil
}
