// Package bus publica los eventos del outbox en NATS JetStream (ADR 0002). Publish vuelve solo cuando el servidor ha confirmado el mensaje (PubAck),
// que es lo que necesita el relay para borrarlo del outbox; el identificador del evento viaja como Nats-Msg-Id, de modo que una republicación
// dentro de la ventana de duplicados (2 h) no genera un segundo mensaje.
package bus

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"

	"github.com/ionindustry/cerebro101/licitaciones/internal/ingest"
)

// Nombres y límites del flujo. Un flujo siempre con límites (NORMAS: nunca una cola sin vigilancia).
const (
	StreamName    = "LICITACIONES"
	SubjectFilter = "licitacion.>"
	MaxAge        = 14 * 24 * time.Hour
	MaxBytes      = 1 << 30
	MaxMsgSize    = 64 << 10
	DuplicateWin  = 2 * time.Hour
)

// Config es la conexión. Con usuario y clave se autentica; sin ellos va sin autenticación (solo en desarrollo, red interna).
type Config struct {
	URL      string
	User     string
	Password string
}

// Connect abre la conexión con reconexión automática y plazos acotados.
func Connect(c Config) (*nats.Conn, error) {
	if c.URL == "" {
		return nil, errors.New("bus: falta la dirección de NATS")
	}
	opts := []nats.Option{
		nats.Name("licitaciones"), nats.Timeout(5 * time.Second), nats.MaxReconnects(-1), nats.ReconnectWait(2 * time.Second),
	}
	if c.User != "" {
		opts = append(opts, nats.UserInfo(c.User, c.Password))
	}
	nc, err := nats.Connect(c.URL, opts...)
	if err != nil {
		return nil, fmt.Errorf("bus: conectar con NATS: %w", err)
	}
	return nc, nil
}

// Publisher publica eventos en el flujo.
type Publisher struct {
	js jetstream.JetStream
}

// NewPublisher crea el publicador sobre una conexión abierta.
func NewPublisher(nc *nats.Conn) (*Publisher, error) {
	js, err := jetstream.New(nc)
	if err != nil {
		return nil, fmt.Errorf("bus: JetStream: %w", err)
	}
	return &Publisher{js: js}, nil
}

// EnsureStream crea el flujo si no existe o lo actualiza a la configuración vigente (idempotente).
func (p *Publisher) EnsureStream(ctx context.Context) error {
	_, err := p.js.CreateOrUpdateStream(ctx, jetstream.StreamConfig{
		Name: StreamName, Subjects: []string{SubjectFilter}, Storage: jetstream.FileStorage, Retention: jetstream.LimitsPolicy,
		MaxAge: MaxAge, MaxBytes: MaxBytes, MaxMsgSize: MaxMsgSize, Duplicates: DuplicateWin, Discard: jetstream.DiscardOld,
		Replicas: 1, Description: "Eventos de licitaciones (ADR 0002)",
	})
	if err != nil {
		return fmt.Errorf("bus: crear o actualizar el flujo %s: %w", StreamName, err)
	}
	return nil
}

var token = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

// Subject es el asunto de un evento: licitacion.<tipo>.<fuente>, p. ej. licitacion.nueva.placsp-643.
func Subject(e ingest.Event) (string, error) {
	tipo := strings.TrimPrefix(e.Type, "licitacion.")
	if !token.MatchString(tipo) || !token.MatchString(e.Source) {
		return "", fmt.Errorf("bus: tipo (%q) o fuente (%q) no válidos para un asunto", e.Type, e.Source)
	}
	return "licitacion." + tipo + "." + e.Source, nil
}

type payload struct {
	ID        string `json:"id"`
	Type      string `json:"tipo"`
	Source    string `json:"fuente"`
	SourceID  string `json:"id_origen"`
	Version   int    `json:"version"`
	RawSHA256 string `json:"sha256_original"`
	RawKey    string `json:"clave_original"`
}

// Decode es la operación inversa de Publish: reconstruye el evento a partir del mensaje.
func Decode(data []byte) (ingest.Event, error) {
	var p payload
	if err := json.Unmarshal(data, &p); err != nil {
		return ingest.Event{}, fmt.Errorf("%w: mensaje no válido: %w", ErrPermanent, err)
	}
	if p.ID == "" || p.Type == "" || p.Source == "" || p.RawKey == "" || p.Version < 1 {
		return ingest.Event{}, fmt.Errorf("%w: al mensaje le faltan campos obligatorios", ErrPermanent)
	}
	return ingest.Event{ID: p.ID, Type: p.Type, Source: p.Source, SourceID: p.SourceID, Version: p.Version, RawSHA256: p.RawSHA256, RawKey: p.RawKey}, nil
}

// Publish publica el evento y vuelve cuando JetStream lo ha confirmado. Un duplicado dentro de la ventana cuenta como éxito.
func (p *Publisher) Publish(ctx context.Context, e ingest.Event) error {
	subj, err := Subject(e)
	if err != nil {
		return err
	}
	body, err := json.Marshal(payload{e.ID, e.Type, e.Source, e.SourceID, e.Version, e.RawSHA256, e.RawKey})
	if err != nil {
		return err
	}
	msg := &nats.Msg{Subject: subj, Data: body, Header: nats.Header{}}
	msg.Header.Set(nats.MsgIdHdr, e.ID)
	if _, err := p.js.PublishMsg(ctx, msg); err != nil {
		return fmt.Errorf("bus: publicar %s: %w", e.ID, err)
	}
	return nil
}
