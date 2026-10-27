# Banco de pruebas del grafo (fase 0, ADR 0006)

> **Estado: PROVISIONAL.** Los datos de 10.000 expedientes son completos y fiables. Los de 1 millón están **incompletos** (solo Neo4j tiene
> resumen; Memgraph se quedó sin él y Postgres no se ha ejecutado a esa escala) y **el equipo donde se midió es inestable** (ver
> «Fiabilidad de las medidas»). **No se decide todavía el motor.** Este documento recoge lo medido y lo que falta para aplicar la
> regla de decisión del ADR 0006.

- **Fecha de las medidas**: 26/10/2026 · **Equipo**: PC de Albert, Intel Core i9-14900KF, 62 GB de RAM, Docker sobre WSL2.
- **Qué se compara**: A) Neo4j Community 5.26.32, B) Memgraph, C) **Postgres sin grafo** (control del ADR 0006). Mismo corpus sintético
  (`gen.go`, semilla 20261026), mismas 8 consultas (`query.go`) y mismos límites de contenedor (10 GB de RAM, 4 CPU).
- **Cómo se reproduce**: `licitaciones/bench/grafo` (`run.sh`, `main.go`, `summarize.py`). Los resultados en bruto (CSV/JSON por motor y escala)
  **no se suben a este repositorio** (algunos ficheros de caída pueden contener variables de entorno); están en el equipo que ejecutó el banco.
- **Consultas**: q1 comprador por CPV · q2 adjudicaciones de un proveedor · **q3 competidores por CPV y zona (NUTS)** · q4a vecindad del
  comprador · q4b vecindad de competidores · q5 historial de versiones · q6 contratos que vencen · q7 licitaciones similares.

## Resultados con 10.000 expedientes (completos)

Corpus: ~269.000 nodos y ~357.000 relaciones. «p95 a 20 c/s» = latencia p95 con 20 consultas por segundo, caché caliente.

| Motor | Carga | Reinserción de lo ya cargado (*upsert*) | q3 p95 a 20 c/s | Peor p95 de las 8 consultas a 20 c/s | RAM pico | Disco | Arranque en frío |
|---|---|---|---|---|---|---|---|
| Neo4j | 22.857/s | 10.931/s | (sin medida en caliente) 14,6 ms en frío | 20,6 ms en frío (q4a) | 5,05 GB | 594 MB | 5,3 s |
| Memgraph | 124.283/s | 125.610/s | 8,5 ms | 8,5 ms (q3) | 0,59 GB | 440 MB | 2,1 s |
| **Postgres** | 28.468/s | 18.891/s | **3,0 ms** | 4,7 ms (q6) | **0,10 GB** | **250 MB** | 0,7 s |

Todas las consultas de los tres motores quedan **muy por debajo** del umbral de 50 ms (criterio 1) a esta escala.
En frío, Postgres es más lento en algunas consultas (q2 20,5 ms, q5 24,1 ms) pero sigue dentro de los límites del criterio 2 (< 200 ms).

**Recuperación tras `kill -9` durante la carga (criterio 7)**: Memgraph y Postgres arrancan en 2 a 3 s y no dejan expedientes a medias
(`a_medias=0`, sin huecos). Neo4j arrancó en 6 s pero dejó **500 expedientes a medias** (con lotes y versiones sin escribir).
Falta revisar si es del motor o de cómo el banco trocea cada expediente en transacciones.

## Resultados con 1.000.000 de expedientes (incompletos)

Corpus: ~10 millones de nodos y ~19 millones de relaciones.

### Neo4j (único con resumen)
| Consulta | p95 con 1 c/s | p95 a 20 c/s | p95 en frío |
|---|---|---|---|
| q1 | 19,2 ms | 21,3 ms | 51,5 ms |
| q2 | 4,3 ms | 6,0 ms | 14,9 ms |
| **q3** | **291 ms** | **24.052 ms** | **280 ms** |
| q4a | **55,5 ms** | 56,5 ms | 58,7 ms |
| q4b | 13,2 ms | 15,9 ms | 36,1 ms |
| q5 | 0,6 ms | 2,5 ms | 15,0 ms |
| q6 | **60,1 ms** | 63,2 ms | 69,0 ms |
| q7 | 16,4 ms | 19,0 ms | 30,9 ms |

- **Criterio 1 (p95 < 50 ms)**: **no se cumple**. q3 es la consulta central de la competencia y con 20 consultas por segundo se satura (24 s). q4a y q6 se quedan
  ligeramente por encima. Es posible que mejore con otro plan de consulta (hay un `explain.txt` del banco), pero **no se ha comprobado**.
- **Criterio 3 (RAM ≤ 10 GB)**: cumple (6,7 GB residentes, 9,0 GB como máximo en la carga). **Disco**: 7,2 a 7,7 GB.
- **Criterio 5 (ingesta)**: 38.482 entidades/s en inserciones nuevas, por encima de las 2.000/s exigidas.
- **Calentamiento**: tras reiniciar tarda unos **24 s** por tanda y el p95 máximo baja de ~780 ms (criterio 2: tiempo hasta caliente < 5 min, cumple).
- **Recuperación tras `kill -9` (criterio 7)**: arranque en 18 s; de 50.000 expedientes en vuelo, 17.000 quedaron enteros, **1.000 a medias** y 32.000 sin escribir.
  Lo no confirmado puede perderse; lo **a medias** no debería existir si cada expediente va en una transacción.
- Hay un registro de caída de Java (`hs_err_pid7.log`, SIGSEGV) y un `verify-after-sigsegv.txt`: ver «Fiabilidad de las medidas».

### Memgraph (sin resumen)
Se ejecutó dos veces (`run-memgraph-1000000*.out`). La RAM residente llegó a **7,9 GB** y el uso del contenedor tocó los **10 GB** del límite
(10.737.721.344 bytes), con la carga completa. Sin resumen no hay cifras de latencia a 1 M. El proceso se cayó varias veces con fallos que no
son de un programa en buen estado (ver siguiente apartado).

### Postgres
**No se ha ejecutado a 1 millón.** Es la medida que falta para aplicar la regla 2 del ADR 0006.

## Fiabilidad de las medidas (importante)

El registro del sistema (`dmesg`) del equipo muestra, el mismo día, caídas de **programas distintos** con la firma de un fallo de hardware o de CPU,
no de un error de software:

| Programa | Fallo |
|---|---|
| Memgraph (2 veces) | `general protection fault` dentro de `libc.so.6` |
| Memgraph | `trap invalid opcode` (instrucción inválida) en el propio binario |
| ClickHouse (el de Langfuse) | `segfault` con `ip 0x0` y en otro caso en CPU 8; ambos «likely on CPU 8/16» |

Además, en el mismo equipo fallaron al construir imágenes de Docker procesos de Python con `Illegal instruction` (SIGILL), `exit code -11` (SIGSEGV)
y una capa de imagen con `invalid tar header`. Los fallos son aleatorios, de programas independientes y en CPU distintas.

El procesador es un **Intel Core i9-14900KF** (14.ª generación), afectado por el problema de inestabilidad por degradación (*Vmin Shift*) que Intel
reconoció en 2024 y que mitiga con la actualización de BIOS con microcódigo `0x12B` o posterior; Intel amplió la garantía de estos procesadores a 5 años.
Esto es una **hipótesis a descartar**, no un diagnóstico: hay que comprobar la versión de BIOS y la memoria.

**Consecuencia**: las caídas de Memgraph y de Neo4j **no se pueden atribuir al motor** mientras el equipo no sea estable, y las cifras de latencia
pueden estar afectadas. Los resultados de 10.000 expedientes (sin caídas) y la ausencia de fallos de Postgres son lo único sólido por ahora.

## Aplicación de la regla de decisión (ADR 0006)

| Paso de la regla | Estado |
|---|---|
| 1. Descartar la opción que no cumpla los criterios 1, 3, 5, 6 o 10 | Neo4j **incumple el 1** a 1 M (q3). Memgraph **está en el límite del 3**. Sin datos suficientes para descartar a ninguno con garantías. |
| 2. Si C (sin grafo) cumple 1 y 5 con el mismo corpus, se elige C | Cumple a 10.000 con mucho margen (q3 3 ms, 18.900 entidades/s). **No medido a 1 millón.** |
| 3. Entre las que cumplan, la de menos RAM | A 10.000, Postgres (0,10 GB) < Memgraph (0,59 GB) < Neo4j (5,05 GB). |
| 4. Empate: la copia en caliente más sencilla | Postgres (`pg_dump`/WAL) es la más sencilla. |

**Lectura provisional**: con lo medido, **Postgres sin grafo es el favorito** (menos RAM, menos piezas, mejores latencias a 10.000 y sin fallos),
pero **no se acepta** hasta medirlo con 1 millón de expedientes.

## Qué falta para cerrar el ADR 0006

1. **Estabilizar el equipo**: actualizar la BIOS (microcódigo `0x12B` o posterior), desactivar el perfil XMP/overclock, pasar el «Diagnóstico de memoria de Windows»
   y repetir una prueba de carga larga sin caídas en `dmesg`. Si el procesador sigue fallando, tramitar la garantía de Intel.
2. **Ejecutar Postgres con 1 millón** (mismas 8 consultas, 1 y 20 c/s, frío y caliente, `kill -9`, copia y restauración).
3. **Repetir Memgraph con 1 millón** una vez estable, y Neo4j si la regla 1 lo deja en juego tras revisar el plan de q3.
4. **Revisar la carga de Neo4j** (500 y 1.000 expedientes «a medias»): confirmar que cada expediente va en una transacción.
5. Con todo ello, aplicar la regla, cambiar el estado del ADR 0006 a Aceptado y fijar la elección con las cifras.

## Criterios sin medir

Quedan sin datos en este documento: criterio 6 (reconstrucción completa < 8 h), 8 (copia en caliente y restauración < 1 h), 10 (licencia y soporte, ya
descrito en el ADR) y 11 (alta disponibilidad, informativo).
