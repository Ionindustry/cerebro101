package api

import (
	"net/http"
	"time"
)

// Umbrales del estado del motor (contrato: EstadoMotor.umbrales); de momento fijos.
const (
	frescuraObjetivo = 2 * time.Hour
	fuenteCaida      = 6 * time.Hour
	pingLento        = 2 * time.Second
)

type motivo struct {
	Componente string  `json:"componente"`
	Codigo     string  `json:"codigo"`
	Severidad  string  `json:"severidad"`
	Mensaje    string  `json:"mensaje"`
	Desde      *string `json:"desde"`
}

type estadoFuente struct {
	Fuente                string     `json:"fuente"`
	Estado                string     `json:"estado"`
	UltimaIngestaCorrecta *time.Time `json:"ultima_ingesta_correcta"`
	AntiguedadS           *int64     `json:"antiguedad_s"`
	ObjetivoFrescuraS     int64      `json:"objetivo_frescura_s"`
	Documentos            int        `json:"expedientes"`
}

type estadoComponente struct {
	Nombre       string    `json:"nombre"`
	Estado       string    `json:"estado"`
	ComprobadoEn time.Time `json:"comprobado_en"`
	LatenciaMS   *int64    `json:"latencia_ms"`
}

func peor(a, b string) string {
	rank := map[string]int{"ok": 0, "degradado": 1, "caido": 2}
	if rank[b] > rank[a] {
		return b
	}
	return a
}

// estado calcula la instantánea del motor con lo que esta API conoce: la base y el último punto de control de cada fuente. Los demás
// componentes (almacén, bus, retraso de los consumidores) se añadirán cuando la API los consulte.
func (s *Server) estado(w http.ResponseWriter, r *http.Request) {
	now := s.Now().UTC()
	out := map[string]any{
		"estado": "ok", "calculado_en": now, "alcance": "resumen",
		"umbrales": map[string]any{"frescura_objetivo_s": int(frescuraObjetivo.Seconds()), "fuente_caida_s": int(fuenteCaida.Seconds())},
	}
	global := "ok"
	motivos := []motivo{}

	comp := estadoComponente{Nombre: "postgres", Estado: "ok", ComprobadoEn: now}
	if d, err := s.Repo.Ping(r.Context()); err != nil {
		comp.Estado = "caido"
		motivos = append(motivos, motivo{Componente: "postgres", Codigo: "componente_no_responde", Severidad: "caido", Mensaje: "La base de datos no responde."})
		s.Log.Warn("estado: la base no responde", "error", err)
	} else {
		ms := d.Milliseconds()
		comp.LatenciaMS = &ms
		if d > pingLento {
			comp.Estado = "degradado"
			motivos = append(motivos, motivo{Componente: "postgres", Codigo: "componente_no_responde", Severidad: "degradado", Mensaje: "La base de datos responde con lentitud."})
		}
	}
	global = peor(global, comp.Estado)
	out["componentes"] = []estadoComponente{comp}

	fuentes := []estadoFuente{}
	if comp.Estado != "caido" {
		fs, err := s.Repo.Fuentes(r.Context())
		if err != nil {
			s.internal(w, r, err)
			return
		}
		for _, f := range fs {
			ef := estadoFuente{Fuente: fuenteExterna(f.Fuente), Estado: "ok", UltimaIngestaCorrecta: f.UltimaOK, ObjetivoFrescuraS: int64(frescuraObjetivo.Seconds()), Documentos: f.Expediente}
			if f.UltimaOK == nil {
				ef.Estado = "degradado"
				motivos = append(motivos, motivo{Componente: ef.Fuente, Codigo: "fuente_sin_ingesta", Severidad: "degradado", Mensaje: "La fuente no tiene todavía una ingesta completa."})
			} else {
				age := now.Sub(*f.UltimaOK)
				sec := int64(age.Seconds())
				ef.AntiguedadS = &sec
				switch {
				case age > fuenteCaida:
					ef.Estado = "caido"
					motivos = append(motivos, motivo{Componente: ef.Fuente, Codigo: "fuente_sin_ingesta", Severidad: "caido", Mensaje: "La fuente lleva más de 6 horas sin ingesta."})
				case age > frescuraObjetivo:
					ef.Estado = "degradado"
					motivos = append(motivos, motivo{Componente: ef.Fuente, Codigo: "frescura_fuera_de_objetivo", Severidad: "degradado", Mensaje: "La última ingesta supera el objetivo de frescura (2 horas)."})
				}
			}
			global = peor(global, ef.Estado)
			fuentes = append(fuentes, ef)
		}
	}
	out["fuentes"] = fuentes
	out["motivos"] = motivos
	out["estado"] = global
	writeJSON(w, http.StatusOK, out)
}
