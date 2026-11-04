-- Peticiones de «actualiza ya»: cuando alguien abre la aplicación y lo último ingerido es viejo, la API del motor anota aquí una petición y el ingestor, que mira esta tabla
-- mientras espera a su siguiente vuelta, la empieza de inmediato en vez de esperar al intervalo. Se conservan pocos días: es solo el rastro de quién pidió qué y cuándo.
CREATE TABLE ingest_solicitudes (
    id        bigserial PRIMARY KEY,
    pedido_en timestamptz NOT NULL DEFAULT now(),
    por       text NOT NULL DEFAULT ''
);
CREATE INDEX ingest_solicitudes_pedido_en ON ingest_solicitudes (pedido_en DESC);
