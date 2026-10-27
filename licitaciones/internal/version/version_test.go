package version

import "testing"

func TestStringUsaLaVersionFijada(t *testing.T) {
	old := Version
	t.Cleanup(func() { Version = old })
	Version = "abc123"
	if got := String(); got != "abc123" {
		t.Fatalf("String() = %q, quería abc123", got)
	}
}

func TestStringNuncaEstaVacia(t *testing.T) {
	old := Version
	t.Cleanup(func() { Version = old })
	Version = "dev"
	if String() == "" {
		t.Fatal("la versión no puede estar vacía")
	}
}
