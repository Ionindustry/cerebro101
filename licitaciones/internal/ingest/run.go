package ingest

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
)

// RunOptions configura una ejecución.
type RunOptions struct {
	MaxPages int // tope de páginas que se DESCARGAN por ejecución; 0 = 50
}

const (
	defaultMaxPages = 50
	maxRecorrido    = 1_000_000 // freno contra un ciclo de enlaces en la fuente
)

// ErrNoStartURL se devuelve si no se indica la dirección de la primera página.
var ErrNoStartURL = errors.New("ingest: falta la dirección de la primera página")

// Run ingiere una fuente. La sindicación es una cadena: la primera página (la «cabeza», que cambia) y, siguiendo `next` hacia atrás en el
// tiempo, páginas de archivo que una vez publicadas ya no cambian.
//
//   - La cabeza se descarga siempre (con los validadores de la ejecución anterior: si responde 304 se sigue por el enlace que se guardó).
//   - Una página de archivo ya ingerida (DonePages) se SALTA sin descargarla, usando el enlace siguiente que se anotó. Una página nueva se descarga,
//     se ingiere entera y se anota (MarkPageDone) solo si no falló nada.
//   - Se recorre la cadena hasta su final o hasta MaxPages descargas; si quedan páginas, Stats.Pending lo dice y la siguiente ejecución sigue
//     donde esta lo dejó.
//
// Por eso un fallo a mitad de camino (una página lenta, la red) no se paga dos veces: lo hecho no se repite y la siguiente ejecución retoma en la
// página que falló. La cabeza se anota (punto de control) en cuanto se ingiere: es lo que dice cuándo se comprobó la fuente por última vez.
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
	done, err := d.State.DonePages(ctx, source)
	if err != nil {
		return total, fmt.Errorf("ingest: leer las páginas ya ingeridas: %w", err)
	}

	url, validators := startURL, cp.Validators
	downloads := 0
	for step := 0; step < maxRecorrido && url != ""; step++ {
		head := url == startURL
		if !head {
			if next, ok := done[url]; ok { // ya ingerida: no se descarga
				total.Skipped++
				url = next
				continue
			}
		}
		if downloads >= opt.MaxPages {
			total.Pending = true
			break
		}
		res, err := d.Fetcher.Fetch(ctx, url, validators)
		if err != nil {
			return total, fmt.Errorf("ingest: descargar %s: %w", url, err)
		}
		if res.NotModified { // solo la cabeza lleva validadores
			total.NotModified = true
			d.log().Info("fuente sin cambios", "fuente", source)
			// Comprobada y al día: se anota para que «última ingesta» diga la verdad, y se sigue por donde se quedó.
			if err := d.State.SaveCheckpoint(ctx, source, Checkpoint{LastRun: d.now(), Validators: cp.Validators, Next: cp.Next}); err != nil {
				return total, fmt.Errorf("ingest: guardar el punto de control: %w", err)
			}
			url, validators = cp.Next, fetch.Validators{}
			continue
		}
		downloads++
		t0 := time.Now()
		feed, st, err := ingestPage(ctx, d, source, res)
		total.add(st)
		if err != nil {
			return total, fmt.Errorf("ingest: página %s: %w", url, err)
		}
		d.log().Info("página ingerida", "fuente", source, "url", res.URL, "entradas", st.Entries, "bajas", st.Removed,
			"nuevas", st.New, "modificadas", st.Modified, "sin_cambios", st.Unchanged,
			"ms_total", time.Since(t0).Milliseconds(), "ms_almacen", st.TiempoAlmacen.Milliseconds(), "ms_estado", st.TiempoEstado.Milliseconds())
		if head {
			if err := d.State.SaveCheckpoint(ctx, source, Checkpoint{LastRun: d.now(), Validators: res.Validators, Next: feed.Next}); err != nil {
				return total, fmt.Errorf("ingest: guardar el punto de control: %w", err)
			}
			cp.Next = feed.Next
		} else {
			if err := d.State.MarkPageDone(ctx, source, url, feed.Next); err != nil {
				return total, fmt.Errorf("ingest: anotar la página ingerida: %w", err)
			}
			done[url] = feed.Next
		}
		url, validators = feed.Next, fetch.Validators{}
	}
	return total, nil
}
