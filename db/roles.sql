-- Roles y permisos (ISO 27001: mínimo privilegio). Se ejecuta en cada arranque, siempre como propietario,
-- desde el servicio «migraciones»; es idempotente. La contraseña del rol la pone cerebro.migrar.
--
--   cerebro      propietario de la base de datos: esquema, disparadores y migraciones. Solo lo usa «migraciones».
--   cerebro_app  la usan la API, el worker y beat. No puede crear ni alterar tablas ni quitar disparadores,
--                y sobre las evidencias solo tiene los permisos mínimos.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cerebro_app') THEN
    CREATE ROLE cerebro_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END $$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM cerebro_app;
GRANT USAGE ON SCHEMA public TO cerebro_app;

-- Operación normal: leer y escribir datos (conocimiento, licitaciones, instaladores, estado del grafo…)
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM cerebro_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cerebro_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cerebro_app;

-- Evidencias: el registro de acciones solo se lee y se anexa; las aprobaciones no se borran
REVOKE UPDATE, DELETE ON registro_acciones FROM cerebro_app;
REVOKE DELETE ON aprobaciones FROM cerebro_app;
