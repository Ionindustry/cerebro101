# Cómo se trabaja en este repositorio

## Regla de oro: un PR = un cambio
Desde la versión inicial, todo cambio va en una **rama propia y un PR pequeño** (una función, un arreglo, una pantalla), nunca directo a `main`.
Un PR que se puede leer en 10 minutos se revisa de verdad; uno de 200 ficheros, no.

```bash
git switch main && git pull
git switch -c mejora/descripcion-corta
# … cambios …
git push -u origin mejora/descripcion-corta      # y se abre el PR en GitHub con la plantilla
```

## Comprobaciones automáticas (CI, `.github/workflows/ci.yml`)
Cada PR ejecuta: pruebas de la API (Python), pruebas del panel (Node), búsqueda de secretos en los ficheros y en todo el historial,
validez de `docker-compose.yml` y del compose de ERPNext, sintaxis de los scripts, que las fichas de los agentes estén al día y, para `licitaciones/`, el trabajo de Go (formato, `go vet`, `staticcheck`, `golangci-lint`, pruebas con `-race`, `govulncheck` y construcción de la imagen).
**Si algo está en rojo, no se fusiona.** En local: `cd api && python -m unittest discover -s tests`, `cd panel && node --test test/*.test.mjs`,
`python3 scripts/comprobar_secretos.py` y, para el motor de licitaciones, `cd licitaciones && go vet ./... && go test -race ./...` (ver `licitaciones/README.md`).

## Proteger `main` (se hace una vez en GitHub, no se puede desde el código)
Ajustes del repositorio → **Rules → Rulesets** (o *Branches → Branch protection rules*) → regla para `main`:
- Exigir un PR antes de fusionar.
- Exigir que pasen las comprobaciones: **API · pruebas de Python**, **Panel · pruebas de Node** y **Configuración · secretos, compose, scripts y fichas**. «**Licitaciones · Go**» se añade a esa lista cuando lleve una semana en verde (ADR 0008).
- Bloquear los *force push* y el borrado de la rama.
- (Si hay más de una persona) exigir al menos una aprobación.

## Secretos
Las claves nunca se suben: `.env` y `secretos/` están fuera de git. Si una clave se sube por error, **se considera perdida: se cambia en el servicio** (borrarla del
historial no basta) y se avisa. El detector de CI lo pillará en el siguiente PR.
