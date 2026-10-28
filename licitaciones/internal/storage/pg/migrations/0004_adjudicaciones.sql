-- Adjudicaciones por lote (modelo de lectura para el análisis de mercado y la competencia, `/awards` y `/competitors`). Se deriva SIEMPRE del
-- `documento` de cada expediente con la función `lic_proyectar_adjudicaciones` (una sola lógica): un disparador la llama cada vez que el
-- expediente cambia, y esta migración la llama para los expedientes que ya hay. Como todo el modelo de lectura, se puede regenerar (ADR 0003).

-- UUID v8 estable derivado de un nombre (el mismo cálculo que `uuid8` de internal/api: una prueba comprueba que coinciden).
CREATE FUNCTION lic_uuid8(nombre text) RETURNS uuid LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT encode(
        set_byte(set_byte(h, 6, (get_byte(h, 6) & 15) | 128), 8, (get_byte(h, 8) & 63) | 128), 'hex')::uuid
    FROM (SELECT substring(sha256(convert_to('licitaciones.101.cat|' || nombre, 'UTF8')) FROM 1 FOR 16) AS h) t
$$;

CREATE TABLE adjudicaciones (
    expediente_id        uuid    NOT NULL REFERENCES expedientes (id) ON DELETE CASCADE,
    n                    integer NOT NULL,                       -- posición del resultado dentro del expediente
    id                   uuid    GENERATED ALWAYS AS (lic_uuid8('adj:' || expediente_id::text || '|' || n::text)) STORED PRIMARY KEY,
    lote                 text    NOT NULL,
    resultado            text    NOT NULL CHECK (resultado IN ('adjudicado', 'desierto')),
    adjudicatario_nombre text    NOT NULL DEFAULT '',
    -- NIF del adjudicatario si es uno completo; si no (persona física con el NIF tapado, sin identificador) el nombre en minúsculas con prefijo.
    adjudicatario_clave  text    NOT NULL DEFAULT '',
    adjudicatario_nif    text    NOT NULL DEFAULT '',
    adjudicatario_id     uuid    GENERATED ALWAYS AS (CASE WHEN adjudicatario_clave <> '' THEN lic_uuid8('org:' || adjudicatario_clave) END) STORED,
    moneda               text    NOT NULL DEFAULT 'EUR',
    importe_sin_iva      numeric(18,4),
    importe_con_iva      numeric(18,4),
    presupuesto_sin_iva  numeric(18,4),                          -- presupuesto base del lote (o del expediente si no tiene lotes); NULL si no hay forma fiable
    oferta_mas_baja      numeric(18,4),
    oferta_mas_alta      numeric(18,4),
    ofertas_recibidas    integer,
    baja_anormal         boolean,
    fecha_adjudicacion   date,
    fecha_formalizacion  date,
    -- 1 − adjudicado/presupuesto base (sin IVA los dos); NULL si falta un dato, el presupuesto no es positivo o lo adjudicado lo supera (contratos plurianuales
    -- o de precios unitarios: en las muestras hay uno con el cuádruple, y ahí la «baja» no significa nada).
    baja                 numeric GENERATED ALWAYS AS (
        CASE WHEN presupuesto_sin_iva > 0 AND importe_sin_iva IS NOT NULL AND importe_sin_iva <= presupuesto_sin_iva THEN round(1 - importe_sin_iva / presupuesto_sin_iva, 6) END) STORED,
    UNIQUE (expediente_id, n)
);

CREATE INDEX adjudicaciones_fecha         ON adjudicaciones (fecha_adjudicacion DESC NULLS LAST, id);
CREATE INDEX adjudicaciones_adjudicatario ON adjudicaciones (adjudicatario_clave) WHERE adjudicatario_clave <> '';

CREATE FUNCTION lic_proyectar_adjudicaciones(p_id uuid) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM adjudicaciones WHERE expediente_id = p_id;
    INSERT INTO adjudicaciones (expediente_id, n, lote, resultado, adjudicatario_nombre, adjudicatario_clave, adjudicatario_nif, moneda,
        importe_sin_iva, importe_con_iva, presupuesto_sin_iva, oferta_mas_baja, oferta_mas_alta, ofertas_recibidas, baja_anormal,
        fecha_adjudicacion, fecha_formalizacion)
    SELECT e.id, r.n::integer, coalesce(nullif(r.x ->> 'lot_id', ''), '1'),
        CASE WHEN r.x ->> 'code' = '3' THEN 'desierto' ELSE 'adjudicado' END,
        coalesce(r.x ->> 'winner_name', ''),
        CASE WHEN r.x ->> 'code' = '3' THEN ''
             WHEN coalesce(r.x ->> 'winner_id', '') ~ '^[0-9A-Za-z]{9}$' THEN upper(r.x ->> 'winner_id')
             WHEN coalesce(r.x ->> 'winner_name', '') <> '' THEN 'n:' || lower(r.x ->> 'winner_name')
             ELSE '' END,
        CASE WHEN r.x ->> 'code' <> '3' AND coalesce(r.x ->> 'winner_id', '') ~ '^[0-9A-Za-z]{9}$' THEN upper(r.x ->> 'winner_id') ELSE '' END,
        coalesce(nullif(r.x #>> '{awarded_excl_vat,currency}', ''), e.moneda),
        CASE WHEN r.x #>> '{awarded_excl_vat,value}' ~ '^-?[0-9]{1,14}(\.[0-9]{1,4})?$' THEN (r.x #>> '{awarded_excl_vat,value}')::numeric END,
        CASE WHEN r.x #>> '{awarded_incl_vat,value}' ~ '^-?[0-9]{1,14}(\.[0-9]{1,4})?$' THEN (r.x #>> '{awarded_incl_vat,value}')::numeric END,
        -- Presupuesto base: el del lote; si el expediente no tiene lotes, el del expediente; si hay varios lotes y este no lo trae, ninguno.
        -- Con varios resultados para el mismo lote (varios adjudicatarios) tampoco hay forma fiable de repartirlo.
        CASE WHEN count(*) OVER (PARTITION BY coalesce(r.x ->> 'lot_id', '')) > 1 THEN NULL
             WHEN lote.x IS NOT NULL THEN
                 CASE WHEN lote.x #>> '{base_budget_excl_vat,value}' ~ '^-?[0-9]{1,14}(\.[0-9]{1,4})?$'
                      THEN (lote.x #>> '{base_budget_excl_vat,value}')::numeric END
             WHEN jsonb_array_length(coalesce(e.documento -> 'lots', '[]'::jsonb)) = 0 THEN e.presupuesto_sin_iva
             END,
        CASE WHEN r.x #>> '{lowest_offer,value}' ~ '^-?[0-9]{1,14}(\.[0-9]{1,4})?$' THEN (r.x #>> '{lowest_offer,value}')::numeric END,
        CASE WHEN r.x #>> '{highest_offer,value}' ~ '^-?[0-9]{1,14}(\.[0-9]{1,4})?$' THEN (r.x #>> '{highest_offer,value}')::numeric END,
        CASE WHEN r.x ->> 'tenders_received' ~ '^[0-9]{1,9}$' THEN (r.x ->> 'tenders_received')::integer END,
        (r.x ->> 'abnormally_low')::boolean,
        CASE WHEN r.x ->> 'award_date' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN (r.x ->> 'award_date')::date END,
        CASE WHEN r.x ->> 'formalized_on' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN (r.x ->> 'formalized_on')::date END
    FROM expedientes e
    CROSS JOIN LATERAL jsonb_array_elements(coalesce(e.documento -> 'results', '[]'::jsonb)) WITH ORDINALITY AS r (x, n)
    LEFT JOIN LATERAL (
        SELECT l.x FROM jsonb_array_elements(coalesce(e.documento -> 'lots', '[]'::jsonb)) AS l (x)
        WHERE l.x ->> 'id' = r.x ->> 'lot_id' LIMIT 1
    ) lote ON true
    WHERE e.id = p_id AND e.estado <> 'anulada' AND r.x ->> 'code' IN ('3', '8', '9');
END
$$;

CREATE FUNCTION lic_disparador_adjudicaciones() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM lic_proyectar_adjudicaciones(NEW.id);
    RETURN NULL;
END
$$;

CREATE TRIGGER expedientes_adjudicaciones AFTER INSERT OR UPDATE OF documento, estado ON expedientes
    FOR EACH ROW EXECUTE FUNCTION lic_disparador_adjudicaciones();

-- Los expedientes que ya estaban proyectados.
SELECT lic_proyectar_adjudicaciones(id) FROM expedientes;
