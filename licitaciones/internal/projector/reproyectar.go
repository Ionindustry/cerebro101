package projector

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"log/slog"

	"github.com/ionindustry/cerebro101/licitaciones/internal/connectors/placsp"
	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
	"github.com/ionindustry/cerebro101/licitaciones/internal/storage/pg"
)

// Repo es lo que la reproyección necesita de la base; lo satisface *pg.Store.
type Repo interface {
	ExpedientesParaReproyectar(ctx context.Context, fuente, despues string, limite int) ([]pg.FilaReproyeccion, error)
	ReproyectarExpediente(ctx context.Context, f pg.FilaReproyeccion, l *domain.Licitacion, simular bool) (pg.ResultadoReproyeccion, error)
}

// OpcionesReproyeccion acota una reproyección.
type OpcionesReproyeccion struct {
	Fuente   string // solo esta fuente; vacío = todas
	Limite   int    // como máximo este número de expedientes (0 = todos)
	Despues  string // seguir después de este id de expediente (el último que enseñó una pasada cortada); vacío = desde el principio
	Simular  bool   // no escribe: cuenta cuántos cambiarían
	Pagina   int    // expedientes por consulta a la base (por defecto 500)
	Progreso func(r ResumenReproyeccion)
}

// ResumenReproyeccion cuenta lo que ha pasado con los expedientes revisados.
type ResumenReproyeccion struct {
	Revisados int // expedientes cuyo original se ha releído
	Cambiados int // con un registro normalizado distinto (en simulación, los que cambiarían)
	Iguales   int // el original releído da lo mismo que lo guardado
	Bajas     int // su original actual es una baja de la sindicación: se dejan como están
	Movidos   int // llegó una versión nueva (o una baja) mientras tanto: no se pisan
	Errores   int // el original no se pudo leer, no coincide con su SHA-256 o no se pudo interpretar
	UltimoID  string
	Terminado bool // false si se cortó por el límite o por cancelación
}

// Reproyectar vuelve a leer, uno a uno, los originales de los expedientes ya proyectados y rehace su modelo de lectura con el parser actual (ADR 0003: el modelo de
// lectura se puede regenerar). Es idempotente: se puede repetir o cortar sin riesgo (con Despues se sigue después del último id que enseñó la pasada anterior). Un fallo en un expediente no impide los demás.
func Reproyectar(ctx context.Context, raw Raw, repo Repo, opt OpcionesReproyeccion, log *slog.Logger) (ResumenReproyeccion, error) {
	r := ResumenReproyeccion{UltimoID: opt.Despues}
	pagina := opt.Pagina
	if pagina <= 0 {
		pagina = 500
	}
	for {
		n := pagina
		if opt.Limite > 0 && opt.Limite-r.Revisados < n {
			n = opt.Limite - r.Revisados
		}
		if n <= 0 {
			return r, nil
		}
		filas, err := repo.ExpedientesParaReproyectar(ctx, opt.Fuente, r.UltimoID, n)
		if err != nil {
			return r, err
		}
		if len(filas) == 0 {
			r.Terminado = true
			return r, nil
		}
		for _, f := range filas {
			if err := ctx.Err(); err != nil {
				return r, err
			}
			r.UltimoID = f.ID
			r.Revisados++
			l, resultado := leer(ctx, raw, f)
			switch resultado {
			case leerBaja:
				r.Bajas++
				continue
			case leerError:
				r.Errores++
				log.Warn("reproyección: no se ha podido releer el original", "expediente", f.IDOrigen, "fuente", f.Fuente)
				continue
			}
			res, err := repo.ReproyectarExpediente(ctx, f, l, opt.Simular)
			if err != nil {
				return r, err
			}
			switch res {
			case pg.ReproyCambiado:
				r.Cambiados++
			case pg.ReproyMovido:
				r.Movidos++
			default:
				r.Iguales++
			}
		}
		if opt.Progreso != nil {
			opt.Progreso(r)
		}
	}
}

type resultadoLectura int

const (
	leerOK resultadoLectura = iota
	leerBaja
	leerError
)

func leer(ctx context.Context, raw Raw, f pg.FilaReproyeccion) (*domain.Licitacion, resultadoLectura) {
	b, err := raw.GetRaw(ctx, f.ClaveRaw)
	if err != nil {
		return nil, leerError
	}
	sum := sha256.Sum256(b)
	if hex.EncodeToString(sum[:]) != f.SHA256 { // evidencia alterada o clave que no corresponde: no se proyecta nada de ella
		return nil, leerError
	}
	rec, err := placsp.ParseFragment(b, placsp.Options{Source: f.Fuente})
	switch {
	case err != nil:
		return nil, leerError
	case rec.Baja != nil:
		return nil, leerBaja
	case rec.Licitacion == nil:
		return nil, leerError
	}
	return rec.Licitacion, leerOK
}

// String es el resumen en una línea.
func (r ResumenReproyeccion) String() string {
	return fmt.Sprintf("revisados %d: cambiados %d, iguales %d, bajas %d, movidos %d, errores %d", r.Revisados, r.Cambiados, r.Iguales, r.Bajas, r.Movidos, r.Errores)
}
