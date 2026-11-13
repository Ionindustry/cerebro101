# Keycloak en modo producción con PostgreSQL

Keycloak es el inicio de sesión de Jarvis. Hasta ahora arrancaba en **modo desarrollo** (`start-dev`) con una base de datos **H2 en un fichero**: sirve para probar, pero no es lo recomendado para producción (más frágil ante cortes y actualizaciones). Este cambio lo pasa al **modo producción** (`start`, arranque optimizado) con su **propia base PostgreSQL**, **sin perder usuarios, contraseñas ni ajustes**.

Es para la instalación local (un PC con Docker Desktop). El servidor completo (`despliegue/desplegar.sh` + `despliegue/docker-compose.produccion.yml`) ya lleva Keycloak así y no necesita esto.

## Cómo se hace (ventana **Ubuntu**, `pc@DESKTOP…$`)

```bash
cd /home/pc/cerebro101
git pull --ff-only
./scripts/keycloak_a_postgres.sh
```

Tarda unos 3-5 minutos y **durante ese rato nadie puede iniciar sesión en Jarvis**. No lo hagas mientras «Preparar la oferta» está trabajando (el panel pediría iniciar sesión de nuevo; el trabajo del worker no se pierde, pero es mejor no mezclarlo).

El script, y se detiene **sin cambiar nada** si algo falla:

1. Copia los datos actuales (`copias/keycloak-postgres-FECHA/h2`). **Los datos viejos no se tocan nunca**.
2. Exporta el realm `cerebro` **con sus usuarios** (`copias/keycloak-postgres-FECHA/export`) y comprueba que trae usuarios.
3. Genera él mismo la contraseña de la base de Keycloak (no la tienes que escribir ni ver; queda en el `.env`) y **fija la versión exacta de Keycloak** (`KEYCLOAK_IMAGEN`), para que una actualización futura sea una decisión tuya.
4. Activa `despliegue/docker-compose.keycloak-postgres.yml` en `COMPOSE_FILE` del `.env` y arranca Keycloak con PostgreSQL importando esa exportación.
5. Comprueba que responde, que el administrador entra y que hay usuarios. Si algo no cuadra, **vuelve atrás solo**.

Al terminar, **prueba a iniciar sesión en Jarvis**.

## Qué cambia y qué no

- Misma dirección y mismos puertos (Keycloak sigue solo en `127.0.0.1:8080`, y detrás del proxy si el acceso externo está activo). El panel y la API no necesitan ningún cambio.
- Usuarios, contraseñas, roles y clientes (con sus secretos) se conservan. **Las sesiones abiertas se cierran**: hay que volver a iniciar sesión.
- El administrador de Keycloak (`admin`) se vuelve a crear con la contraseña `KEYCLOAK_ADMIN_PASSWORD` del `.env`. Si la habías cambiado desde la consola de Keycloak, entra con la del `.env` (y cámbiala con `scripts/keycloak_clave_admin.sh` si quieres).
- Los ficheros de `copias/keycloak-postgres-…` contienen contraseñas cifradas y secretos de clientes: no los compartas. Están fuera de git.

## Volver atrás

```bash
./scripts/keycloak_a_postgres.sh --deshacer
```

Vuelve al modo anterior con los datos del volumen viejo (los de **antes** del cambio: los usuarios que crees después de migrar no estarán ahí). La base PostgreSQL y su volumen se quedan por si quieres volver a intentarlo.

## Copias de seguridad

Desde ahora los usuarios viven en el volumen `keycloak-db` de Docker (PostgreSQL) y **`scripts/copia_seguridad.sh` los incluye** (`keycloak.sql.gz`). El volumen viejo `keycloak-datos` ya no se usa tras el cambio; **no lo borres** hasta que lleves unos días trabajando con normalidad y tengas una copia de seguridad reciente (`scripts/copia_seguridad.sh`). Cuando quieras limpiarlo: `docker volume ls` para ver su nombre completo y `docker volume rm <nombre>` solo para ese volumen. **En Docker Desktop no uses «Reset to factory defaults» ni «Clean / Purge data»: borran todos los volúmenes.**

**Restaurar** (con Keycloak parado y la base vacía): `docker compose stop keycloak`, `gunzip -c keycloak.sql.gz | docker compose exec -T keycloak-db psql -U keycloak keycloak` y `docker compose start keycloak`. Si la base no estuviera vacía, recréala antes (`DROP SCHEMA public CASCADE; CREATE SCHEMA public;` dentro de `psql`).
