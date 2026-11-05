package ingest

import (
	"context"
	"errors"
	"fmt"
	"regexp"
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
func Run(ctx context.Context, d Deps, source, startURL string, opt RunOptions) (total Stats, runErr error) {
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

	// Al día o no se calcula SIEMPRE, también si la vuelta acaba en error (p. ej. falla una página antigua del relleno del histórico): lo reciente puede estar completo.
	defer func() { total.CaughtUp = AlDiaReciente(done, cp.Next, d.now(), VentanaAlDia) }()

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

// VentanaAlDia es hasta dónde hacia atrás tiene que estar completo lo ingerido para decir que la fuente está «al día»: lo de las últimas semanas. Los huecos más antiguos (el relleno del histórico, que
// puede tardar horas o días) NO cuentan: lo reciente se publica y se consulta desde que se ingiere, y no hay que esperar a que acabe el pasado.
const VentanaAlDia = 30 * 24 * time.Hour

var reFechaPagina = regexp.MustCompile(`_(\d{8})_(\d{6})`)

// fechaDePagina saca la fecha de una página de archivo de la sindicación (…_20250926_183504_4.atom). ok=false si el nombre no lleva fecha.
func fechaDePagina(url string) (t time.Time, ok bool) {
	m := reFechaPagina.FindStringSubmatch(url)
	if m == nil {
		return time.Time{}, false
	}
	t, err := time.Parse("20060102150405", m[1]+m[2])
	return t, err == nil
}

// AlDiaReciente es AlDia pero solo exige que esté completo lo RECIENTE: si la cadena desde la cabecera llega hasta una página aún sin ingerir cuya fecha es anterior a `ahora - ventana`, todo lo de
// los últimos días está ingerido (lo que falta es histórico) y la fuente está al día. Si el primer hueco es reciente, o su nombre no lleva fecha, se exige lo mismo que AlDia (falla hacia «no al día»). Pura.
func AlDiaReciente(done map[string]string, siguiente string, ahora time.Time, ventana time.Duration) bool {
	if AlDia(done, siguiente) {
		return true
	}
	hueco := siguiente
	visitado := map[string]bool{}
	for hueco != "" {
		next, ok := done[hueco]
		if !ok || visitado[hueco] {
			break
		}
		visitado[hueco] = true
		hueco = next
	}
	if hueco == "" || visitado[hueco] {
		return false // la cadena termina o da vueltas: no hay un hueco que datar
	}
	t, ok := fechaDePagina(hueco)
	return ok && t.Before(ahora.Add(-ventana))
}

// AlDia dice si las páginas de archivo ya ingeridas (done: dirección → enlace siguiente) forman una cadena continua desde `siguiente` (el enlace que sigue a la cabecera). Al día, TODAS las
// ingeridas se alcanzan siguiendo la cadena desde la cabecera. Tras una parada (el equipo apagado unos días) las páginas nuevas del principio no están ingeridas y las que ya estaban quedan
// «sueltas» (no se llega a ellas desde la cabecera) hasta que se rellena el hueco: entonces vuelve a haber una sola cadena. Sin páginas de archivo ingeridas, solo está al día si no hay
// ninguna que seguir. Pura.
func AlDia(done map[string]string, siguiente string) bool {
	if siguiente != "" {
		if _, ok := done[siguiente]; !ok {
			return false // la primera página de archivo aún no está ingerida
		}
	}
	vistas := 0
	visitado := map[string]bool{}
	for url := siguiente; url != ""; {
		next, ok := done[url]
		if !ok || visitado[url] {
			break
		}
		visitado[url] = true
		vistas++
		url = next
	}
	return vistas == len(done)
}
