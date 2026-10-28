package ingestor

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

// Servidores que publican los ZIP del histórico. POR VERIFICAR con una descarga real: la documentación oficial los sitúa en
// contrataciondelsectorpublico.gob.es, la sindicación en vivo está en contrataciondelestado.es; se prueba cada uno hasta que uno responde.
var zipHosts = []string{"contrataciondelsectorpublico.gob.es", sourceHost}

// histSource describe dónde están los ZIP de una fuente.
type histSource struct{ dir, prefix string }

// HistoricoCatalog son las fuentes con ZIP de histórico conocidos. Las demás no cargan histórico.
var HistoricoCatalog = map[string]histSource{
	domain.SourcePLACSP643: {dir: "sindicacion_643", prefix: "licitacionesPerfilesContratanteCompleto3"},
}

// Límites de un ZIP: el mensual pesa unos 92 MB (docs/SEGURIDAD.md); el anual reúne doce.
const (
	maxZipBytes     = 4 << 30
	minHistoricYear = 2012 // PLACSP ofrece datos abiertos desde 2012
)

// HistoricoConfig es la configuración de la carga del histórico.
type HistoricoConfig struct {
	Since   time.Time     // primer día desde el que se carga
	Dir     string        // carpeta de trabajo donde se baja el ZIP (con espacio para uno de varios GB); se borra al terminar cada ZIP
	Timeout time.Duration // plazo por descarga de un ZIP
}

// Downloader es lo que necesita el histórico del cliente HTTP.
type Downloader interface {
	Download(ctx context.Context, rawURL, path string, o fetch.DownloadOptions) (int64, error)
}

// Item es un ZIP del plan: Label es «AAAAMM» (mes del año en curso) o «AAAA» (año completo).
type Item struct{ Label string }

// Plan lista los ZIP que hay que cargar, del más reciente al más antiguo (lo más útil primero): los meses cerrados del año en curso (el mes en
// curso lo cubre la sindicación en vivo) y los años completos anteriores, desde since. El ZIP de un año cerrado puede no estar publicado aún en
// enero: simplemente no existe todavía y se reintenta.
func Plan(now, since time.Time) []Item {
	now, since = now.UTC(), since.UTC()
	var items []Item
	cy, cm := now.Year(), int(now.Month())
	for m := cm - 1; m >= 1; m-- {
		if cy < since.Year() || (cy == since.Year() && m < int(since.Month())) {
			break
		}
		items = append(items, Item{Label: fmt.Sprintf("%04d%02d", cy, m)})
	}
	for y := cy - 1; y >= since.Year() && y >= minHistoricYear; y-- {
		items = append(items, Item{Label: fmt.Sprintf("%04d", y)})
	}
	return items
}

// Historico carga los ZIP que faltan, uno por vuelta del ingestor.
type Historico struct {
	Source string
	Cfg    HistoricoConfig
	Deps   ingest.Deps
	DL     Downloader
	Log    *slog.Logger
	Now    func() time.Time
}

// Step ingiere, como mucho, un ZIP pendiente. pending dice que quedan más: seguir pronto. Un ZIP que aún no existe en la fuente (404) se salta
// sin bloquear a los demás. Un fallo se devuelve para reintentar más tarde: la descarga a medias y las páginas ya ingeridas se conservan.
func (h *Historico) Step(ctx context.Context) (pending bool, err error) {
	src, ok := HistoricoCatalog[h.Source]
	if !ok {
		return false, nil
	}
	now := time.Now
	if h.Now != nil {
		now = h.Now
	}
	done, err := h.Deps.State.DonePages(ctx, h.Source)
	if err != nil {
		return false, fmt.Errorf("histórico: leer lo ya ingerido: %w", err)
	}
	var todo []Item
	for _, it := range Plan(now(), h.Cfg.Since) {
		if _, ok := done[ingest.ZipKey(it.Label)]; !ok {
			todo = append(todo, it)
		}
	}
	for _, it := range todo {
		ok, err := h.load(ctx, src, it)
		if err != nil {
			return true, err
		}
		if ok {
			return true, nil // cargado uno: la siguiente vuelta mira si hay más (si no, esperará lo normal)
		}
	}
	return false, nil // todo cargado, o lo que falta aún no está publicado
}

// load descarga (si hace falta), ingiere y borra un ZIP. ok=false si no existe todavía en ninguno de los servidores.
func (h *Historico) load(ctx context.Context, src histSource, it Item) (bool, error) {
	if err := os.MkdirAll(h.Cfg.Dir, 0o700); err != nil {
		return false, fmt.Errorf("histórico: carpeta de trabajo: %w", err)
	}
	file := fmt.Sprintf("%s_%s.zip", src.prefix, it.Label)
	zipPath := filepath.Join(h.Cfg.Dir, h.Source+"_"+it.Label+".zip")
	part := zipPath + ".part"
	zipURL := ""
	if _, err := os.Stat(zipPath); err != nil { // sin ZIP completo (de un intento anterior): descargarlo o continuar la descarga
		found := false
		for _, host := range zipHosts {
			zipURL = "https://" + host + "/sindicacion/" + src.dir + "/" + file
			start := time.Now()
			n, err := h.DL.Download(ctx, zipURL, part, fetch.DownloadOptions{MaxBytes: maxZipBytes, Timeout: h.Cfg.Timeout})
			if errors.Is(err, fetch.ErrNotFound) {
				h.log().Info("el ZIP del histórico aún no existe en este servidor", "zip", it.Label, "servidor", host)
				continue
			}
			if err != nil {
				return false, fmt.Errorf("histórico: descargar %s: %w", zipURL, err) // se conserva lo bajado: la próxima vez continúa
			}
			h.log().Info("ZIP del histórico descargado", "zip", it.Label, "servidor", host, "bytes", n, "duracion", time.Since(start).Round(time.Second).String())
			found = true
			break
		}
		if !found {
			return false, nil
		}
		if err := checkZipMagic(part); err != nil {
			_ = os.Remove(part)
			return false, fmt.Errorf("histórico: %s: %w", zipURL, err)
		}
		if err := os.Rename(part, zipPath); err != nil {
			return false, fmt.Errorf("histórico: %w", err)
		}
	} else {
		zipURL = "https://" + zipHosts[0] + "/sindicacion/" + src.dir + "/" + file
	}

	stats, err := ingest.RunZip(ctx, h.Deps, h.Source, it.Label, zipURL, zipPath, ingest.ZipLimits{})
	h.log().Info("ZIP del histórico ingerido", "zip", it.Label, "paginas", stats.Pages, "paginas_saltadas", stats.Skipped, "entradas", stats.Entries,
		"nuevas", stats.New, "modificadas", stats.Modified, "sin_cambios", stats.Unchanged, "superadas", stats.Stale, "bajas", stats.Removed, "error", err != nil)
	if err != nil {
		if errors.Is(err, ingest.ErrZipInvalid) || errors.Is(err, ingest.ErrZipTooLarge) {
			_ = os.Remove(zipPath) // un ZIP corrupto no se arregla reintentando: se vuelve a bajar entero
		}
		return false, fmt.Errorf("histórico: ZIP %s: %w", it.Label, err)
	}
	_ = os.Remove(zipPath)
	return true, nil
}

func (h *Historico) log() *slog.Logger {
	if h.Log != nil {
		return h.Log
	}
	return slog.New(slog.DiscardHandler)
}

// checkZipMagic comprueba que el fichero empieza como un ZIP: un error HTML servido con 200 no debe llegar al lector.
func checkZipMagic(path string) error {
	f, err := os.Open(filepath.Clean(path))
	if err != nil {
		return err
	}
	defer f.Close()
	var b [4]byte
	if _, err := f.Read(b[:]); err != nil || string(b[:]) != "PK\x03\x04" {
		return errors.New("lo descargado no es un ZIP")
	}
	return nil
}

// ParseSince lee LIC_HISTORICO_DESDE: «AAAA» (desde el 1 de enero) o «AAAA-MM».
func ParseSince(s string, now time.Time) (time.Time, error) {
	s = strings.TrimSpace(s)
	layout := "2006-01"
	if len(s) == 4 {
		layout = "2006"
	}
	t, err := time.ParseInLocation(layout, s, time.UTC)
	if err != nil {
		return time.Time{}, fmt.Errorf("%s no válido: usa un año (2023) o año y mes (2023-06)", EnvHistoricoDesde)
	}
	if t.Year() < minHistoricYear {
		return time.Time{}, fmt.Errorf("%s: PLACSP publica desde %d", EnvHistoricoDesde, minHistoricYear)
	}
	if t.After(now) {
		return time.Time{}, fmt.Errorf("%s está en el futuro", EnvHistoricoDesde)
	}
	return t, nil
}
