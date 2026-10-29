package bus

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"sync"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

// ErrPermanent marca un fallo que repetir no arregla (un original corrupto, un XML que no se lee): el mensaje se da por terminado en vez
// de reintentarlo, y queda registrado. Cualquier otro error se reintenta con espera creciente.
var ErrPermanent = errors.New("fallo permanente")

// Handler procesa un evento. Tiene que ser idempotente: JetStream entrega «al menos una vez».
type Handler func(ctx context.Context, e ingest.Event) error

// ConsumerOptions configura un consumidor duradero.
type ConsumerOptions struct {
	Durable       string        // nombre del consumidor; su avance se conserva entre reinicios
	AckWait       time.Duration // tiempo para confirmar antes de reentregar; 0 = 2 min
	MaxDeliver    int           // intentos antes de descartar; 0 = 8
	MaxAckPending int           // mensajes en vuelo; 0 = 32
	Workers       int           // eventos que se procesan a la vez; 0 o 1 = uno detrás de otro (como siempre). Nunca más que MaxAckPending
	Stream        string        // flujo del que se consume; vacío = el de la sindicación en vivo (StreamName)
	Filter        string        // asuntos del flujo; vacío = el del flujo en vivo (SubjectFilter) o, con StreamHistorico, el suyo
	Log           *slog.Logger
}

// Consume procesa los eventos del flujo con un consumidor duradero hasta que se cancela ctx (devuelve entonces nil). Confirma (Ack) cuando
// el manejador acaba bien; ante un error permanente da el mensaje por terminado (Term) y lo registra; ante cualquier otro lo reintenta
// con espera creciente hasta MaxDeliver intentos, y después lo descarta con un registro de error.
func Consume(ctx context.Context, nc *nats.Conn, h Handler, o ConsumerOptions) error {
	if o.Durable == "" {
		return errors.New("bus: falta el nombre del consumidor")
	}
	if o.AckWait <= 0 {
		o.AckWait = 2 * time.Minute
	}
	if o.MaxDeliver <= 0 {
		o.MaxDeliver = 8
	}
	if o.MaxAckPending <= 0 {
		o.MaxAckPending = 32
	}
	if o.Log == nil {
		o.Log = slog.New(slog.DiscardHandler)
	}
	if o.Stream == "" {
		o.Stream = StreamName
	}
	if o.Filter == "" {
		o.Filter = SubjectFilter
		if o.Stream == StreamHistorico {
			o.Filter = SubjectHistoricoFilter
		}
	}
	workers := min(max(o.Workers, 1), o.MaxAckPending)
	sem := make(chan struct{}, workers)
	js, err := jetstream.New(nc)
	if err != nil {
		return fmt.Errorf("bus: JetStream: %w", err)
	}
	cons, err := js.CreateOrUpdateConsumer(ctx, o.Stream, jetstream.ConsumerConfig{
		Durable: o.Durable, AckPolicy: jetstream.AckExplicitPolicy, AckWait: o.AckWait, MaxDeliver: o.MaxDeliver,
		MaxAckPending: o.MaxAckPending, FilterSubject: o.Filter, DeliverPolicy: jetstream.DeliverAllPolicy,
		Description: "Proyector de lectura",
	})
	if err != nil {
		return fmt.Errorf("bus: crear el consumidor %s: %w", o.Durable, err)
	}
	var wg sync.WaitGroup
	cc, err := cons.Consume(func(m jetstream.Msg) {
		if workers == 1 {
			handle(ctx, m, h, o)
			return
		}
		// Varios a la vez: este callback espera a que haya un hueco (así el consumidor no se adelanta a lo que se puede procesar) y cada evento va por su cuenta.
		sem <- struct{}{}
		wg.Add(1)
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			handle(ctx, m, h, o)
		}()
	})
	if err != nil {
		return fmt.Errorf("bus: consumir: %w", err)
	}
	<-ctx.Done()
	cc.Stop()
	wg.Wait() // los que están en marcha terminan antes de salir: no se cierra la conexión con eventos a medias
	return nil
}

func handle(ctx context.Context, m jetstream.Msg, h Handler, o ConsumerOptions) {
	meta, _ := m.Metadata()
	attempt := 1
	if meta != nil && meta.NumDelivered <= math.MaxInt32 {
		attempt = int(meta.NumDelivered)
	}
	ev, err := Decode(m.Data())
	if err == nil {
		err = h(ctx, ev)
	}
	switch {
	case err == nil:
		_ = m.Ack()
	case ctx.Err() != nil:
		_ = m.NakWithDelay(time.Second) // parada: otro intento cuando vuelva a arrancar
	case errors.Is(err, ErrPermanent):
		o.Log.Error("evento descartado: fallo permanente", "asunto", m.Subject(), "error", err)
		_ = m.Term()
	case attempt >= o.MaxDeliver:
		o.Log.Error("evento descartado tras agotar los intentos", "asunto", m.Subject(), "intentos", attempt, "error", err)
		_ = m.Term()
	default:
		delay := min(time.Duration(1<<min(attempt, 6))*time.Second, time.Minute)
		o.Log.Warn("no se pudo procesar el evento, se reintenta", "asunto", m.Subject(), "intento", attempt, "reintento_en", delay.String(), "error", err)
		_ = m.NakWithDelay(delay)
	}
}
