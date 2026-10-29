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

-- Cuadernos de investigación (como NotebookLM, en local): fuentes que reúne un agente y sobre las que se pregunta con citas
CREATE TABLE IF NOT EXISTS cuadernos (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  titulo        text NOT NULL,
  descripcion   text NOT NULL DEFAULT '',
  departamento  text NOT NULL,
  creado        timestamptz NOT NULL DEFAULT now(),
  actualizado   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS cuadernos_titulo_idx ON cuadernos (departamento, lower(titulo));

CREATE TABLE IF NOT EXISTS cuaderno_fuentes (
  id            bigserial PRIMARY KEY,
  cuaderno      uuid NOT NULL REFERENCES cuadernos(id) ON DELETE CASCADE,
  tipo          text NOT NULL CHECK (tipo IN ('web','nota')),
  titulo        text NOT NULL,
  url           text NOT NULL DEFAULT '',
  texto         text NOT NULL,
  creado        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cuaderno_fuentes_cuaderno_idx ON cuaderno_fuentes (cuaderno);

CREATE TABLE IF NOT EXISTS cuaderno_trozos (
  id            bigserial PRIMARY KEY,
  fuente        bigint NOT NULL REFERENCES cuaderno_fuentes(id) ON DELETE CASCADE,
  cuaderno      uuid NOT NULL REFERENCES cuadernos(id) ON DELETE CASCADE,
  orden         integer NOT NULL,
  texto         text NOT NULL,
  embedding     vector(1024) NOT NULL
);
CREATE INDEX IF NOT EXISTS cuaderno_trozos_cuaderno_idx ON cuaderno_trozos (cuaderno);

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

-- Objetivos permanentes: una firma de Dirección que cubre varias peticiones (con caducidad y tope de acciones)
CREATE TABLE IF NOT EXISTS objetivos (
  id             uuid PRIMARY KEY,
  titulo         text NOT NULL,
  departamentos  text[] NOT NULL CHECK (cardinality(departamentos) > 0),
  agentes        text[] NOT NULL DEFAULT '{}',
  operaciones    text[] NOT NULL CHECK (cardinality(operaciones) > 0),
  max_acciones   integer NOT NULL CHECK (max_acciones BETWEEN 1 AND 500),
  usadas         integer NOT NULL DEFAULT 0,
  caduca         timestamptz NOT NULL,
  estado         text NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo','revocado')),
  creado_por     text NOT NULL,
  creado         timestamptz NOT NULL DEFAULT now(),
  revocado_por   text,
  revocado       timestamptz
);

-- Qué está haciendo cada agente ahora (la pestaña «Oficina» del panel). Es información de estado, no evidencia: se sobrescribe.
CREATE TABLE IF NOT EXISTS actividad_agentes (
  agente        text PRIMARY KEY,
  estado        text NOT NULL CHECK (estado IN ('trabajando','reposo')),
  detalle       text,
  hilo          text,
  actualizado   timestamptz NOT NULL DEFAULT now(),
  ultima        text,
  ultima_fecha  timestamptz
);

-- Pasos recientes de cada agente (detalle de la pestaña «Oficina»). Solo qué herramienta usa, nunca el contenido de lo que trabaja. Se recorta solo.
CREATE TABLE IF NOT EXISTS actividad_eventos (
  id       bigserial PRIMARY KEY,
  agente   text NOT NULL,
  texto    text NOT NULL,
  hilo     text,
  creado   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS actividad_eventos_agente_idx ON actividad_eventos (agente, id DESC);

-- Contadores diarios por agente para los KPI de su panel (peticiones, usos de herramientas, errores, propuestas). Solo cifras, nunca contenido.
CREATE TABLE IF NOT EXISTS kpi_uso (
  agente  text NOT NULL,
  dia     date NOT NULL,
  clave   text NOT NULL,
  n       integer NOT NULL DEFAULT 0,
  PRIMARY KEY (agente, dia, clave)
);

-- Qué modelos externos (Claude, ChatGPT) están conectados: lo cambia Dirección desde el panel. Sin fila = desconectado.
CREATE TABLE IF NOT EXISTS modelos_externos (
  proveedor    text PRIMARY KEY,
  activo       boolean NOT NULL DEFAULT false,
  cambiado_por text,
  cambiado     timestamptz NOT NULL DEFAULT now()
);

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

-- Protección de las evidencias (ISO 27001): el registro de acciones es de solo anexado y las aprobaciones
-- no se borran ni pierden decisiones. Quien sea propietario o superusuario de la base de datos podría quitar
-- estos disparadores: la aplicación debería conectarse con un rol sin ese permiso (ver docs/SEGURIDAD.md).
CREATE OR REPLACE FUNCTION evidencia_solo_anexar() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  RAISE EXCEPTION '% no permitido en %: es un registro de evidencias de solo anexado', TG_OP, TG_TABLE_NAME
    USING ERRCODE = 'integrity_constraint_violation';
END $f$;

DROP TRIGGER IF EXISTS registro_acciones_solo_anexar ON registro_acciones;
CREATE TRIGGER registro_acciones_solo_anexar BEFORE UPDATE OR DELETE ON registro_acciones
  FOR EACH ROW EXECUTE FUNCTION evidencia_solo_anexar();
DROP TRIGGER IF EXISTS registro_acciones_sin_vaciar ON registro_acciones;
CREATE TRIGGER registro_acciones_sin_vaciar BEFORE TRUNCATE ON registro_acciones
  FOR EACH STATEMENT EXECUTE FUNCTION evidencia_solo_anexar();

CREATE OR REPLACE FUNCTION aprobaciones_conservar_historial() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Las aprobaciones no se borran' USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF jsonb_array_length(NEW.decisiones) < jsonb_array_length(OLD.decisiones) THEN
    RAISE EXCEPTION 'No se pueden quitar decisiones de una aprobación' USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF (OLD.estado <> 'pendiente' AND NEW.estado <> OLD.estado) THEN
    RAISE EXCEPTION 'Una aprobación ya resuelta no puede cambiar de estado' USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NEW;
END $f$;

DROP TRIGGER IF EXISTS aprobaciones_historial ON aprobaciones;
CREATE TRIGGER aprobaciones_historial BEFORE UPDATE OR DELETE ON aprobaciones
  FOR EACH ROW EXECUTE FUNCTION aprobaciones_conservar_historial();

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

-- Embudo propio de licitaciones (ADR 0007 §3 y §4; api/cerebro/licitaciones/embudo.py). La tabla `licitaciones` pasa a ser el embudo comercial y
-- apunta al expediente del motor (motor_id). Idempotente: se aplica en cada arranque. Estados: detectada → en_estudio → presentada → ganada | perdida;
-- «descartada» es el no ir. Las fechas dicen cuándo se pasó de un estado a otro (para los indicadores): decidida_en = salió de «detectada».
ALTER TABLE licitaciones ADD COLUMN IF NOT EXISTS motor_id        uuid;
ALTER TABLE licitaciones ADD COLUMN IF NOT EXISTS motor_version   int;
ALTER TABLE licitaciones ADD COLUMN IF NOT EXISTS encaje          numeric;
ALTER TABLE licitaciones ADD COLUMN IF NOT EXISTS motivo_perdida  text;
ALTER TABLE licitaciones ADD COLUMN IF NOT EXISTS actualizado     timestamptz NOT NULL DEFAULT now();
ALTER TABLE licitaciones ADD COLUMN IF NOT EXISTS decidida_en     timestamptz;
ALTER TABLE licitaciones ADD COLUMN IF NOT EXISTS presentada_en   timestamptz;
ALTER TABLE licitaciones ADD COLUMN IF NOT EXISTS resuelta_en     timestamptz;
-- Estado del expediente en el motor (abierta, adjudicada, anulada…); lo actualiza el consumidor de eventos (cerebro/licitaciones/consumidor.py).
ALTER TABLE licitaciones ADD COLUMN IF NOT EXISTS estado_motor    text;
-- Petición de un informe de viabilidad por una persona («Pedir informe de viabilidad»): {"estado": "en_curso"|"error", "por": usuario, "en": hora, "error": texto}.
-- Evita pedirlo dos veces a la vez; se borra al guardarse el informe.
ALTER TABLE licitaciones ADD COLUMN IF NOT EXISTS viabilidad_peticion jsonb;
-- Plazo que se puso en el calendario de la empresa (botón «Añadir el plazo al calendario»); NULL = no está. El evento se identifica por un UID fijo sacado del motor_id.
ALTER TABLE licitaciones ADD COLUMN IF NOT EXISTS calendario_plazo timestamptz;
-- El código de expediente no es único entre organismos: la identidad de una fila es el expediente del motor.
ALTER TABLE licitaciones DROP CONSTRAINT IF EXISTS licitaciones_expediente_key;
CREATE UNIQUE INDEX IF NOT EXISTS licitaciones_motor_id ON licitaciones (motor_id);
CREATE INDEX IF NOT EXISTS licitaciones_estado ON licitaciones (estado, actualizado DESC);
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'licitaciones_estado_valido' AND conrelid = 'licitaciones'::regclass) THEN
    -- NOT VALID: no revisa lo que ya hubiera (la tabla no tenía uso); sí lo que se escriba a partir de ahora.
    ALTER TABLE licitaciones ADD CONSTRAINT licitaciones_estado_valido
      CHECK (estado IN ('detectada','en_estudio','presentada','ganada','perdida','descartada')) NOT VALID;
  END IF;
END $$;

-- Alertas de licitaciones: búsquedas guardadas con aviso (api/cerebro/licitaciones/alertas.py). El filtro es el mismo que el de GET /tenders del motor; el
-- consumidor de eventos (cerebro/licitaciones/consumidor.py) pregunta al motor si el expediente de cada evento lo cumple y, si sí, deja un aviso. Personal: solo
-- su dueño; de departamento: la ven sus miembros (y Dirección) y la cambian el responsable del departamento y Dirección.
CREATE TABLE IF NOT EXISTS licitaciones_alertas (
  id              bigserial PRIMARY KEY,
  nombre          text NOT NULL,
  propietario     text NOT NULL,                       -- quien la creó (id del usuario)
  ambito          text NOT NULL CHECK (ambito IN ('personal','departamento')),
  departamento    text,                                -- obligatorio si ambito = departamento
  filtro          jsonb NOT NULL,
  eventos         text[] NOT NULL,                     -- licitacion.nueva, .modificada, .adjudicada, .formalizada, .anulada
  canal           text NOT NULL DEFAULT 'panel',       -- panel: solo el aviso en el panel · resumen_diario: además, en el resumen de las 16:00 (solo alertas de departamento); correo: además, un correo a `correo_destino` (solo @101.cat; sale del buzón «notificaciones»)
  activa          boolean NOT NULL DEFAULT true,
  creada          timestamptz NOT NULL DEFAULT now(),
  cambiada        timestamptz NOT NULL DEFAULT now(),
  ultima_entrega  timestamptz,
  CHECK ((ambito = 'departamento') = (departamento IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS licitaciones_alertas_activas ON licitaciones_alertas (activa) WHERE activa;
-- Las reglas del canal van con nombre y se reaplican en cada arranque (así una base creada antes, que solo admitía «panel», pasa a admitir «resumen_diario»).
ALTER TABLE licitaciones_alertas DROP CONSTRAINT IF EXISTS licitaciones_alertas_canal_check;
ALTER TABLE licitaciones_alertas ADD COLUMN IF NOT EXISTS correo_destino text;
ALTER TABLE licitaciones_alertas ADD CONSTRAINT licitaciones_alertas_canal_check CHECK (canal IN ('panel','resumen_diario','correo'));
-- Alertas de competencia: avisan cuando una licitación (que cumple el filtro) se adjudica a un competidor de la lista (NIF) o, con la lista vacía, a cualquiera.
-- Solo del evento «adjudicada»; una alerta de licitaciones normal no lleva competidores.
ALTER TABLE licitaciones_alertas ADD COLUMN IF NOT EXISTS tipo text NOT NULL DEFAULT 'licitacion';
ALTER TABLE licitaciones_alertas ADD COLUMN IF NOT EXISTS competidores text[] NOT NULL DEFAULT '{}';
ALTER TABLE licitaciones_alertas DROP CONSTRAINT IF EXISTS licitaciones_alertas_tipo_check;
ALTER TABLE licitaciones_alertas ADD CONSTRAINT licitaciones_alertas_tipo_check CHECK (tipo IN ('licitacion','competencia'));
ALTER TABLE licitaciones_alertas DROP CONSTRAINT IF EXISTS licitaciones_alertas_competencia;
ALTER TABLE licitaciones_alertas ADD CONSTRAINT licitaciones_alertas_competencia CHECK (
  (tipo = 'competencia' AND eventos = ARRAY['licitacion.adjudicada']::text[]) OR (tipo = 'licitacion' AND cardinality(competidores) = 0));
-- «Solo empresas nuevas»: la alerta de competencia (sin lista de competidores) avisa solo si el adjudicatario no había ganado antes nada en ese mercado.
ALTER TABLE licitaciones_alertas ADD COLUMN IF NOT EXISTS solo_nuevos boolean NOT NULL DEFAULT false;
ALTER TABLE licitaciones_alertas DROP CONSTRAINT IF EXISTS licitaciones_alertas_solo_nuevos;
ALTER TABLE licitaciones_alertas ADD CONSTRAINT licitaciones_alertas_solo_nuevos CHECK (NOT solo_nuevos OR (tipo = 'competencia' AND cardinality(competidores) = 0));
-- Con canal «correo» hay dirección de destino, y solo entonces.
ALTER TABLE licitaciones_alertas DROP CONSTRAINT IF EXISTS licitaciones_alertas_correo_destino;
ALTER TABLE licitaciones_alertas ADD CONSTRAINT licitaciones_alertas_correo_destino CHECK ((canal = 'correo') = (correo_destino IS NOT NULL));
ALTER TABLE licitaciones_alertas DROP CONSTRAINT IF EXISTS licitaciones_alertas_resumen_solo_departamento;
-- El resumen lo ven Dirección y Licitaciones: una alerta PERSONAL nunca puede aparecer en él.
ALTER TABLE licitaciones_alertas ADD CONSTRAINT licitaciones_alertas_resumen_solo_departamento CHECK (canal <> 'resumen_diario' OR ambito = 'departamento');

-- Avisos: una fila por alerta y evento (UNIQUE: una alerta no avisa dos veces del mismo evento, ADR 0003). Guardan los datos del expediente tal como eran al avisar.
CREATE TABLE IF NOT EXISTS licitaciones_avisos (
  id           bigserial PRIMARY KEY,
  alerta_id    bigint NOT NULL REFERENCES licitaciones_alertas (id) ON DELETE CASCADE,
  evento_id    text NOT NULL,
  tipo         text NOT NULL,
  motor_id     uuid NOT NULL,
  titulo       text NOT NULL,
  organismo    text,
  encaje       numeric,
  importe      numeric,
  fecha_limite timestamptz,
  enlace       text,
  estado_motor text,
  leido        boolean NOT NULL DEFAULT false,
  creado       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (alerta_id, evento_id)
);
-- Envío por correo (canal «correo»): NULL = pendiente de enviar; se reintenta hasta agotar los intentos (cerebro/licitaciones/avisos_correo.py).
ALTER TABLE licitaciones_avisos ADD COLUMN IF NOT EXISTS detalle jsonb;        -- alertas de competencia: quién ha ganado ({"ganadores": [...]})
ALTER TABLE licitaciones_avisos ADD COLUMN IF NOT EXISTS correo_enviado timestamptz;
ALTER TABLE licitaciones_avisos ADD COLUMN IF NOT EXISTS correo_intentos integer NOT NULL DEFAULT 0;
ALTER TABLE licitaciones_avisos ADD COLUMN IF NOT EXISTS correo_error text;
CREATE INDEX IF NOT EXISTS licitaciones_avisos_correo_pendiente ON licitaciones_avisos (alerta_id, creado) WHERE correo_enviado IS NULL;
CREATE INDEX IF NOT EXISTS licitaciones_avisos_no_leidos ON licitaciones_avisos (creado DESC) WHERE NOT leido;

-- Resumen diario de licitaciones (a las 16:00, para Dirección; ver api/cerebro/licitaciones/resumen.py). El contenido es un documento completo:
-- lo que se vio ese día no cambia aunque después cambien las licitaciones.
CREATE TABLE IF NOT EXISTS licitaciones_resumenes (
  id         bigserial PRIMARY KEY,
  fecha      date NOT NULL,                 -- día (hora local) al que pertenece
  origen     text NOT NULL CHECK (origen IN ('programada','manual')),
  desde      timestamptz NOT NULL,
  hasta      timestamptz NOT NULL,
  estado     text NOT NULL CHECK (estado IN ('ok','sin_datos')),
  contenido  jsonb NOT NULL,
  generado   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS licitaciones_resumenes_programado ON licitaciones_resumenes (fecha) WHERE origen = 'programada';
CREATE INDEX IF NOT EXISTS licitaciones_resumenes_fecha ON licitaciones_resumenes (fecha DESC, generado DESC);

-- Pliegos y otros documentos de una licitación (api/cerebro/licitaciones/pliegos.py, docs/SEGURIDAD.md §3.10): se bajan POR ID (nunca por URL), pasan por cuarentena y antivirus
-- y solo se ofrecen si están «limpio» (o «con_macros»: solo se leerá el texto). Aquí solo van los metadatos; los ficheros están en /datos/licitaciones/pliegos/<licitación>/.
CREATE TABLE IF NOT EXISTS pliegos_documentos (
  id        bigserial PRIMARY KEY,
  motor_id  uuid NOT NULL,                              -- la licitación en el motor
  n         integer NOT NULL,                           -- número del documento en la ficha (desde 1) cuando se pidió
  nombre    text NOT NULL,
  formato   text NOT NULL,                              -- pdf, docx, xlsx, odt, ods, zip (según el contenido real)
  bytes     bigint NOT NULL,
  sha256    text NOT NULL,
  estado    text NOT NULL DEFAULT 'cuarentena',
  motivo    text NOT NULL DEFAULT '',
  creado    timestamptz NOT NULL DEFAULT now(),
  analizado timestamptz,
  UNIQUE (motor_id, sha256)
);
ALTER TABLE pliegos_documentos DROP CONSTRAINT IF EXISTS pliegos_documentos_estado_check;
ALTER TABLE pliegos_documentos ADD CONSTRAINT pliegos_documentos_estado_check CHECK (estado IN ('cuarentena','limpio','con_macros','infectado','no_analizable','error'));
CREATE INDEX IF NOT EXISTS pliegos_documentos_creado ON pliegos_documentos (creado);

-- Texto de los pliegos (api/cerebro/licitaciones/extractor.py): una fila por página (o bloque u hoja, según el formato) de los documentos limpios, con búsqueda de texto en castellano.
ALTER TABLE pliegos_documentos ADD COLUMN IF NOT EXISTS unidad text;                  -- página | bloque | hoja
ALTER TABLE pliegos_documentos ADD COLUMN IF NOT EXISTS paginas integer;              -- cuántas se han extraído; NULL = aún no se ha leído
ALTER TABLE pliegos_documentos ADD COLUMN IF NOT EXISTS aviso text NOT NULL DEFAULT '';   -- lo que la extracción tiene que decir (escaneo, páginas de más…)
CREATE TABLE IF NOT EXISTS pliegos_paginas (
  documento_id bigint NOT NULL REFERENCES pliegos_documentos (id) ON DELETE CASCADE,
  pagina       integer NOT NULL,
  texto        text NOT NULL,
  tsv          tsvector GENERATED ALWAYS AS (to_tsvector('spanish', texto)) STORED,
  PRIMARY KEY (documento_id, pagina)
);
CREATE INDEX IF NOT EXISTS pliegos_paginas_tsv ON pliegos_paginas USING gin (tsv);

-- Requisitos que el Analista de Pliegos extrae de un documento. Cada uno lleva su CITA LITERAL y la página, y el sistema comprueba que esa frase está de verdad en esa página antes de
-- guardarlo. Nacen en «borrador»: una persona los confirma o los rechaza (nunca el agente).
CREATE TABLE IF NOT EXISTS pliegos_requisitos (
  id           bigserial PRIMARY KEY,
  documento_id bigint NOT NULL REFERENCES pliegos_documentos (id) ON DELETE CASCADE,
  pagina       integer NOT NULL,
  tipo         text NOT NULL,
  resumen      text NOT NULL,                  -- lo que dice el requisito, con las palabras del agente
  cita         text NOT NULL,                  -- la frase tal cual del documento
  valor        text NOT NULL DEFAULT '',       -- puntos, importe, plazo… si procede
  estado       text NOT NULL DEFAULT 'borrador',
  creado       timestamptz NOT NULL DEFAULT now(),
  por          text NOT NULL DEFAULT '',       -- el agente que lo anotó
  revisado_por text,
  revisado     timestamptz,
  CHECK (estado IN ('borrador', 'confirmado', 'rechazado'))
);
CREATE UNIQUE INDEX IF NOT EXISTS pliegos_requisitos_unico ON pliegos_requisitos (documento_id, pagina, md5(cita));

-- Matriz de cumplimiento: de cada requisito CONFIRMADO, una persona anota si 101.cat lo cumple (y por qué si es parcial o no). Nunca el agente.
ALTER TABLE pliegos_requisitos ADD COLUMN IF NOT EXISTS cumplimiento      text NOT NULL DEFAULT 'pendiente';
ALTER TABLE pliegos_requisitos ADD COLUMN IF NOT EXISTS cumplimiento_nota text NOT NULL DEFAULT '';
ALTER TABLE pliegos_requisitos ADD COLUMN IF NOT EXISTS cumplimiento_por  text;
ALTER TABLE pliegos_requisitos ADD COLUMN IF NOT EXISTS cumplimiento_en   timestamptz;
ALTER TABLE pliegos_requisitos DROP CONSTRAINT IF EXISTS pliegos_requisitos_cumplimiento;
ALTER TABLE pliegos_requisitos ADD CONSTRAINT pliegos_requisitos_cumplimiento CHECK (cumplimiento IN ('pendiente', 'cumple', 'parcial', 'no_cumple', 'no_aplica'));
