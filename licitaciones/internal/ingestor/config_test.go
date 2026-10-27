package ingestor

import (
	"strings"
	"testing"
	"time"
)

func env(m map[string]string) func(string) string { return func(k string) string { return m[k] } }

func base() map[string]string {
	return map[string]string{EnvPG: "postgres://u:p@h/d", EnvS3Endpoint: "s3:9000", EnvS3User: "u", EnvS3Clave: "p", EnvNATS: "nats://nats:4222"}
}

func TestConfigPorDefecto(t *testing.T) {
	c, err := FromEnv(env(base()))
	if err != nil {
		t.Fatal(err)
	}
	if c.Interval != time.Hour || c.MaxPages != 50 || c.Timeout != 5*time.Minute || len(c.Sources) != 1 || c.Sources[0] != "placsp-643" || c.S3Secure {
		t.Fatalf("valores por defecto inesperados: %+v", c)
	}
}

func TestConfigValoresPropios(t *testing.T) {
	m := base()
	m[EnvSources], m[EnvInterval], m[EnvMaxPages], m[EnvS3Secure] = "placsp-1044, placsp-643,placsp-1044", "30m", "7", "true"
	c, err := FromEnv(env(m))
	if err != nil {
		t.Fatal(err)
	}
	if len(c.Sources) != 2 || c.Sources[0] != "placsp-1044" || c.Interval != 30*time.Minute || c.MaxPages != 7 || !c.S3Secure {
		t.Fatalf("config = %+v", c)
	}
}

func TestConfigErrores(t *testing.T) {
	for nombre, cambio := range map[string]map[string]string{
		"fuente desconocida": {EnvSources: "boe"},
		"intervalo corto":    {EnvInterval: "1m"},
		"intervalo roto":     {EnvInterval: "rápido"},
		"páginas fuera":      {EnvMaxPages: "0"},
		"seguro roto":        {EnvS3Secure: "quizá"},
		"nats sin servidor":  {EnvNATS: "nada"},
		"plazo muy corto":    {EnvTimeout: "5s"},
		"plazo muy largo":    {EnvTimeout: "2h"},
	} {
		m := base()
		for k, v := range cambio {
			m[k] = v
		}
		if _, err := FromEnv(env(m)); err == nil {
			t.Errorf("%s: debía fallar", nombre)
		}
	}
}

func TestConfigFaltanObligatorias(t *testing.T) {
	_, err := FromEnv(env(map[string]string{EnvS3Clave: "clave-secreta-123"}))
	if err == nil || !strings.Contains(err.Error(), EnvPG) || !strings.Contains(err.Error(), EnvNATS) {
		t.Fatalf("error = %v", err)
	}
	if strings.Contains(err.Error(), "clave-secreta-123") {
		t.Fatal("el error no debe contener valores")
	}
}

func TestCatalogoSoloApuntaAlHostPermitido(t *testing.T) {
	for n, u := range Catalog {
		if !strings.HasPrefix(u, "https://"+sourceHost+"/") {
			t.Errorf("%s apunta fuera del host permitido: %s", n, u)
		}
	}
}

func TestUserAgent(t *testing.T) {
	if got := userAgent("it@101.cat"); got != "cerebro101-licitaciones/0.1 (+https://101.cat; it@101.cat)" {
		t.Fatal(got)
	}
}
