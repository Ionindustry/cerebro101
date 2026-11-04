package pg

import (
	"context"
	"testing"
	"time"
)

func TestSolicitudesDeIngestaSeAgrupanYSeVen(t *testing.T) {
	_, st := conectar(t)
	ctx := context.Background()
	antes := time.Now().Add(-time.Minute)
	if hay, err := st.IngestaSolicitadaDesde(ctx, antes); err != nil || hay {
		t.Fatalf("sin peticiones: hay=%v err=%v", hay, err)
	}
	nueva, err := st.SolicitarIngesta(ctx, "albert", time.Minute)
	if err != nil || !nueva {
		t.Fatalf("la primera petición se anota: nueva=%v err=%v", nueva, err)
	}
	if otra, err := st.SolicitarIngesta(ctx, "ana", time.Minute); err != nil || otra {
		t.Fatalf("una segunda a los pocos segundos no se anota: otra=%v err=%v", otra, err)
	}
	if hay, _ := st.IngestaSolicitadaDesde(ctx, antes); !hay {
		t.Fatal("la petición debe verse desde antes de hacerla")
	}
	if hay, _ := st.IngestaSolicitadaDesde(ctx, time.Now().Add(time.Minute)); hay {
		t.Fatal("no debe verse una petición posterior a «desde»")
	}
	if nueva, _ := st.SolicitarIngesta(ctx, "ana", 0); !nueva { // sin hueco mínimo siempre se anota
		t.Fatal("con hueco 0 se anota")
	}
}

func TestSolicitudesViejasSeBorran(t *testing.T) {
	pool, st := conectar(t)
	ctx := context.Background()
	if _, err := pool.Exec(ctx, `INSERT INTO ingest_solicitudes (pedido_en, por) VALUES (now() - interval '8 days', 'vieja')`); err != nil {
		t.Fatal(err)
	}
	if _, err := st.SolicitarIngesta(ctx, "hoy", time.Minute); err != nil {
		t.Fatal(err)
	}
	var n int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM ingest_solicitudes WHERE por = 'vieja'`).Scan(&n); err != nil || n != 0 {
		t.Fatalf("la de hace 8 días debe haberse borrado: n=%d err=%v", n, err)
	}
}
