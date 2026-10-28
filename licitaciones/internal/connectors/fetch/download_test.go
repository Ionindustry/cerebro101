package fetch

import (
	"bytes"
	"context"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"
)

var optsDescarga = DownloadOptions{MaxBytes: 1 << 20, Timeout: 10 * time.Second}

func contenido() []byte { return bytes.Repeat([]byte("0123456789"), 1000) }

func servirZip(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/zip")
	http.ServeContent(w, r, "x.zip", time.Time{}, bytes.NewReader(contenido())) // admite Range
}

func TestDescargaAFichero(t *testing.T) {
	c, srv, _ := clienteLocal(t, http.HandlerFunc(servirZip), Options{})
	p := filepath.Join(t.TempDir(), "a.zip")
	n, err := c.Download(context.Background(), srv.URL+"/a.zip", p, optsDescarga)
	if err != nil || n != int64(len(contenido())) {
		t.Fatalf("n=%d err=%v", n, err)
	}
	if b, _ := os.ReadFile(p); !bytes.Equal(b, contenido()) {
		t.Fatal("el fichero no coincide")
	}
}

func TestDescargaSeContinuaDondeSeQuedo(t *testing.T) {
	var rango string
	c, srv, _ := clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rango = r.Header.Get("Range")
		servirZip(w, r)
	}), Options{})
	p := filepath.Join(t.TempDir(), "a.zip")
	if err := os.WriteFile(p, contenido()[:3000], 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Download(context.Background(), srv.URL, p, optsDescarga); err != nil {
		t.Fatal(err)
	}
	if rango != "bytes=3000-" {
		t.Fatalf("Range = %q", rango)
	}
	if b, _ := os.ReadFile(p); !bytes.Equal(b, contenido()) {
		t.Fatal("la descarga continuada no coincide")
	}
}

func TestDescargaSinRangosSeReescribeEntera(t *testing.T) {
	c, srv, _ := clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/zip")
		_, _ = w.Write(contenido()) // ignora Range
	}), Options{})
	p := filepath.Join(t.TempDir(), "a.zip")
	_ = os.WriteFile(p, []byte("basura a medias"), 0o600)
	if _, err := c.Download(context.Background(), srv.URL, p, optsDescarga); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(p); !bytes.Equal(b, contenido()) {
		t.Fatal("no se reescribió desde el principio")
	}
}

func TestDescargaYaEntera(t *testing.T) {
	c, srv, _ := clienteLocal(t, http.HandlerFunc(servirZip), Options{})
	p := filepath.Join(t.TempDir(), "a.zip")
	_ = os.WriteFile(p, contenido(), 0o600)
	n, err := c.Download(context.Background(), srv.URL, p, optsDescarga)
	if err != nil || n != int64(len(contenido())) {
		t.Fatalf("n=%d err=%v", n, err)
	}
}

func TestDescarga404NoDejaFichero(t *testing.T) {
	c, srv, _ := clienteLocal(t, http.NotFoundHandler(), Options{})
	p := filepath.Join(t.TempDir(), "a.zip")
	if _, err := c.Download(context.Background(), srv.URL, p, optsDescarga); !errors.Is(err, ErrNotFound) {
		t.Fatalf("err = %v", err)
	}
	if _, err := os.Stat(p); err == nil {
		t.Fatal("quedó un fichero vacío")
	}
}

func TestDescargaDemasiadoGrandeSeBorra(t *testing.T) {
	c, srv, _ := clienteLocal(t, http.HandlerFunc(servirZip), Options{})
	p := filepath.Join(t.TempDir(), "a.zip")
	_, err := c.Download(context.Background(), srv.URL, p, DownloadOptions{MaxBytes: 5000, Timeout: time.Second})
	if !errors.Is(err, ErrTooLarge) {
		t.Fatalf("err = %v", err)
	}
	if _, err := os.Stat(p); err == nil {
		t.Fatal("el fichero demasiado grande no se borró")
	}
}

func TestDescargaDeUnaPaginaWebNoSeAcepta(t *testing.T) {
	c, srv, _ := clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte("<html>error</html>"))
	}), Options{})
	p := filepath.Join(t.TempDir(), "a.zip")
	if _, err := c.Download(context.Background(), srv.URL, p, optsDescarga); !errors.Is(err, ErrContentType) {
		t.Fatalf("err = %v", err)
	}
}

func TestDescargaFueraDeLaListaBlanca(t *testing.T) {
	c, _, _ := clienteLocal(t, http.NotFoundHandler(), Options{})
	if _, err := c.Download(context.Background(), "https://malo.example/a.zip", filepath.Join(t.TempDir(), "a.zip"), optsDescarga); !errors.Is(err, ErrNotAllowed) {
		t.Fatalf("err = %v", err)
	}
}
