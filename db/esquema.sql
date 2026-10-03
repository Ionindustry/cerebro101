-- Esquema del Cerebro (PostgreSQL 16 + pgvector). Se carga al crear el contenedor.
-- Las tablas del checkpointer de LangGraph las crea la propia API al arrancar.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Base de conocimiento (embeddings BGE-M3, 1024 dimensiones)
CREATE TABLE IF NOT EXISTS documentos (
  id            bigserial PRIMARY KEY,
  titulo        text NOT NULL,
  fuente        text NOT NULL,
  departamento  text NOT NULL DEFAULT 'comun',
  sensibilidad  text NOT NULL DEFAULT 'media' CHECK (sensibilidad IN ('baja','media','alta')),
  texto         text NOT NULL,
  embedding     vector(1024) NOT NULL,
  metadatos     jsonb NOT NULL DEFAULT '{}',
  creado        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS documentos_embedding_idx ON documentos USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS documentos_dep_idx ON documentos (departamento, sensibilidad);

-- Bandeja de aprobaciones
CREATE TABLE IF NOT EXISTS aprobaciones (
  id             uuid PRIMARY KEY,
  hilo           text NOT NULL,
  agente         text NOT NULL,
  departamento   text NOT NULL,
  accion         text NOT NULL,
  nivel          text NOT NULL CHECK (nivel IN ('simple','doble')),
  aprobadores    text[] NOT NULL,
  voz_permitida  boolean NOT NULL DEFAULT false,
  datos          jsonb NOT NULL,
  decisiones     jsonb NOT NULL DEFAULT '[]',
  estado         text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','aprobada','rechazada')),
  creado         timestamptz NOT NULL DEFAULT now(),
  actualizado    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS aprobaciones_estado_idx ON aprobaciones (estado, departamento);

-- Registro de acciones ejecutadas (evidencia para ENS / ISO 27001)
CREATE TABLE IF NOT EXISTS registro_acciones (
  id           bigserial PRIMARY KEY,
  hilo         text,
  agente       text NOT NULL,
  herramienta  text NOT NULL,
  operacion    text NOT NULL,
  aprobacion   uuid REFERENCES aprobaciones(id),
  resultado    text NOT NULL,
  creado       timestamptz NOT NULL DEFAULT now()
);

-- Red de instaladores
CREATE TABLE IF NOT EXISTS instaladores (
  id              bigserial PRIMARY KEY,
  nombre          text NOT NULL,
  cif             text UNIQUE,
  zonas           text[] NOT NULL DEFAULT '{}',
  especialidades  text[] NOT NULL DEFAULT '{}',
  habilitaciones  jsonb NOT NULL DEFAULT '{}',
  tarifas_hora    jsonb NOT NULL DEFAULT '{}',   -- {tecnico_primera: 24, lampista_oficial: 21, ...}
  acuerdo_marco   jsonb,                         -- fecha, vigencia, documento
  estado          text NOT NULL DEFAULT 'candidato' CHECK (estado IN ('candidato','negociando','con_acuerdo','baja')),
  creado          timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS trabajos_instaladores (
  id                bigserial PRIMARY KEY,
  instalador_id     bigint REFERENCES instaladores(id),
  proyecto          text NOT NULL,
  horas_estimadas   numeric NOT NULL,
  horas_reales      numeric,
  incidencias       int NOT NULL DEFAULT 0,
  valoracion        numeric CHECK (valoracion BETWEEN 0 AND 5),
  terminado         date
);

-- Oportunidades detectadas (Radar, Analista de Noticias, Detector de Intención)
CREATE TABLE IF NOT EXISTS oportunidades (
  id           bigserial PRIMARY KEY,
  origen       text NOT NULL,
  area         text,                        -- una de las 10 áreas de servicio
  titulo       text NOT NULL,
  resumen      text NOT NULL,
  fuentes      jsonb NOT NULL DEFAULT '[]',
  puntuacion   numeric,
  urgencia     text,
  estado       text NOT NULL DEFAULT 'nueva' CHECK (estado IN ('nueva','aprobada','descartada','lanzada')),
  creado       timestamptz NOT NULL DEFAULT now()
);

-- Licitaciones
CREATE TABLE IF NOT EXISTS licitaciones (
  id             bigserial PRIMARY KEY,
  expediente     text UNIQUE NOT NULL,
  organismo      text,
  titulo         text NOT NULL,
  cpv            text[] NOT NULL DEFAULT '{}',
  importe        numeric,
  fecha_limite   timestamptz,
  enlace         text,
  viabilidad     jsonb,
  decision       text CHECK (decision IN ('ir','no_ir')),
  estado         text NOT NULL DEFAULT 'detectada',
  creado         timestamptz NOT NULL DEFAULT now()
);
