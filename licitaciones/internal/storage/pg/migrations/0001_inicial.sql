-- Estado operativo de la ingesta (ADR 0003): vistas de los expedientes, outbox de eventos y puntos de control.
-- Las vistas se pueden regenerar listando `processed`; el outbox solo guarda lo pendiente de publicar.

CREATE TABLE vistas (
    fuente             text        NOT NULL,
    id_origen          text        NOT NULL,
    version_entidad    integer     NOT NULL CHECK (version_entidad >= 1),
    hash_normalizado   text        NOT NULL,
    actualizado_origen timestamptz NOT NULL,
    banderas           smallint    NOT NULL DEFAULT 0,
    sha256_original    text        NOT NULL,
    clave_original     text        NOT NULL,
    visto_primera      timestamptz NOT NULL DEFAULT clock_timestamp(),
    visto_ultima       timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (fuente, id_origen)
);

CREATE TABLE outbox (
    seq             bigserial   PRIMARY KEY,           -- orden estricto de publicación
    id              text        NOT NULL UNIQUE,       -- determinista: (tipo, fuente, id, versión)
    tipo            text        NOT NULL,
    fuente          text        NOT NULL,
    id_origen       text        NOT NULL,
    version_entidad integer     NOT NULL,
    sha256_original text        NOT NULL,
    clave_original  text        NOT NULL,
    creado          timestamptz NOT NULL DEFAULT clock_timestamp(),
    intentos        integer     NOT NULL DEFAULT 0
);

CREATE TABLE puntos_control (
    fuente           text        PRIMARY KEY,
    ultima_ejecucion timestamptz NOT NULL,
    etag             text        NOT NULL DEFAULT '',
    last_modified    text        NOT NULL DEFAULT '',
    actualizado      timestamptz NOT NULL DEFAULT clock_timestamp()
);
