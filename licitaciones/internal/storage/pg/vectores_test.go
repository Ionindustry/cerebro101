package pg

import (
	"context"
	"errors"
	"testing"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

// vec construye un vector de prueba: un 1 en la posición i y el resto casi cero, para que «cercano» sea fácil de predecir.
func vec(i int, ruido float32) []float32 {
	v := make([]float32, DimensionesVector)
	v[i] = 1
	v[(i+1)%DimensionesVector] = ruido
	return v
}

func conVectores(t *testing.T) (*Store, context.Context) {
	t.Helper()
	pool, st := conectar(t)
	ctx := context.Background()
	// La extensión la instala el vectorizador; en la prueba va a «public» para que todos los esquemas de prueba la vean.
	if _, err := pool.Exec(ctx, `CREATE EXTENSION IF NOT EXISTS vector SCHEMA public`); err != nil {
		t.Skipf("este PostgreSQL no trae pgvector: %v", err)
	}
	ok, err := st.PrepararVectores(ctx)
	if err != nil || !ok {
		t.Fatalf("preparar: %v %v", ok, err)
	}
	return st, ctx
}

func alta(t *testing.T, st *Store, ctx context.Context, id, titulo string, cpv string, nif string) string {
	t.Helper()
	l := licitacion(id, titulo, "PUB", t0)
	l.CPV = []string{cpv}
	l.Organism.NIF = nif
	ev := ingest.Event{Source: "placsp-643", SourceID: id, Version: 1, RawSHA256: "sha", RawKey: "clave"}
	if ok, err := st.UpsertExpediente(ctx, ev, l); err != nil || !ok {
		t.Fatalf("alta %s: %v %v", id, ok, err)
	}
	var uid string
	if err := st.pool.QueryRow(ctx, `SELECT id::text FROM expedientes WHERE id_origen = $1`, id).Scan(&uid); err != nil {
		t.Fatal(err)
	}
	return uid
}

func TestVectoresPorVectorizarGuardarYBuscar(t *testing.T) {
	st, ctx := conVectores(t)
	a := alta(t, st, ctx, "a/1", "Mantenimiento de software de gestión", "72000000", "P1708500E")
	b := alta(t, st, ctx, "b/1", "Soporte de aplicaciones informáticas", "72000000", "P1708500E")
	c := alta(t, st, ctx, "c/1", "Obras de asfaltado de calles", "45233000", "P0800000A")

	pend, err := st.PorVectorizar(ctx, 10)
	if err != nil || len(pend) != 3 {
		t.Fatalf("por vectorizar: %v %v", pend, err)
	}
	if pend[0].Texto == "" {
		t.Fatal("el texto a vectorizar no debe estar vacío")
	}
	if err := st.GuardarVectores(ctx, "bge-m3", []string{a, b, c}, [][]float32{vec(0, 0.1), vec(0, 0.3), vec(500, 0.1)}); err != nil {
		t.Fatal(err)
	}
	if faltan, hechos, err := st.ContarPorVectorizar(ctx); err != nil || faltan != 0 || hechos != 3 {
		t.Fatalf("contar: faltan=%d hechos=%d %v", faltan, hechos, err)
	}
	if pend, _ := st.PorVectorizar(ctx, 10); len(pend) != 0 {
		t.Fatalf("ya no debería faltar ninguno: %v", pend)
	}

	filas, err := st.BuscarPorSignificado(ctx, Filtro{Limit: 10}, vec(0, 0), 3)
	if err != nil || len(filas) != 3 {
		t.Fatalf("buscar: %v %v", filas, err)
	}
	if filas[0].ID != a || filas[1].ID != b || filas[2].ID != c {
		t.Fatalf("orden por cercanía inesperado: %s %s %s", filas[0].Titulo, filas[1].Titulo, filas[2].Titulo)
	}
	// Los filtros se respetan: con el CPV de las obras solo sale c.
	filas, err = st.BuscarPorSignificado(ctx, Filtro{CPV: []string{"45"}}, vec(0, 0), 5)
	if err != nil || len(filas) != 1 || filas[0].ID != c {
		t.Fatalf("con filtro de CPV: %v %v", filas, err)
	}

	p, err := st.Parecidas(ctx, a, 5)
	if err != nil || len(p) != 2 || p[0].ID != b {
		t.Fatalf("parecidas: %v %v", p, err)
	}
	if !p[0].MismoComprador || !p[0].CPVEnComun || p[1].MismoComprador || p[1].CPVEnComun {
		t.Fatalf("el porqué de la cercanía es incorrecto: %+v %+v", p[0], p[1])
	}
	if p[0].Distancia >= p[1].Distancia {
		t.Fatalf("las parecidas deben venir de más cerca a más lejos: %v %v", p[0].Distancia, p[1].Distancia)
	}
}

func TestVectoresCambiarElExpedienteLoMarcaPendienteYBorrarloBorraSuVector(t *testing.T) {
	st, ctx := conVectores(t)
	a := alta(t, st, ctx, "a/1", "Mantenimiento de software", "72000000", "P1708500E")
	if err := st.GuardarVectores(ctx, "bge-m3", []string{a}, [][]float32{vec(0, 0)}); err != nil {
		t.Fatal(err)
	}
	// Un expediente que se vuelve a proyectar (versión nueva) tiene que revectorizarse.
	l := licitacion("a/1", "Mantenimiento de software y soporte", "PUB", t0)
	ev := ingest.Event{Source: "placsp-643", SourceID: "a/1", Version: 2, RawSHA256: "sha2", RawKey: "clave2"}
	l.Updated = t0.Add(1)
	if ok, err := st.UpsertExpediente(ctx, ev, l); err != nil || !ok {
		t.Fatalf("v2: %v %v", ok, err)
	}
	if pend, err := st.PorVectorizar(ctx, 10); err != nil || len(pend) != 1 || pend[0].ID != a {
		t.Fatalf("debería quedar pendiente: %v %v", pend, err)
	}
	if _, err := st.pool.Exec(ctx, `DELETE FROM expedientes WHERE id = $1::uuid`, a); err != nil {
		t.Fatal(err)
	}
	if _, hechos, _ := st.ContarPorVectorizar(ctx); hechos != 0 {
		t.Fatalf("el vector debía borrarse con el expediente: %d", hechos)
	}
}

func TestParecidasErrores(t *testing.T) {
	st, ctx := conVectores(t)
	if _, err := st.Parecidas(ctx, "00000000-0000-0000-0000-000000000000", 5); !errors.Is(err, ErrNoEncontrado) {
		t.Fatalf("no existe: %v", err)
	}
	a := alta(t, st, ctx, "a/1", "Algo", "72000000", "P1708500E")
	if _, err := st.Parecidas(ctx, a, 5); !errors.Is(err, ErrSinVector) {
		t.Fatalf("sin vector: %v", err)
	}
	if err := st.GuardarVectores(ctx, "bge-m3", []string{a}, [][]float32{{1, 2}}); err == nil {
		t.Fatal("un vector de otro tamaño debe rechazarse")
	}
}
