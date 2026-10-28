-- Los eventos de la carga del histórico (ZIP) se publican en su propio flujo (LIC_HISTORICO, ADR 0002), no en el de la sindicación en vivo: así los consumidores del
-- Cerebro no reciben millones de «nuevas» y el histórico no expulsa del flujo en vivo lo que aún no se ha leído. Los eventos que ya estaban en el outbox son en vivo.
ALTER TABLE outbox ADD COLUMN historico boolean NOT NULL DEFAULT false;
