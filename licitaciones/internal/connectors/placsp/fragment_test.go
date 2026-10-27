package placsp

import (
	"bytes"
	"errors"
	"os"
	"testing"
)

// Releer cada original guardado tiene que dar el mismo registro y el mismo SHA-256 que la página de la que salió.
func TestParseFragmentDaLoMismoQueLaPagina(t *testing.T) {
	b, err := os.ReadFile("../../../testdata/placsp_643/extracto_licitacionesPerfilesContratanteCompleto3_20261025_200314.atom")
	if err != nil {
		t.Fatal(err)
	}
	var recs []Record
	if _, err := ParseFeed(bytes.NewReader(b), Options{Source: "placsp-643"}, func(r Record) error { recs = append(recs, r); return nil }); err != nil {
		t.Fatal(err)
	}
	if len(recs) == 0 {
		t.Fatal("la muestra no tiene entradas")
	}
	for i, r := range recs {
		x, err := ParseFragment(r.Raw, Options{Source: "placsp-643"})
		if err != nil {
			t.Fatalf("entrada %d: %v", i, err)
		}
		if x.RawSHA256 != r.RawSHA256 {
			t.Errorf("entrada %d: SHA-256 distinto", i)
		}
		switch {
		case r.Licitacion != nil:
			if x.Licitacion == nil || x.Licitacion.SourceID != r.Licitacion.SourceID || x.Licitacion.Title != r.Licitacion.Title ||
				len(x.Licitacion.CPV) != len(r.Licitacion.CPV) || len(x.Licitacion.Results) != len(r.Licitacion.Results) {
				t.Errorf("entrada %d: licitación distinta", i)
			}
		case r.Baja != nil:
			if x.Baja == nil || x.Baja.Ref != r.Baja.Ref || x.Baja.Kind != r.Baja.Kind {
				t.Errorf("entrada %d: baja distinta", i)
			}
		}
	}
}

func TestParseFragmentExigeUnaSolaEntrada(t *testing.T) {
	for nombre, raw := range map[string][]byte{"vacío": nil, "dos": []byte(`<entry><id>a</id></entry><entry><id>b</id></entry>`)} {
		if _, err := ParseFragment(raw, Options{Source: "placsp-643"}); !errors.Is(err, ErrNotOneEntry) {
			t.Errorf("%s: error = %v", nombre, err)
		}
	}
}

func TestParseFragmentRechazaDTD(t *testing.T) {
	if _, err := ParseFragment([]byte(`<!DOCTYPE x [<!ENTITY e "x">]><entry><id>a</id></entry>`), Options{Source: "placsp-643"}); err == nil {
		t.Fatal("un DTD debe rechazarse")
	}
}
