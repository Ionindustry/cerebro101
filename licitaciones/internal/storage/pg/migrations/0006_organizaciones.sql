-- Fichas de organismo y de competidor (`/organizations/{id}`): el identificador de un comprador es el mismo UUID derivado que ya sirven las listas
-- (`uuid8("org:" + NIF, o DIR3, o el nombre)`), así que para encontrarlo por UUID hace falta guardarlo. Es una columna generada: no hay lógica duplicada ni nada que
-- mantener, y se calcula ahora, cuando la tabla todavía es pequeña (la carga del histórico la hará crecer).
ALTER TABLE expedientes ADD COLUMN comprador_id uuid GENERATED ALWAYS AS (
    lic_uuid8('org:' || coalesce(nullif(comprador_nif, ''), nullif(comprador_dir3, ''), nullif(comprador_nombre, '')))) STORED;

CREATE INDEX expedientes_comprador_id ON expedientes (comprador_id) WHERE comprador_id IS NOT NULL;
CREATE INDEX expedientes_comprador_dir3 ON expedientes (comprador_dir3) WHERE comprador_dir3 <> '';
