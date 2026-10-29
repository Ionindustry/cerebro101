package s3

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/minio/minio-go/v7"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

func TestAsciiMeta(t *testing.T) {
	for in, want := range map[string]string{
		"https://x.test/a?b=c":   "https://x.test/a?b=c",
		"Administración Pública": "Administraci%C3%B3n P%C3%BAblica",
		"con\nsalto":             "con%0Asalto",
		"":                       "",
	} {
		if got := asciiMeta(in); got != want {
			t.Errorf("asciiMeta(%q) = %q, quería %q", in, got, want)
		}
	}
}

// RustFS contesta 304 (y no 412) a una escritura condicional sobre un objeto que ya existe: las dos respuestas significan «ya estaba».
func TestPreconditionFailedReconoceLas412YLas304DeRustFS(t *testing.T) {
	for _, e := range []minio.ErrorResponse{
		{StatusCode: http.StatusPreconditionFailed, Code: "PreconditionFailed"},
		{StatusCode: http.StatusNotModified, Code: "NotModified", Message: "304 Not Modified"},
		{Code: "NotModified"},
	} {
		if !preconditionFailed(e) {
			t.Errorf("%+v debería contar como «ya existe»", e)
		}
	}
	for _, e := range []minio.ErrorResponse{{StatusCode: http.StatusInternalServerError, Code: "InternalError"}, {StatusCode: http.StatusForbidden, Code: "AccessDenied"}, {}} {
		if preconditionFailed(e) {
			t.Errorf("%+v no es «ya existe»", e)
		}
	}
	if preconditionFailed(errors.New("otro error")) {
		t.Error("un error cualquiera no es «ya existe»")
	}
}

func TestUserMetaSinDistinguirMayusculas(t *testing.T) {
	if userMeta(map[string]string{"Sha256": "abc"}, "sha256") != "abc" || userMeta(map[string]string{}, "sha256") != "" {
		t.Fatal("userMeta no encuentra el metadato")
	}
}

func TestNewExigeConfiguracion(t *testing.T) {
	for _, c := range []Config{{}, {Endpoint: "x:9000"}, {Endpoint: "x:9000", AccessKey: "a"}} {
		if _, err := New(c); err == nil {
			t.Errorf("New(%+v) debería fallar", c)
		}
	}
	if _, err := New(Config{Endpoint: "x:9000", AccessKey: "a", SecretKey: "b"}); err != nil {
		t.Fatal(err)
	}
}

// Las pruebas siguientes necesitan un servidor S3 de pruebas (RustFS): LICITACIONES_TEST_S3 = «servidor:puerto» y las claves en
// LICITACIONES_TEST_S3_USER y LICITACIONES_TEST_S3_KEY. Sin ellas se omiten.
func conectar(t *testing.T) *Store {
	t.Helper()
	ep := os.Getenv("LICITACIONES_TEST_S3")
	if ep == "" {
		t.Skip("sin LICITACIONES_TEST_S3: pruebas de S3 omitidas")
	}
	s, err := New(Config{Endpoint: ep, AccessKey: os.Getenv("LICITACIONES_TEST_S3_USER"), SecretKey: os.Getenv("LICITACIONES_TEST_S3_KEY"),
		Raw: fmt.Sprintf("raw-prueba-%d", time.Now().UnixNano()%1_000_000_000)})
	if err != nil {
		t.Fatal(err)
	}
	if err := s.EnsureBuckets(context.Background()); err != nil {
		t.Fatalf("EnsureBuckets: %v", err)
	}
	return s
}

func objeto(clave, contenido string) ingest.RawObject {
	h := sha256.Sum256([]byte(contenido))
	return ingest.RawObject{Key: clave, Data: []byte(contenido), SHA256: hex.EncodeToString(h[:]),
		Meta: map[string]string{"fuente": "placsp-643", "url-origen": "https://contrataciondelestado.es/x", "organismo": "Administración Pública"}}
}

func TestPutRawNoSobrescribe(t *testing.T) {
	s := conectar(t)
	ctx := context.Background()
	o := objeto("placsp-643/2026/10/77/abc.xml", "<entry>uno</entry>")
	if c, err := s.PutRaw(ctx, o); err != nil || !c {
		t.Fatalf("primera vez: created = %v, err = %v", c, err)
	}
	if c, err := s.PutRaw(ctx, o); err != nil || c {
		t.Fatalf("segunda vez con el mismo contenido: created = %v, err = %v (esperaba false y sin error)", c, err)
	}
	otro := objeto("placsp-643/2026/10/77/abc.xml", "<entry>otro contenido</entry>")
	if _, err := s.PutRaw(ctx, otro); err == nil || !strings.Contains(err.Error(), "otro SHA-256") {
		t.Fatalf("la misma clave con otro contenido debe fallar, llegó %v", err)
	}
}

func TestPutRawGuardaLaProcedenciaYElContenidoIntacto(t *testing.T) {
	s := conectar(t)
	ctx := context.Background()
	o := objeto("placsp-643/2026/10/78/def.xml", "<entry>contenido</entry>")
	if _, err := s.PutRaw(ctx, o); err != nil {
		t.Fatal(err)
	}
	obj, err := s.cli.GetObject(ctx, s.raw, o.Key, minio.GetObjectOptions{})
	if err != nil {
		t.Fatal(err)
	}
	defer obj.Close()
	st, err := obj.Stat()
	if err != nil {
		t.Fatal(err)
	}
	if userMeta(st.UserMetadata, "sha256") != o.SHA256 || userMeta(st.UserMetadata, "fuente") != "placsp-643" ||
		userMeta(st.UserMetadata, "organismo") != "Administraci%C3%B3n P%C3%BAblica" {
		t.Fatalf("metadatos inesperados: %v", st.UserMetadata)
	}
	buf := make([]byte, st.Size)
	if _, err := obj.Read(buf); err != nil && err.Error() != "EOF" {
		t.Fatal(err)
	}
	if string(buf) != "<entry>contenido</entry>" {
		t.Fatalf("contenido = %q", buf)
	}
}

func TestGetRawDevuelveLoGuardadoYFallaSiNoExiste(t *testing.T) {
	s := conectar(t)
	ctx := context.Background()
	o := objeto("placsp-643/2026/10/79/leer.xml", "<entry>para leer</entry>")
	if _, err := s.PutRaw(ctx, o); err != nil {
		t.Fatal(err)
	}
	got, err := s.GetRaw(ctx, o.Key)
	if err != nil || string(got) != "<entry>para leer</entry>" {
		t.Fatalf("GetRaw = %q, %v", got, err)
	}
	if _, err := s.GetRaw(ctx, "placsp-643/no/existe.xml"); err == nil {
		t.Fatal("un objeto que no existe debe dar error")
	}
}

func TestEnsureBucketsEsIdempotente(t *testing.T) {
	s := conectar(t)
	if err := s.EnsureBuckets(context.Background()); err != nil {
		t.Fatal(err)
	}
}

func TestSeRepiteLaIngestaSinDuplicarOriginales(t *testing.T) {
	s := conectar(t)
	ctx := context.Background()
	creados := 0
	for i := 0; i < 3; i++ {
		for _, n := range []string{"a", "b", "c"} {
			c, err := s.PutRaw(ctx, objeto("placsp-643/2026/10/1/"+n+".xml", "<e>"+n+"</e>"))
			if err != nil {
				t.Fatal(err)
			}
			if c {
				creados++
			}
		}
	}
	if creados != 3 {
		t.Fatalf("originales creados = %d, quería 3 (tres repeticiones no deben duplicar)", creados)
	}
}
