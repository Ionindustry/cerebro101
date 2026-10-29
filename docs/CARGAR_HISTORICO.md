# Cargar el histórico de licitaciones (paso a paso)

La sindicación en vivo de PLACSP solo llega al principio del mes en curso. Lo anterior hay que cargarlo desde los ZIP de datos abiertos. Sin esa carga, las páginas de
**Competencia**, **Contratos que vencen** y **fichas de organización** casi no tienen datos y los avisos de competencia no tienen con qué comparar.

Se hace **poco a poco**: del mes más reciente hacia atrás, midiendo en cada paso. Todo lo cargado se conserva; se puede parar y seguir cuando quieras.

## Lo que ocurre por dentro (para no asustarse)
- El ingestor baja **un ZIP por vuelta** (el más reciente primero), lo abre sin descomprimirlo en disco y guarda cada página y cada licitación en el almacén de originales.
- Los eventos de lo que carga van a su **propio flujo** (`LIC_HISTORICO`), que solo lee el proyector. **El Cerebro no los recibe**: no se llenan el embudo ni las alertas de
  «nuevas» antiguas. Lo que llega en vivo tiene prioridad y sale siempre antes.
- El proyector convierte esos eventos en expedientes del modelo de lectura. Es lo que más tarda: procesa 6 eventos del histórico a la vez (y 2 de lo en vivo); antes iba de uno en uno, a unos 3 o 4 expedientes por segundo. Si el flujo del histórico se llena (2 GiB), el ingestor espera: no se pierde nada.
- Un ZIP que aún no existe se salta y se reintenta. Un fallo a mitad de un ZIP se retoma en el siguiente fichero.

## Antes de empezar (una vez)
1. Copia de seguridad hecha y **sacada del PC**: `COPIA_SIN_TRAZAS=1 ./scripts/copia_seguridad.sh`.
2. El PC estable: nada al 99 % de CPU. Mira `uptime` y el administrador de tareas. Si se cuelga, no sigas: arregla eso primero.
3. Espacio en disco. **Estimación** (a confirmar con el primer mes): cada mes ocupa del orden de 1–2 GB entre almacén de originales y base de datos, y un ZIP anual
   necesita además 1–2 GB de sitio temporal mientras se baja. Mira `df -h /` y `docker system df`. Un año completo puede pedir 15–25 GB.
4. El motor actualizado con la versión que separa los flujos (de lo contrario el histórico iría al flujo en vivo):
   ```
   git checkout main && git pull --ff-only
   docker compose -f licitaciones/compose.yaml -f licitaciones/compose.cerebro.yaml --env-file .env up -d --build ingestor proyector api
   ```
   Si el build falla con capas corruptas o SIGSEGV, repite solo ese servicio con `--no-cache`.

## Paso 1: un solo mes
1. En `.env` pon `LIC_HISTORICO_DESDE=2026-09` (el último mes cerrado; ajusta al mes que toque).
2. Recrea el ingestor para que lea el valor:
   ```
   docker compose -f licitaciones/compose.yaml -f licitaciones/compose.cerebro.yaml --env-file .env up -d ingestor
   ```
3. Míralo cargar, repitiendo cada pocos minutos:
   ```
   ./scripts/estado_historico.sh
   ```
   Verás los ZIP cargados, los eventos que esperan, los expedientes proyectados y las últimas líneas de los logs. Ha terminado cuando el ZIP aparece en la lista, el
   outbox llega a 0 y los expedientes dejan de crecer entre dos ejecuciones.
4. **Mide** y apunta: cuánto tardó, la carga del PC mientras tanto, y el crecimiento del disco (`docker system df -v`, volúmenes `s3-datos`, `pg-datos`, `nats-datos`).
5. **Comprueba con datos reales** (panel → Licitaciones):
   - **Competencia**: elige un CPV (por ejemplo `72` informática o `35125` videovigilancia) y mira que salgan adjudicatarios con importes razonables y la baja media.
   - **Contratos que vencen**: que salgan contratos con fecha de fin plausible.
   - Abre la ficha de un organismo y la de un competidor.
   Si algo no cuadra, **para aquí** y cuéntamelo con el ejemplo concreto: es mejor corregir con un mes que con tres años.

## Paso 2: ampliar, sin prisa
Solo si el paso 1 fue bien (PC estable, disco con margen). Cambia `LIC_HISTORICO_DESDE` y repite «recrea el ingestor» y «míralo cargar»:

| Paso | `LIC_HISTORICO_DESDE` | Qué carga |
|---|---|---|
| 2 | `2026-01` | los meses cerrados de este año |
| 3 | `2025` | el año 2025 (un ZIP anual grande) |
| 4 | `2024` | el año 2024 |

Entre un paso y otro, espera a que el proyector termine y vuelve a medir. Lo ya cargado no se repite.

## Parar
Deja `LIC_HISTORICO_DESDE=` vacío en `.env` y recrea el ingestor. Se conserva todo lo cargado y, al volver a poner un valor, sigue donde quedó.

## Si algo va mal
- **El PC se pone al 99 % o se cuelga**: para (arriba). Con el ingestor limitado a media CPU y el proyector a una, no debería, pero tu equipo ya ha dado fallos de hardware.
- **El ZIP no se descarga**: los servidores exactos de los ZIP están **por verificar con una descarga real**. El ingestor prueba `contrataciondelsectorpublico.gob.es` y
  `contrataciondelestado.es`. Si ves «el ZIP del histórico aún no existe en este servidor» en los dos, copia la línea del log y me la pasas.
- **«The service is unavailable» al guardar un original** (ingestor): el almacén RustFS se cae, casi siempre por falta de memoria. `./scripts/estado_historico.sh` enseña cuántas veces ha arrancado el proceso (1 = nunca se ha caído). Con el límite de 4 GB del compose actual no debería; si pasa, para y avisa.
- **Disco casi lleno**: para y avisa. No borres volúmenes a mano.
- **Ver los logs**: `docker logs --tail 50 licitaciones-ingestor-1` y `docker logs --tail 50 licitaciones-proyector-1`.
