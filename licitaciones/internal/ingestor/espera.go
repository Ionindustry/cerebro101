package ingestor

import (
	"context"
	"log/slog"
	"time"
)

// pollPeticiones es cada cuánto se mira, mientras se espera a la siguiente vuelta, si alguien ha pedido una actualización inmediata.
const pollPeticiones = 10 * time.Second

// Peticiones lo implementa el almacén (*pg.Store): dice si alguien ha pedido una ingesta después de un instante (la API del motor anota la petición cuando se abre la aplicación y
// lo último ingerido es viejo).
type Peticiones interface {
	IngestaSolicitadaDesde(ctx context.Context, desde time.Time) (bool, error)
}

// esperar duerme hasta wait, pero se despierta antes si alguien ha pedido una ingesta después de desde (el comienzo de la vuelta que acaba de terminar): así lo que se pide mientras el
// ingestor trabaja se atiende justo al terminar, y lo que se pide mientras duerme, en como mucho pollPeticiones. fuente puede ser nil (sin peticiones: duerme todo el intervalo).
func esperar(ctx context.Context, fuente any, desde time.Time, wait time.Duration, log *slog.Logger) error {
	p, _ := fuente.(Peticiones)
	fin := time.NewTimer(wait)
	defer fin.Stop()
	if p == nil {
		select {
		case <-fin.C:
			return nil
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	tick := time.NewTicker(pollPeticiones)
	defer tick.Stop()
	for {
		hay, err := p.IngestaSolicitadaDesde(ctx, desde)
		if err != nil {
			log.Warn("no se han podido leer las peticiones de actualización", "error", err) // no impide seguir con el intervalo normal
		} else if hay {
			log.Info("actualización pedida: se empieza la vuelta sin esperar al intervalo")
			return nil
		}
		select {
		case <-fin.C:
			return nil
		case <-tick.C:
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}
