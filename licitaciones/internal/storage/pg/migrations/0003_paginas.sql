-- Páginas de archivo ya ingeridas (una página de archivo no cambia una vez publicada): las ejecuciones siguientes las saltan sin descargarlas y un
-- fallo a mitad de la carga se retoma donde quedó. `siguiente` es el enlace al que apuntaba, para seguir la cadena sin descargar la página.
CREATE TABLE paginas_ingeridas (
    fuente    text        NOT NULL,
    url       text        NOT NULL,
    siguiente text        NOT NULL DEFAULT '',
    ingerida  timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (fuente, url)
);

-- Por dónde seguir hacia atrás cuando la primera página responde «sin cambios».
ALTER TABLE puntos_control ADD COLUMN siguiente text NOT NULL DEFAULT '';
