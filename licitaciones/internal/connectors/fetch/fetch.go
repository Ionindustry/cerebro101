// Package fetch es el cliente HTTP con el que el ingestor descarga las páginas de las fuentes públicas. Es la única salida a internet del
// motor (NORMAS, «Seguridad»), así que aplica los controles anti-SSRF antes de abrir ninguna conexión:
//   - solo https, puerto 443 y servidores de una lista blanca;
//   - el nombre se resuelve una vez, se comprueba que todas las direcciones son públicas (nada de bucle, redes privadas ni enlace local)
//     y la conexión se hace a esa dirección ya comprobada, sin volver a resolver;
//   - cada redirección se valida igual que la petición inicial y hay un máximo de saltos;
//   - tamaño máximo de la respuesta, plazo total, solo texto XML y reintentos acotados con espera creciente.
package fetch

import (
	"context"
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"slices"
	"strings"
	"time"
)

// Valores por defecto.
const (
	DefaultMaxBytes  = 64 << 20
	DefaultTimeout   = 60 * time.Second
	DefaultRetries   = 2 // reintentos tras el primer intento (429 y 5xx)
	maxRedirects     = 3
	defaultUserAgent = "cerebro101-licitaciones/0.1 (+https://101.cat)"
)

// Errores identificables por quien llama.
var (
	ErrNotAllowed  = errors.New("fetch: dirección no permitida")
	ErrTooLarge    = errors.New("fetch: respuesta demasiado grande")
	ErrContentType = errors.New("fetch: tipo de contenido no admitido")
	ErrStatus      = errors.New("fetch: respuesta con error")
)

// Options configura el cliente. AllowedHosts es obligatorio: sin lista blanca no se descarga nada.
type Options struct {
	AllowedHosts []string
	MaxBytes     int64
	Timeout      time.Duration
	Retries      int // 0 = DefaultRetries; negativo = sin reintentos
	UserAgent    string
}

// Validators son los validadores de una descarga anterior, para pedir solo si ha cambiado (304).
type Validators struct {
	ETag         string
	LastModified string
}

// Result es una descarga.
type Result struct {
	URL         string // dirección final, tras las redirecciones
	Body        []byte
	NotModified bool // respuesta 304: Body vacío
	Validators  Validators
	FetchedAt   time.Time
}

// Client descarga páginas con los controles descritos en el paquete.
type Client struct {
	hosts      []string
	maxBytes   int64
	retries    int
	userAgent  string
	http       *http.Client
	now        func() time.Time
	sleep      func(context.Context, time.Duration) error
	lookup     func(ctx context.Context, host string) ([]netip.Addr, error)
	testHTTP   bool // solo pruebas: admite http y direcciones locales
	baseDialer net.Dialer
}

// New crea el cliente.
func New(o Options) (*Client, error) {
	if len(o.AllowedHosts) == 0 {
		return nil, errors.New("fetch: falta la lista blanca de servidores (Options.AllowedHosts)")
	}
	c := &Client{
		maxBytes: o.MaxBytes, retries: o.Retries, userAgent: o.UserAgent,
		now: time.Now, sleep: sleepCtx,
		baseDialer: net.Dialer{Timeout: 10 * time.Second},
	}
	for _, h := range o.AllowedHosts {
		c.hosts = append(c.hosts, strings.ToLower(strings.TrimSpace(h)))
	}
	if c.maxBytes <= 0 {
		c.maxBytes = DefaultMaxBytes
	}
	if c.retries < 0 {
		c.retries = 0
	} else if o.Retries == 0 {
		c.retries = DefaultRetries
	}
	if c.userAgent == "" {
		c.userAgent = defaultUserAgent
	}
	timeout := o.Timeout
	if timeout <= 0 {
		timeout = DefaultTimeout
	}
	c.lookup = func(ctx context.Context, host string) ([]netip.Addr, error) {
		return net.DefaultResolver.LookupNetIP(ctx, "ip", host)
	}
	c.http = &http.Client{
		Timeout: timeout,
		Transport: &http.Transport{
			DialContext:            c.dialPinned,
			TLSHandshakeTimeout:    10 * time.Second,
			ResponseHeaderTimeout:  30 * time.Second,
			MaxResponseHeaderBytes: 1 << 16,
			DisableCompression:     false,
			Proxy:                  nil, // sin proxys del entorno: la salida va directa y comprobada
		},
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) > maxRedirects {
				return fmt.Errorf("%w: demasiadas redirecciones", ErrNotAllowed)
			}
			return c.checkURL(req.URL)
		},
	}
	return c, nil
}

// Fetch descarga rawURL. Con validadores pide la descarga condicional y puede devolver NotModified.
func (c *Client) Fetch(ctx context.Context, rawURL string, v Validators) (Result, error) {
	u, err := url.Parse(rawURL)
	if err != nil {
		return Result{}, fmt.Errorf("%w: %w", ErrNotAllowed, err)
	}
	if err := c.checkURL(u); err != nil {
		return Result{}, err
	}
	var lastErr error
	for attempt := 0; attempt <= c.retries; attempt++ {
		if attempt > 0 {
			if err := c.sleep(ctx, time.Duration(1<<(attempt-1))*time.Second); err != nil {
				return Result{}, err
			}
		}
		res, retry, err := c.once(ctx, u.String(), v)
		if err == nil {
			return res, nil
		}
		lastErr = err
		if !retry {
			break
		}
	}
	return Result{}, lastErr
}

// once hace un intento. retry indica si el error merece otro intento (429, 5xx o fallo de red).
func (c *Client) once(ctx context.Context, rawURL string, v Validators) (Result, bool, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return Result{}, false, err
	}
	req.Header.Set("User-Agent", c.userAgent)
	req.Header.Set("Accept", "application/atom+xml, application/xml;q=0.9, text/xml;q=0.8")
	if v.ETag != "" {
		req.Header.Set("If-None-Match", v.ETag)
	}
	if v.LastModified != "" {
		req.Header.Set("If-Modified-Since", v.LastModified)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		if errors.Is(err, ErrNotAllowed) || ctx.Err() != nil {
			return Result{}, false, err
		}
		return Result{}, true, fmt.Errorf("fetch: %w", err)
	}
	defer resp.Body.Close()

	res := Result{
		URL: resp.Request.URL.String(), FetchedAt: c.now().UTC(),
		Validators: Validators{ETag: resp.Header.Get("ETag"), LastModified: resp.Header.Get("Last-Modified")},
	}
	switch {
	case resp.StatusCode == http.StatusNotModified:
		res.NotModified = true
		return res, false, nil
	case resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500:
		return Result{}, true, fmt.Errorf("%w: %s", ErrStatus, resp.Status)
	case resp.StatusCode != http.StatusOK:
		return Result{}, false, fmt.Errorf("%w: %s", ErrStatus, resp.Status)
	}
	if err := checkContentType(resp.Header.Get("Content-Type")); err != nil {
		return Result{}, false, err
	}
	if resp.ContentLength > c.maxBytes {
		return Result{}, false, ErrTooLarge
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, c.maxBytes+1))
	if err != nil {
		return Result{}, true, fmt.Errorf("fetch: leer la respuesta: %w", err)
	}
	if int64(len(body)) > c.maxBytes {
		return Result{}, false, ErrTooLarge
	}
	res.Body = body
	return res, false, nil
}

func checkContentType(h string) error {
	mt, _, err := mime.ParseMediaType(h)
	if err != nil {
		return fmt.Errorf("%w: %q", ErrContentType, h)
	}
	if mt == "application/atom+xml" || mt == "application/xml" || mt == "text/xml" || strings.HasSuffix(mt, "+xml") {
		return nil
	}
	return fmt.Errorf("%w: %q", ErrContentType, mt)
}

// checkURL aplica la lista blanca, el esquema y el puerto (la comprobación de direcciones IP se hace al conectar).
func (c *Client) checkURL(u *url.URL) error {
	if u.User != nil {
		return fmt.Errorf("%w: la dirección no puede llevar usuario ni contraseña", ErrNotAllowed)
	}
	if u.Scheme != "https" && (!c.testHTTP || u.Scheme != "http") {
		return fmt.Errorf("%w: solo https", ErrNotAllowed)
	}
	host := strings.ToLower(u.Hostname())
	if !slices.Contains(c.hosts, host) {
		return fmt.Errorf("%w: servidor %q fuera de la lista blanca", ErrNotAllowed, host)
	}
	if p := u.Port(); p != "" && p != "443" && !c.testHTTP {
		return fmt.Errorf("%w: solo el puerto 443", ErrNotAllowed)
	}
	return nil
}

// dialPinned resuelve el nombre, comprueba que todas las direcciones son públicas y conecta a una de ellas sin volver a resolver.
func (c *Client) dialPinned(ctx context.Context, network, addr string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(addr)
	if err != nil {
		return nil, err
	}
	var addrs []netip.Addr
	if ip, err := netip.ParseAddr(host); err == nil {
		addrs = []netip.Addr{ip}
	} else if addrs, err = c.lookup(ctx, host); err != nil {
		return nil, fmt.Errorf("fetch: resolver %s: %w", host, err)
	}
	if len(addrs) == 0 {
		return nil, fmt.Errorf("fetch: %s no tiene direcciones", host)
	}
	if !c.testHTTP {
		for _, a := range addrs {
			if !isPublic(a) {
				return nil, fmt.Errorf("%w: %s resuelve a una dirección no pública (%s)", ErrNotAllowed, host, a)
			}
		}
	}
	var lastErr error
	for _, a := range addrs {
		conn, err := c.baseDialer.DialContext(ctx, network, net.JoinHostPort(a.String(), port))
		if err == nil {
			return conn, nil
		}
		lastErr = err
	}
	return nil, lastErr
}

var cgnat = netip.MustParsePrefix("100.64.0.0/10")

// isPublic dice si una dirección es alcanzable en internet público: nada de bucle, privadas, enlace local, multidifusión ni CGNAT.
func isPublic(a netip.Addr) bool {
	a = a.Unmap()
	return a.IsGlobalUnicast() && !a.IsPrivate() && !a.IsLoopback() && !a.IsLinkLocalUnicast() && !a.IsMulticast() &&
		!a.IsUnspecified() && !cgnat.Contains(a)
}

func sleepCtx(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-t.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}
