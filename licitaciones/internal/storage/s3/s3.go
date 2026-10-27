// Package s3 guarda los originales (la evidencia) en un almacén compatible con S3: MinIO en el propio servidor, o AWS S3 cambiando solo la
// configuración (ADR 0004). Un original no se sobrescribe nunca: la escritura es condicional (If-None-Match: *) y su clave lleva el SHA-256 del contenido.
package s3

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

// Cubos del motor (ADR 0004).
const (
	BucketRaw        = "raw"        // originales inmutables
	BucketProcessed  = "processed"  // registros normalizados, derivados de raw
	BucketDocs       = "docs"       // pliegos y documentos, ya revisados
	BucketQuarantine = "quarantine" // documentos pendientes del antivirus
)

// Config es la conexión. Secure activa TLS (en producción, dentro de la red de Docker, puede ir sin él y con el puerto sin publicar).
type Config struct {
	Endpoint  string // «minio:9000»
	AccessKey string
	SecretKey string
	Secure    bool
	Raw       string // cubo de los originales; por defecto «raw»
}

// Store implementa ingest.RawStore sobre S3.
type Store struct {
	cli *minio.Client
	raw string
}

var _ ingest.RawStore = (*Store)(nil)

// New crea el cliente. No abre ninguna conexión todavía.
func New(c Config) (*Store, error) {
	if c.Endpoint == "" || c.AccessKey == "" || c.SecretKey == "" {
		return nil, errors.New("s3: faltan el servidor, la clave de acceso o la clave secreta")
	}
	cli, err := minio.New(c.Endpoint, &minio.Options{Creds: credentials.NewStaticV4(c.AccessKey, c.SecretKey, ""), Secure: c.Secure})
	if err != nil {
		return nil, fmt.Errorf("s3: crear el cliente: %w", err)
	}
	raw := c.Raw
	if raw == "" {
		raw = BucketRaw
	}
	return &Store{cli: cli, raw: raw}, nil
}

// EnsureBuckets crea los cubos que falten. El de originales se crea con el bloqueo de objetos activado (hay que decidirlo al crearlo: después no se puede);
// la retención por defecto se fija aparte según la política de conservación.
func (s *Store) EnsureBuckets(ctx context.Context) error {
	for _, b := range []struct {
		name string
		lock bool
	}{{s.raw, true}, {BucketProcessed, false}, {BucketDocs, false}, {BucketQuarantine, false}} {
		ok, err := s.cli.BucketExists(ctx, b.name)
		if err != nil {
			return fmt.Errorf("s3: comprobar el cubo %s: %w", b.name, err)
		}
		if ok {
			continue
		}
		if err := s.cli.MakeBucket(ctx, b.name, minio.MakeBucketOptions{ObjectLocking: b.lock}); err != nil {
			return fmt.Errorf("s3: crear el cubo %s: %w", b.name, err)
		}
	}
	return nil
}

// PutRaw guarda el original sin sobrescribirlo. Si la clave ya existe con el mismo SHA-256 devuelve created=false (es la misma evidencia);
// con otro SHA-256 es un error (la clave lleva el hash, no debería pasar).
func (s *Store) PutRaw(ctx context.Context, o ingest.RawObject) (bool, error) {
	meta := make(map[string]string, len(o.Meta)+1)
	for k, v := range o.Meta {
		if v != "" {
			meta[k] = asciiMeta(v)
		}
	}
	meta["sha256"] = o.SHA256 // el SHA-256 de los bytes manda sobre lo que traiga Meta
	opts := minio.PutObjectOptions{ContentType: "application/xml", UserMetadata: meta}
	opts.SetMatchETagExcept("*") // If-None-Match: *

	_, err := s.cli.PutObject(ctx, s.raw, o.Key, bytes.NewReader(o.Data), int64(len(o.Data)), opts)
	if err == nil {
		return true, nil
	}
	if !preconditionFailed(err) {
		return false, fmt.Errorf("s3: guardar %s: %w", o.Key, err)
	}
	st, serr := s.cli.StatObject(ctx, s.raw, o.Key, minio.StatObjectOptions{})
	if serr != nil {
		return false, fmt.Errorf("s3: comprobar el original existente %s: %w", o.Key, serr)
	}
	if got := userMeta(st.UserMetadata, "sha256"); got != o.SHA256 {
		return false, fmt.Errorf("s3: la clave %s ya existe con otro SHA-256 (%q frente a %q)", o.Key, got, o.SHA256)
	}
	return false, nil
}

func preconditionFailed(err error) bool {
	r := minio.ToErrorResponse(err)
	return r.StatusCode == http.StatusPreconditionFailed || r.Code == "PreconditionFailed"
}

// userMeta busca un metadato sin distinguir mayúsculas (el servidor devuelve las claves con la inicial en mayúscula).
func userMeta(m map[string]string, key string) string {
	for k, v := range m {
		if strings.EqualFold(k, key) {
			return v
		}
	}
	return ""
}

// asciiMeta deja el valor en ASCII imprimible, que es lo que admiten los metadatos de S3: lo demás se codifica en %XX.
func asciiMeta(v string) string {
	var b strings.Builder
	for _, r := range v {
		if r >= 0x20 && r < 0x7f {
			b.WriteRune(r)
			continue
		}
		b.WriteString(url.QueryEscape(string(r)))
	}
	return b.String()
}
