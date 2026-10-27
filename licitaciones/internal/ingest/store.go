// Package ingest ejecuta la ingesta de las fuentes: descarga las páginas, guarda el original como evidencia, normaliza cada entrada y decide
// si es nueva, modificada o ya conocida, dejando un evento por cada cambio (ADR 0003).
//
// Este paquete solo define lo que necesita de fuera mediante interfaces (RawStore para el original, State para el estado operativo y el
// outbox, Fetcher para la descarga). Hay implementaciones en memoria para las pruebas y el desarrollo; las de MinIO y Postgres llegan
// en los PR siguientes sin tocar la lógica.
package ingest

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"regexp"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/fetch"
)

// Fetcher descarga una página; lo satisface *fetch.Client.
type Fetcher interface {
	Fetch(ctx context.Context, url string, v fetch.Validators) (fetch.Result, error)
}

// RawObject es un original inmutable. Key es determinista: el mismo contenido da siempre la misma clave.
type RawObject struct {
	Key    string
	Data   []byte
	SHA256 string            // de Data, en hexadecimal
	Meta   map[string]string // procedencia: url-origen, capturado-en, fuente, id-origen…
}

// RawStore guarda la evidencia. PutRaw no sobrescribe: si la clave ya existe con el mismo SHA-256 devuelve created=false.
type RawStore interface {
	PutRaw(ctx context.Context, o RawObject) (created bool, err error)
}

// Kind es el resultado de observar una entrada.
type Kind string

// Resultados posibles de Observe.
const (
	KindNew       Kind = "nueva"
	KindModified  Kind = "modificada"
	KindUnchanged Kind = "sin_cambios" // mismo contenido normalizado: repetir la ingesta no duplica
	KindStale     Kind = "antigua"     // llega una versión anterior a la que ya se conoce: se ignora
)

// Flags resume en qué punto del ciclo de vida está un expediente; sirve para clasificar los eventos sin guardar el registro completo.
type Flags uint8

// Marcas del ciclo de vida.
const (
	FlagAwarded    Flags = 1 << iota // algún lote adjudicado
	FlagFormalized                   // algún lote formalizado
	FlagAnnulled                     // anulado o dado de baja
)

// Observation es lo que el ingestor ha visto de una entrada.
type Observation struct {
	Source     string
	SourceID   string
	Hash       string // hash del registro normalizado (sin metadatos de captura)
	RawSHA256  string
	RawKey     string
	Updated    time.Time // atom:updated de la entrada
	Flags      Flags
	Removed    bool // baja (at:deleted-entry): no lleva registro normalizado
	ObservedAt time.Time
}

// Event es un cambio que debe llegar a los consumidores (se publica desde el outbox).
type Event struct {
	ID        string // determinista: (tipo, fuente, id, versión)
	Type      string // licitacion.nueva, .modificada, .adjudicada, .formalizada, .anulada
	Source    string
	SourceID  string
	Version   int
	RawSHA256 string
	RawKey    string
}

// Outcome es la decisión sobre una observación. Event solo va informado cuando hay un cambio.
type Outcome struct {
	Kind    Kind
	Version int
	Event   *Event
}

// Checkpoint es el punto de control de una fuente: cuándo se ingirió por última vez y los validadores de la primera página.
type Checkpoint struct {
	LastRun    time.Time
	Validators fetch.Validators
}

// State es el estado operativo de la ingesta. Observe debe ser atómico: la vista del expediente y el evento del outbox se escriben en
// la misma transacción (ADR 0003, opción C). Lo usa un único escritor (cerrojo de líder).
type State interface {
	Observe(ctx context.Context, o Observation) (Outcome, error)
	Checkpoint(ctx context.Context, source string) (Checkpoint, error)
	SaveCheckpoint(ctx context.Context, source string, c Checkpoint) error
}

var seguro = regexp.MustCompile(`^[A-Za-z0-9._-]{1,64}$`)

// RawKey construye la clave del original de una entrada: `{fuente}/{año}/{mes}/{id}/{sha256}.xml` (ADR 0004). El año y el mes salen de la fecha
// de actualización en origen, de modo que la misma entrada da siempre la misma clave. Un id con caracteres no seguros se sustituye por
// «h-» y los 32 primeros hexadecimales del SHA-256 del id (el id exacto va en los metadatos).
func RawKey(source, id string, updated time.Time, sha string) string {
	u := updated.UTC()
	return fmt.Sprintf("%s/%04d/%02d/%s/%s.xml", source, u.Year(), int(u.Month()), claveID(id), sha)
}

// PageKey es la clave de la página descargada (evidencia de la descarga): `{fuente}/_paginas/{año}/{mes}/{día}/{sha256}.xml`.
func PageKey(source string, fetched time.Time, sha string) string {
	u := fetched.UTC()
	return fmt.Sprintf("%s/_paginas/%04d/%02d/%02d/%s.xml", source, u.Year(), int(u.Month()), u.Day(), sha)
}

func claveID(id string) string {
	if seguro.MatchString(id) && id != "." && id != ".." {
		return id
	}
	h := sha256.Sum256([]byte(id))
	return "h-" + hex.EncodeToString(h[:])[:32]
}

func sha256Hex(b []byte) string {
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

func eventID(typ, source, id string, version int) string {
	h := sha256.Sum256([]byte(fmt.Sprintf("%s|%s|%s|%d", typ, source, id, version)))
	return hex.EncodeToString(h[:])[:32]
}
