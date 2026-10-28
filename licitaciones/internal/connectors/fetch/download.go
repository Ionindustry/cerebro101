package fetch

import (
	"context"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// ErrNotFound es la respuesta 404: el fichero no existe (todavía) en la fuente.
var ErrNotFound = errors.New("fetch: no existe (404)")

// DownloadOptions configura una descarga a fichero.
type DownloadOptions struct {
	MaxBytes int64         // tamaño máximo del fichero entero; obligatorio
	Timeout  time.Duration // plazo de esta descarga (no el de las páginas, que son pequeñas); obligatorio
}

// Download descarga rawURL al fichero path sin cargarlo en memoria (los ZIP del histórico pesan cientos de MB). Pasa por los mismos controles que Fetch
// (lista blanca, https, direcciones públicas, redirecciones validadas). Si path ya existe con una descarga a medias, la continúa con una petición
// Range; si el servidor no admite rangos y responde el fichero entero, lo reescribe desde el principio. Un fallo deja lo descargado hasta ahí para
// poder continuar en el siguiente intento; un fichero demasiado grande o de un tipo que no es un archivo se borra. Devuelve el tamaño final.
func (c *Client) Download(ctx context.Context, rawURL, path string, o DownloadOptions) (int64, error) {
	if o.MaxBytes <= 0 || o.Timeout <= 0 {
		return 0, errors.New("fetch: Download necesita MaxBytes y Timeout")
	}
	u, err := url.Parse(rawURL)
	if err != nil {
		return 0, fmt.Errorf("%w: %w", ErrNotAllowed, err)
	}
	if err := c.checkURL(u); err != nil {
		return 0, err
	}
	f, err := os.OpenFile(filepath.Clean(path), os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return 0, fmt.Errorf("fetch: abrir %s: %w", path, err)
	}
	defer f.Close()
	have, err := f.Seek(0, io.SeekEnd)
	if err != nil {
		return 0, err
	}
	if have > o.MaxBytes {
		have = 0
		if err := f.Truncate(0); err != nil {
			return 0, err
		}
		if _, err := f.Seek(0, io.SeekStart); err != nil {
			return 0, err
		}
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return 0, err
	}
	req.Header.Set("User-Agent", c.userAgent)
	req.Header.Set("Accept", "application/zip, application/octet-stream;q=0.9")
	if have > 0 {
		req.Header.Set("Range", fmt.Sprintf("bytes=%d-", have))
	}
	cli := &http.Client{Transport: c.http.Transport, CheckRedirect: c.http.CheckRedirect, Timeout: o.Timeout}
	resp, err := cli.Do(req)
	if err != nil {
		if errors.Is(err, ErrNotAllowed) || ctx.Err() != nil {
			return have, err
		}
		return have, fmt.Errorf("fetch: %w", err)
	}
	defer resp.Body.Close()

	restart := func() error { // empezar de cero: el servidor no continúa donde lo dejamos
		have = 0
		if err := f.Truncate(0); err != nil {
			return err
		}
		_, err := f.Seek(0, io.SeekStart)
		return err
	}
	switch resp.StatusCode {
	case http.StatusOK:
		if err := restart(); err != nil {
			return 0, err
		}
	case http.StatusPartialContent:
		if start, ok := rangeStart(resp.Header.Get("Content-Range")); !ok || start != have {
			_ = restart()
			return 0, fmt.Errorf("%w: el servidor continuó en otro punto (Content-Range %q)", ErrStatus, resp.Header.Get("Content-Range"))
		}
	case http.StatusRequestedRangeNotSatisfiable:
		if total, ok := rangeTotal(resp.Header.Get("Content-Range")); ok && have > 0 && total == have {
			return have, nil // ya estaba entero
		}
		_ = restart()
		return 0, fmt.Errorf("%w: %s", ErrStatus, resp.Status)
	case http.StatusNotFound:
		if have == 0 {
			_ = os.Remove(path)
		}
		return have, ErrNotFound
	default:
		return have, fmt.Errorf("%w: %s", ErrStatus, resp.Status)
	}
	if mt, _, err := mime.ParseMediaType(resp.Header.Get("Content-Type")); err == nil && (strings.HasPrefix(mt, "text/") || strings.HasSuffix(mt, "+xml") || mt == "application/json") {
		_ = os.Remove(path)
		return 0, fmt.Errorf("%w: %q (se esperaba un archivo)", ErrContentType, mt)
	}
	if resp.ContentLength >= 0 && have+resp.ContentLength > o.MaxBytes {
		_ = os.Remove(path)
		return 0, ErrTooLarge
	}
	n, err := io.Copy(f, io.LimitReader(resp.Body, o.MaxBytes-have+1))
	have += n
	if have > o.MaxBytes {
		_ = os.Remove(path)
		return 0, ErrTooLarge
	}
	if err != nil {
		return have, fmt.Errorf("fetch: leer la respuesta: %w", err)
	}
	if resp.ContentLength >= 0 && n < resp.ContentLength {
		return have, fmt.Errorf("fetch: respuesta cortada (%d de %d bytes)", n, resp.ContentLength)
	}
	return have, nil
}

// rangeStart lee el primer byte de «bytes 100-199/1000».
func rangeStart(h string) (int64, bool) {
	rest, ok := strings.CutPrefix(h, "bytes ")
	if !ok {
		return 0, false
	}
	first, _, ok := strings.Cut(rest, "-")
	if !ok {
		return 0, false
	}
	n, err := strconv.ParseInt(first, 10, 64)
	return n, err == nil
}

// rangeTotal lee el tamaño total de «bytes 100-199/1000» o «bytes */1000».
func rangeTotal(h string) (int64, bool) {
	_, total, ok := strings.Cut(h, "/")
	if !ok {
		return 0, false
	}
	n, err := strconv.ParseInt(total, 10, 64)
	return n, err == nil
}
