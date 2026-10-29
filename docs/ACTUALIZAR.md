# Actualizar el servidor

Las imágenes del Cerebro (API, worker, beat, migraciones y panel) las **construye GitHub** (flujo «Imágenes», `.github/workflows/imagenes.yml`) cada vez que se fusiona algo en `main`
y las publica, privadas, en `ghcr.io/ionindustry/cerebro101-api` y `…-panel`. El servidor solo las **descarga**: construirlas en el propio PC es lento y, en el PC de la oficina,
ha dado capas corruptas de Docker. El motor de licitaciones (Go, una imagen pequeña) sí se sigue construyendo en el servidor.

## Cada actualización

```
cd /home/pc/cerebro101
./scripts/actualizar.sh
```

El script trae el código (`git pull --ff-only`), reconstruye el motor, descarga las imágenes nuevas del Cerebro y reinicia lo que ha cambiado. Antes de lanzarlo, comprueba en GitHub
(pestaña **Actions**) que el flujo **Imágenes** del último cambio de `main` está en verde: si no ha terminado, la descarga dice «manifest unknown» y basta con esperar.

## La primera vez: entrar en el registro

Las imágenes son privadas porque llevan la configuración de los agentes. Hace falta, una sola vez en cada equipo:

1. En GitHub: foto de perfil → *Settings* → *Developer settings* → *Personal access tokens* → *Tokens (classic)* → *Generate new token (classic)*, con **solo** el permiso `read:packages`.
2. En el servidor: `docker login ghcr.io -u TU_USUARIO_DE_GITHUB` y, cuando pida la contraseña, pegar el token (no se ve al escribirlo).

El token es una contraseña: no se escribe en chats, ficheros del repositorio ni correos. Si se pierde o se comparte por error, se borra en la misma pantalla de GitHub y se crea otro.

## Si GitHub no las tiene o no hay acceso

`./scripts/actualizar.sh --construir` las construye en el propio equipo (como antes).

## Volver a una versión anterior

Cada imagen se publica también con el código completo de su commit como etiqueta. Con `CEREBRO_VERSION=<código del commit>` en el `.env`, `docker compose pull api panel` y
`docker compose up -d --no-build api worker beat panel licitaciones-eventos`, el servidor vuelve a esa versión. (Las migraciones de la base de datos no se deshacen solas: solo añaden.)
