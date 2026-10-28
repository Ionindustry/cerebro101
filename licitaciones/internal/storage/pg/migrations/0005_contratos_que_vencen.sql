-- Contratos que vencen: cuándo termina cada contrato adjudicado (y cuándo podría terminar con las prórrogas), para saber cuándo vuelve a salir el concurso.
-- Todo se calcula en la misma función SQL que proyecta las adjudicaciones (una sola lógica) a partir del `documento` del expediente; los expedientes que ya hay se
-- recalculan al final. La duración sale del expediente (o del lote); las prórrogas solo se calculan cuando el pliego las dice con claridad (parser: «tres (3) prórrogas
-- de un (1) año»); en los expedientes ingeridos antes de esta versión el texto de las prórrogas no está hasta que el expediente se vuelva a proyectar.

ALTER TABLE adjudicaciones
    ADD COLUMN fecha_inicio        date,
    ADD COLUMN fecha_fin           date,
    ADD COLUMN fecha_fin_prorrogas date,
    ADD COLUMN prorrogas_posibles  boolean,          -- true/false si el texto del pliego lo dice con claridad; NULL si no se sabe
    ADD COLUMN prorrogas_texto     text,             -- texto de origen (dato de un tercero, acotado)
    ADD COLUMN confianza_fin       numeric(3,2);     -- 0,9 inicio publicado; 0,7 formalización; 0,4 adjudicación

CREATE INDEX adjudicaciones_fin ON adjudicaciones (fecha_fin, id) WHERE fecha_fin IS NOT NULL AND resultado = 'adjudicado';

-- Suma una duración de origen (ANN, MON, DAY, WEE) a una fecha. Solo enteros razonables; si no, NULL.
CREATE FUNCTION lic_sumar_duracion(desde date, valor text, unidad text) RETURNS date LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN valor ~ '^[0-9]{1,4}$' AND (valor::integer) BETWEEN 1 AND 1200 THEN
        CASE unidad WHEN 'ANN' THEN (desde + make_interval(years => valor::integer))::date
                    WHEN 'MON' THEN (desde + make_interval(months => valor::integer))::date
                    WHEN 'WEE' THEN desde + 7 * valor::integer
                    WHEN 'DAY' THEN desde + valor::integer END
    END
$$;

CREATE OR REPLACE FUNCTION lic_proyectar_adjudicaciones(p_id uuid) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM adjudicaciones WHERE expediente_id = p_id;
    INSERT INTO adjudicaciones (expediente_id, n, lote, resultado, adjudicatario_nombre, adjudicatario_clave, adjudicatario_nif, moneda,
        importe_sin_iva, importe_con_iva, presupuesto_sin_iva, oferta_mas_baja, oferta_mas_alta, ofertas_recibidas, baja_anormal,
        fecha_adjudicacion, fecha_formalizacion, fecha_inicio, fecha_fin, fecha_fin_prorrogas, prorrogas_posibles, prorrogas_texto, confianza_fin)
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
        CASE WHEN r.x ->> 'formalized_on' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN (r.x ->> 'formalized_on')::date END,
        fin.inicio, fin.fin,
        CASE WHEN fin.fin IS NOT NULL AND coalesce(fin.prorroga ->> 'allowed', 'true') <> 'false' AND fin.prorroga #>> '{each,value}' ~ '^[0-9]{1,3}$'
                  AND fin.prorroga ->> 'count' ~ '^[0-9]{1,2}$'
             THEN lic_sumar_duracion(fin.fin + 1, ((fin.prorroga ->> 'count')::integer * (fin.prorroga #>> '{each,value}')::integer)::text, fin.prorroga #>> '{each,unit}') - 1
             END,
        (fin.prorroga ->> 'allowed')::boolean, left(fin.prorroga ->> 'text', 1000), fin.confianza
    FROM expedientes e
    CROSS JOIN LATERAL jsonb_array_elements(coalesce(e.documento -> 'results', '[]'::jsonb)) WITH ORDINALITY AS r (x, n)
    LEFT JOIN LATERAL (
        SELECT l.x FROM jsonb_array_elements(coalesce(e.documento -> 'lots', '[]'::jsonb)) AS l (x)
        WHERE l.x ->> 'id' = r.x ->> 'lot_id' LIMIT 1
    ) lote ON true
    -- Fin del contrato = inicio + duración prevista (la del lote, si la trae; si no, la del expediente) − 1 día. El inicio, por orden de fiabilidad: la entrada en
    -- vigor publicada (0,9), la fecha de formalización (0,7) o la de adjudicación (0,4). Sin inicio o sin duración, no hay fecha de fin.
    CROSS JOIN LATERAL (
        SELECT d.inicio, lic_sumar_duracion(d.inicio, dur ->> 'value', dur ->> 'unit') - 1 AS fin, d.confianza, coalesce(lote.x -> 'extension', e.documento -> 'extension') AS prorroga
        FROM (SELECT coalesce(lote.x -> 'duration', e.documento -> 'duration') AS dur) u,
        LATERAL (SELECT CASE
                     WHEN r.x ->> 'contract_starts_on' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN (r.x ->> 'contract_starts_on')::date
                     WHEN r.x ->> 'formalized_on' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN (r.x ->> 'formalized_on')::date
                     WHEN r.x ->> 'award_date' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN (r.x ->> 'award_date')::date END AS inicio,
                 CASE WHEN r.x ->> 'contract_starts_on' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN 0.9
                      WHEN r.x ->> 'formalized_on' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN 0.7 ELSE 0.4 END AS confianza) d
    ) fin
    WHERE e.id = p_id AND e.estado <> 'anulada' AND r.x ->> 'code' IN ('3', '8', '9');
END
$$;


SELECT lic_proyectar_adjudicaciones(id) FROM expedientes;
