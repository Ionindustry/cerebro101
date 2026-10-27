package fetch

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strings"
	"testing"
	"time"
)

// clienteLocal habla con un servidor de pruebas en 127.0.0.1 (solo posible con el modo de pruebas, que desactiva https y la comprobación de IP).
func clienteLocal(t *testing.T, h http.Handler, o Options) (*Client, *httptest.Server, *[]time.Duration) {
	t.Helper()
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	o.AllowedHosts = append(o.AllowedHosts, "127.0.0.1")
	c, err := New(o)
	if err != nil {
		t.Fatal(err)
	}
	c.testHTTP = true
	var esperas []time.Duration
	c.sleep = func(_ context.Context, d time.Duration) error { esperas = append(esperas, d); return nil }
	return c, srv, &esperas
}

func atom(w http.ResponseWriter, cuerpo string) {
	w.Header().Set("Content-Type", "application/atom+xml; charset=UTF-8")
	_, _ = w.Write([]byte(cuerpo))
}

func TestDescargaCorrectaConCabecerasYValidadores(t *testing.T) {
	var visto *http.Request
	c, srv, _ := clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		visto = r
		w.Header().Set("ETag", `"abc"`)
		w.Header().Set("Last-Modified", "Mon, 26 Oct 2026 10:35:32 GMT")
		atom(w, "<feed/>")
	}), Options{UserAgent: "prueba/1"})
	res, err := c.Fetch(context.Background(), srv.URL+"/p.atom", Validators{ETag: `"previo"`, LastModified: "Sun, 25 Oct 2026 19:03:00 GMT"})
	if err != nil {
		t.Fatal(err)
	}
	if string(res.Body) != "<feed/>" || res.Validators.ETag != `"abc"` || res.Validators.LastModified == "" || res.FetchedAt.IsZero() || res.NotModified {
		t.Fatalf("resultado inesperado: %+v", res)
	}
	if visto.Header.Get("User-Agent") != "prueba/1" || visto.Header.Get("If-None-Match") != `"previo"` || visto.Header.Get("If-Modified-Since") == "" {
		t.Fatalf("cabeceras de la petición inesperadas: %v", visto.Header)
	}
}

func TestNoModificado(t *testing.T) {
	c, srv, _ := clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNotModified) }), Options{})
	res, err := c.Fetch(context.Background(), srv.URL, Validators{ETag: `"x"`})
	if err != nil || !res.NotModified || len(res.Body) != 0 {
		t.Fatalf("esperaba 304 sin cuerpo: %+v %v", res, err)
	}
}

func TestReintentosConEsperaCreciente(t *testing.T) {
	llamadas := 0
	c, srv, esperas := clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		llamadas++
		if llamadas <= 2 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		atom(w, "<feed/>")
	}), Options{})
	if _, err := c.Fetch(context.Background(), srv.URL, Validators{}); err != nil {
		t.Fatal(err)
	}
	if llamadas != 3 || len(*esperas) != 2 || (*esperas)[0] != time.Second || (*esperas)[1] != 2*time.Second {
		t.Fatalf("llamadas = %d, esperas = %v", llamadas, *esperas)
	}
}

func TestSePlanteaRendirseTrasLosReintentos(t *testing.T) {
	llamadas := 0
	c, srv, _ := clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { llamadas++; w.WriteHeader(http.StatusTooManyRequests) }), Options{Retries: 1})
	_, err := c.Fetch(context.Background(), srv.URL, Validators{})
	if !errors.Is(err, ErrStatus) || llamadas != 2 {
		t.Fatalf("error = %v, llamadas = %d (1 intento + 1 reintento)", err, llamadas)
	}
}

func TestUnErrorDelClienteNoSeReintenta(t *testing.T) {
	llamadas := 0
	c, srv, _ := clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { llamadas++; http.NotFound(w, nil) }), Options{})
	if _, err := c.Fetch(context.Background(), srv.URL, Validators{}); !errors.Is(err, ErrStatus) || llamadas != 1 {
		t.Fatalf("un 404 no se reintenta: error = %v, llamadas = %d", err, llamadas)
	}
}

func TestTamanoMaximo(t *testing.T) {
	grande := strings.Repeat("a", 1000)
	for nombre, h := range map[string]http.HandlerFunc{
		"con Content-Length": func(w http.ResponseWriter, _ *http.Request) { atom(w, grande) },
		"sin Content-Length (troceada)": func(w http.ResponseWriter, _ *http.Request) {
			w.Header().Set("Content-Type", "application/xml")
			for i := 0; i < 10; i++ {
				_, _ = w.Write([]byte(grande[:100]))
				if f, ok := w.(http.Flusher); ok {
					f.Flush()
				}
			}
		},
	} {
		t.Run(nombre, func(t *testing.T) {
			c, srv, _ := clienteLocal(t, h, Options{MaxBytes: 500})
			if _, err := c.Fetch(context.Background(), srv.URL, Validators{}); !errors.Is(err, ErrTooLarge) {
				t.Fatalf("error = %v, quería ErrTooLarge", err)
			}
		})
	}
}

func TestSoloXml(t *testing.T) {
	c, srv, _ := clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte("<html/>"))
	}), Options{})
	if _, err := c.Fetch(context.Background(), srv.URL, Validators{}); !errors.Is(err, ErrContentType) {
		t.Fatalf("error = %v, quería ErrContentType", err)
	}
}

func TestRedireccionFueraDeLaListaBlancaSeRechaza(t *testing.T) {
	c, srv, _ := clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "http://metadata.interno.test/latest", http.StatusFound)
	}), Options{})
	if _, err := c.Fetch(context.Background(), srv.URL, Validators{}); !errors.Is(err, ErrNotAllowed) {
		t.Fatalf("error = %v, quería ErrNotAllowed", err)
	}
}

func TestDemasiadasRedirecciones(t *testing.T) {
	var c *Client
	var srv *httptest.Server
	c, srv, _ = clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, srv.URL+"/otra", http.StatusFound) }), Options{})
	if _, err := c.Fetch(context.Background(), srv.URL, Validators{}); !errors.Is(err, ErrNotAllowed) {
		t.Fatalf("error = %v, quería ErrNotAllowed por exceso de saltos", err)
	}
}

func TestRedireccionPermitidaSeSigue(t *testing.T) {
	c, srv, _ := clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/nueva" {
			atom(w, "<feed/>")
			return
		}
		http.Redirect(w, r, "/nueva", http.StatusMovedPermanently)
	}), Options{})
	res, err := c.Fetch(context.Background(), srv.URL+"/vieja", Validators{})
	if err != nil || !strings.HasSuffix(res.URL, "/nueva") {
		t.Fatalf("debería seguir la redirección: %+v %v", res, err)
	}
}

// Con el cliente de producción (sin el modo de pruebas) se comprueban esquema, puerto, lista blanca y direcciones.
func TestControlesDeProduccion(t *testing.T) {
	c, err := New(Options{AllowedHosts: []string{"contrataciondelestado.es", "interno.test"}})
	if err != nil {
		t.Fatal(err)
	}
	c.lookup = func(_ context.Context, host string) ([]netip.Addr, error) {
		switch host {
		case "interno.test":
			return []netip.Addr{netip.MustParseAddr("10.0.0.5")}, nil
		case "mixto.test":
			return []netip.Addr{netip.MustParseAddr("93.184.216.34"), netip.MustParseAddr("127.0.0.1")}, nil
		}
		return nil, errors.New("no existe")
	}
	c2, _ := New(Options{AllowedHosts: []string{"mixto.test"}})
	c2.lookup = c.lookup

	for nombre, caso := range map[string]struct {
		cli *Client
		url string
	}{
		"http":                       {c, "http://contrataciondelestado.es/x.atom"},
		"servidor no permitido":      {c, "https://evil.test/x.atom"},
		"puerto 8443":                {c, "https://contrataciondelestado.es:8443/x.atom"},
		"usuario en la URL":          {c, "https://user:pw@contrataciondelestado.es/x.atom"},
		"resuelve a privada":         {c, "https://interno.test/x.atom"},
		"una pública y una de bucle": {c2, "https://mixto.test/x.atom"},
		"IP literal":                 {c, "https://169.254.169.254/latest"},
		"esquema file":               {c, "file:///etc/passwd"},
	} {
		t.Run(nombre, func(t *testing.T) {
			if _, err := caso.cli.Fetch(context.Background(), caso.url, Validators{}); !errors.Is(err, ErrNotAllowed) {
				t.Fatalf("error = %v, quería ErrNotAllowed", err)
			}
		})
	}
}

func TestSinListaBlancaNoSeCreaElCliente(t *testing.T) {
	if _, err := New(Options{}); err == nil {
		t.Fatal("sin lista blanca debe fallar")
	}
}

func TestContextoCancelado(t *testing.T) {
	c, srv, _ := clienteLocal(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { atom(w, "<feed/>") }), Options{})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := c.Fetch(ctx, srv.URL, Validators{}); !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v, quería context.Canceled", err)
	}
}

func TestIsPublic(t *testing.T) {
	for ip, quiere := range map[string]bool{
		"93.184.216.34": true, "8.8.8.8": true, "2606:2800:220:1:248:1893:25c8:1946": true,
		"127.0.0.1": false, "10.1.2.3": false, "172.16.0.1": false, "192.168.1.1": false, "169.254.169.254": false,
		"100.64.0.1": false, "0.0.0.0": false, "224.0.0.1": false, "::1": false, "fe80::1": false, "fc00::1": false,
		"::ffff:10.0.0.1": false, "::ffff:8.8.8.8": true,
	} {
		if got := isPublic(netip.MustParseAddr(ip)); got != quiere {
			t.Errorf("isPublic(%s) = %v, quería %v", ip, got, quiere)
		}
	}
}
