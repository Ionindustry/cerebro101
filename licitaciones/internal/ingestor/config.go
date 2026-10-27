// Package ingestor monta el servicio de ingesta: lee la configuración del entorno, abre las conexiones (Postgres, S3, NATS), toma el cerrojo de
// líder y, cada cierto tiempo, ingiere las fuentes configuradas mientras el relay publica el outbox en el bus.
package ingestor

import (
	"errors"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
)

// Variables de entorno del ingestor.
const (
	EnvPG         = "LIC_PG_URL"       // dirección de Postgres (obligatoria)
	EnvS3Endpoint = "LIC_S3_ENDPOINT"  // «servidor:puerto» del almacén S3 (obligatoria)
	EnvS3User     = "LIC_S3_USUARIO"   // obligatoria
	EnvS3Clave    = "LIC_S3_PASSWORD"  // obligatoria
	EnvS3Secure   = "LIC_S3_SEGURO"    // true si el almacén va por TLS; por defecto false (red interna)
	EnvNATS       = "LIC_NATS_URL"     // obligatoria
	EnvNATSUser   = "LIC_NATS_USUARIO" // vacía = sin autenticación
	EnvNATSClave  = "LIC_NATS_PASSWORD"
	EnvSources    = "LIC_FUENTES"          // fuentes separadas por comas; por defecto placsp-643
	EnvInterval   = "LIC_INTERVALO"        // entre ingestas; por defecto 1h, mínimo 5m (no se castiga a la fuente)
	EnvMaxPages   = "LIC_MAX_PAGINAS"      // tope de páginas por ejecución; por defecto 50
	EnvTimeout    = "LIC_TIMEOUT_DESCARGA" // plazo por descarga; por defecto 5m (PLACSP sirve las páginas despacio), entre 30s y 15m
	EnvContact    = "LIC_CONTACTO"         // correo o web que se anuncia en el User-Agent, para que la fuente sepa a quién avisar
)

// MinInterval es el intervalo mínimo permitido entre ingestas de una misma fuente.
const MinInterval = 5 * time.Minute

// Host permitido para descargar: la lista blanca del cliente HTTP (nada más sale del proceso).
const sourceHost = "contrataciondelestado.es"

// Catalog son las fuentes que sabe ingerir el motor: nombre → dirección de la primera página de la sindicación.
var Catalog = map[string]string{
	domain.SourcePLACSP643:  "https://" + sourceHost + "/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom",
	domain.SourcePLACSP1044: "https://" + sourceHost + "/sindicacion/sindicacion_1044/PlataformasAgregadasSinMenores.atom",
	domain.SourcePLACSP1143: "https://" + sourceHost + "/sindicacion/sindicacion_1143/contratosMenoresPerfilesContratantes.atom",
}

// Config es la configuración ya validada.
type Config struct {
	PG                         string
	S3Endpoint, S3User, S3Pass string
	S3Secure                   bool
	NATS, NATSUser, NATSPass   string
	Sources                    []string
	Interval                   time.Duration
	MaxPages                   int
	Timeout                    time.Duration
	Contact                    string
}

// FromEnv lee y valida la configuración. Los errores nombran la variable, nunca su valor (puede ser una clave).
func FromEnv(getenv func(string) string) (Config, error) {
	c := Config{
		PG: getenv(EnvPG), S3Endpoint: getenv(EnvS3Endpoint), S3User: getenv(EnvS3User), S3Pass: getenv(EnvS3Clave),
		NATS: getenv(EnvNATS), NATSUser: getenv(EnvNATSUser), NATSPass: getenv(EnvNATSClave),
		Interval: time.Hour, MaxPages: 50, Timeout: 5 * time.Minute, Contact: strings.TrimSpace(getenv(EnvContact)),
	}
	var missing []string
	for name, v := range map[string]string{EnvPG: c.PG, EnvS3Endpoint: c.S3Endpoint, EnvS3User: c.S3User, EnvS3Clave: c.S3Pass, EnvNATS: c.NATS} {
		if v == "" {
			missing = append(missing, name)
		}
	}
	if len(missing) > 0 {
		return c, fmt.Errorf("faltan variables de entorno obligatorias: %s", strings.Join(sorted(missing), ", "))
	}
	if u, err := url.Parse(c.NATS); err != nil || u.Host == "" {
		return c, fmt.Errorf("%s no es una dirección válida", EnvNATS)
	}
	if v := getenv(EnvS3Secure); v != "" {
		b, err := strconv.ParseBool(v)
		if err != nil {
			return c, fmt.Errorf("%s no válido: usa true o false", EnvS3Secure)
		}
		c.S3Secure = b
	}
	if v := getenv(EnvInterval); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil {
			return c, fmt.Errorf("%s no válido: usa una duración como 30m o 2h", EnvInterval)
		}
		if d < MinInterval {
			return c, fmt.Errorf("%s: el mínimo es %s", EnvInterval, MinInterval)
		}
		c.Interval = d
	}
	if v := getenv(EnvMaxPages); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 || n > 1000 {
			return c, fmt.Errorf("%s no válido: un número entre 1 y 1000", EnvMaxPages)
		}
		c.MaxPages = n
	}
	if v := getenv(EnvTimeout); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil || d < 30*time.Second || d > 15*time.Minute {
			return c, fmt.Errorf("%s no válido: una duración entre 30s y 15m", EnvTimeout)
		}
		c.Timeout = d
	}
	list := getenv(EnvSources)
	if strings.TrimSpace(list) == "" {
		list = domain.SourcePLACSP643
	}
	seen := map[string]bool{}
	for _, s := range strings.Split(list, ",") {
		s = strings.TrimSpace(s)
		if s == "" || seen[s] {
			continue
		}
		if _, ok := Catalog[s]; !ok {
			return c, fmt.Errorf("%s: fuente desconocida %q (conocidas: %s)", EnvSources, s, strings.Join(catalogNames(), ", "))
		}
		seen[s] = true
		c.Sources = append(c.Sources, s)
	}
	if len(c.Sources) == 0 {
		return c, errors.New(EnvSources + " no indica ninguna fuente")
	}
	return c, nil
}

func catalogNames() []string {
	var n []string
	for k := range Catalog {
		n = append(n, k)
	}
	return sorted(n)
}

func sorted(s []string) []string {
	out := append([]string(nil), s...)
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j] < out[j-1]; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}
