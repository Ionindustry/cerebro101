package ingest

import (
	"archive/zip"
	"context"
	"errors"
	"fmt"
	"io"
	"math"
	"path"
	"sort"
	"strings"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
)

// ZipLimits acota lo que se acepta de un ZIP de la fuente (SEC-010…013): es entrada externa, así que nada se da por bueno por lo que declare.
type ZipLimits struct {
	MaxFiles      int   // ficheros .atom; 0 = 20 000
	MaxFileBytes  int64 // tamaño de cada .atom descomprimido; 0 = 64 MiB (como una página en vivo)
	MaxTotalBytes int64 // suma de los .atom descomprimidos; 0 = 32 GiB
}

func (l ZipLimits) withDefaults() ZipLimits {
	if l.MaxFiles <= 0 {
		l.MaxFiles = 20_000
	}
	if l.MaxFileBytes <= 0 {
		l.MaxFileBytes = 64 << 20
	}
	if l.MaxTotalBytes <= 0 {
		l.MaxTotalBytes = 32 << 30
	}
	return l
}

// Errores de un ZIP que no se puede aceptar. Quien llama no lo reintenta tal cual: lo vuelve a descargar.
var (
	ErrZipInvalid  = errors.New("ingest: ZIP no válido")
	ErrZipTooLarge = errors.New("ingest: el ZIP supera los límites")
)

// ZipKey es la clave con la que se anota que un ZIP entero (label: «202609» o «2023») está ingerido. El fichero concreto es ZipKey + "/" + nombre.
func ZipKey(label string) string { return "zip:" + label }

// RunZip ingiere los ficheros .atom de un ZIP del histórico (cada uno es una página de la sindicación, como las de la fuente en vivo) con el
// mismo camino que Run: el original de cada entrada y la página entera quedan en el almacén y cada observación en el estado. Orden por nombre
// (determinista). Cada fichero ingerido se anota (MarkPageDone) para que un fallo o un reinicio retome en el siguiente; al terminar se anota el ZIP
// entero. Un orden distinto al cronológico no importa: Observe descarta lo que ya está superado por una versión más reciente (KindStale).
func RunZip(ctx context.Context, d Deps, source, label, zipURL, zipPath string, lim ZipLimits) (Stats, error) {
	var total Stats
	d.Backfill = true // todo lo que sale de un ZIP es histórico, también sus eventos
	lim = lim.withDefaults()
	zr, err := zip.OpenReader(zipPath)
	if err != nil {
		return total, fmt.Errorf("%w: %w", ErrZipInvalid, err)
	}
	defer zr.Close()

	var files []*zip.File
	var declared uint64
	for _, f := range zr.File {
		if f.FileInfo().IsDir() || !strings.EqualFold(path.Ext(f.Name), ".atom") {
			continue
		}
		files = append(files, f)
		declared += f.UncompressedSize64
	}
	if len(files) > lim.MaxFiles || exceeds(declared, lim.MaxTotalBytes) {
		return total, fmt.Errorf("%w: %d ficheros, %d bytes declarados", ErrZipTooLarge, len(files), declared)
	}
	if len(files) == 0 {
		return total, fmt.Errorf("%w: no contiene ficheros .atom", ErrZipInvalid)
	}
	sort.Slice(files, func(i, j int) bool { return files[i].Name < files[j].Name })

	done, err := d.State.DonePages(ctx, source)
	if err != nil {
		return total, fmt.Errorf("ingest: leer las páginas ya ingeridas: %w", err)
	}
	var read int64
	for _, f := range files {
		if err := ctx.Err(); err != nil {
			return total, err
		}
		key := ZipKey(label) + "/" + f.Name
		if _, ok := done[key]; ok {
			total.Skipped++
			continue
		}
		if exceeds(f.UncompressedSize64, lim.MaxFileBytes) {
			return total, fmt.Errorf("%w: %s declara %d bytes", ErrZipTooLarge, f.Name, f.UncompressedSize64)
		}
		body, err := readLimited(f, lim.MaxFileBytes)
		if err != nil {
			return total, fmt.Errorf("ingest: leer %s del ZIP %s: %w", f.Name, label, err)
		}
		if read += int64(len(body)); read > lim.MaxTotalBytes {
			return total, fmt.Errorf("%w: más de %d bytes descomprimidos", ErrZipTooLarge, lim.MaxTotalBytes)
		}
		t0 := time.Now()
		_, st, err := ingestPage(ctx, d, source, fetch.Result{URL: zipURL + "#" + f.Name, Body: body, FetchedAt: d.now()})
		total.add(st)
		if err != nil {
			return total, fmt.Errorf("ingest: %s del ZIP %s: %w", f.Name, label, err)
		}
		d.log().Info("página del histórico ingerida", "fuente", source, "zip", label, "fichero", f.Name, "entradas", st.Entries, "bajas", st.Removed,
			"nuevas", st.New, "modificadas", st.Modified, "sin_cambios", st.Unchanged, "superadas", st.Stale,
			"ms_total", time.Since(t0).Milliseconds(), "ms_almacen", st.TiempoAlmacen.Milliseconds(), "ms_estado", st.TiempoEstado.Milliseconds())
		if err := d.State.MarkPageDone(ctx, source, key, ""); err != nil {
			return total, fmt.Errorf("ingest: anotar la página del histórico: %w", err)
		}
	}
	if err := d.State.MarkPageDone(ctx, source, ZipKey(label), ""); err != nil {
		return total, fmt.Errorf("ingest: anotar el ZIP ingerido: %w", err)
	}
	return total, nil
}

// readLimited lee un fichero del ZIP sin fiarse del tamaño que declara: nunca más de max bytes.
func readLimited(f *zip.File, max int64) ([]byte, error) {
	rc, err := f.Open()
	if err != nil {
		return nil, err
	}
	defer rc.Close()
	b, err := io.ReadAll(io.LimitReader(rc, max+1))
	if err != nil {
		return nil, err
	}
	if int64(len(b)) > max {
		return nil, fmt.Errorf("%w: %s supera %d bytes descomprimidos", ErrZipTooLarge, f.Name, max)
	}
	return b, nil
}

// exceeds dice si un tamaño declarado (sin signo) supera un límite (con signo), sin desbordar en la conversión.
func exceeds(size uint64, limit int64) bool {
	if size > math.MaxInt64 {
		return true
	}
	return int64(size) > limit
}
