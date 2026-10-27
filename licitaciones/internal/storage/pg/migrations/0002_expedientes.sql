-- Modelo de lectura de los expedientes (lo que consultan la API y los agentes). Se regenera por completo repitiendo los eventos o releyendo
-- `raw` (ADR 0003): nunca es la fuente de verdad. Una fila por expediente y fuente, con el registro normalizado completo en `documento`.
-- Búsqueda de texto en castellano y catalán con PostgreSQL; OpenSearch y el grafo llegarán después (ADR 0009).

CREATE TABLE expedientes (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    fuente             text        NOT NULL,
    id_origen          text        NOT NULL,
    id_numerico        text        NOT NULL DEFAULT '',
    version_entidad    integer     NOT NULL CHECK (version_entidad >= 1),
    actualizada        timestamptz NOT NULL,         -- atom:updated de la versión proyectada
    expediente         text        NOT NULL DEFAULT '',
    estado_origen      text        NOT NULL DEFAULT '',
    estado             text        NOT NULL,
    titulo             text        NOT NULL DEFAULT '',
    comprador_nombre   text        NOT NULL DEFAULT '',
    comprador_nif      text        NOT NULL DEFAULT '',
    comprador_dir3     text        NOT NULL DEFAULT '',
    procedimiento      text        NOT NULL DEFAULT '',
    procedimiento_origen text      NOT NULL DEFAULT '',
    tipo_contrato      text        NOT NULL DEFAULT '',
    cpv                text[]      NOT NULL DEFAULT '{}',
    nuts               text[]      NOT NULL DEFAULT '{}',
    valor_estimado     numeric(18,4),
    presupuesto_sin_iva numeric(18,4),
    presupuesto_con_iva numeric(18,4),
    moneda             text        NOT NULL DEFAULT 'EUR',
    plazo_presentacion timestamptz,
    enlace             text        NOT NULL DEFAULT '',
    sha256_original    text        NOT NULL,
    clave_original     text        NOT NULL,
    documento          jsonb       NOT NULL,
    busqueda           tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('spanish', coalesce(titulo, '')), 'A') ||
        setweight(to_tsvector('catalan', coalesce(titulo, '')), 'A') ||
        setweight(to_tsvector('spanish', coalesce(comprador_nombre, '') || ' ' || coalesce(expediente, '')), 'B')
    ) STORED,
    creada             timestamptz NOT NULL DEFAULT clock_timestamp(),
    proyectada         timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (fuente, id_origen)
);

CREATE INDEX expedientes_busqueda  ON expedientes USING gin (busqueda);
CREATE INDEX expedientes_cpv       ON expedientes USING gin (cpv);
CREATE INDEX expedientes_nuts      ON expedientes USING gin (nuts);
CREATE INDEX expedientes_actualizada ON expedientes (actualizada DESC, id);
CREATE INDEX expedientes_plazo     ON expedientes (plazo_presentacion) WHERE plazo_presentacion IS NOT NULL;
CREATE INDEX expedientes_estado    ON expedientes (estado);
CREATE INDEX expedientes_comprador ON expedientes (comprador_nif) WHERE comprador_nif <> '';
