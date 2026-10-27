# ADR 0001 — Registro de decisiones de arquitectura

- **Estado**: Aceptado
- **Fecha**: 26/10/2026
- **Autor**: arquitecto del motor (agente `licitaciones-arquitecto`); aprueba el responsable del motor

## Contexto
El motor de licitaciones introduce muchas piezas nuevas en un servidor que ya ejecuta el Cerebro y Ollama (Go, grafo,
OpenSearch, NATS, MinIO, Redis). Cada una tiene coste de memoria y de operación. Sin un registro, las decisiones se olvidan,
se rehacen o se toman «por moda». `NORMAS.md` exige un ADR por decisión importante; este documento fija cómo se escriben.

## Opciones
| Opción | Pros | Contras |
|---|---|---|
| A. ADR en Markdown dentro del repositorio (`licitaciones/adr/`) | Se revisan en el mismo PR que el código; historial en git; legibles sin herramientas | Requiere disciplina para mantener el estado |
| B. Wiki o documento externo | Edición rápida | Se separa del código; sin revisión en PR; se queda viejo |
| C. Sin registro (comentarios en los PR) | Cero coste | Imposible saber por qué se decidió algo seis meses después |

Criterio: que cualquier decisión se pueda encontrar y justificar desde el repositorio en < 5 minutos.

## Decisión
**Opción A.** Un fichero por decisión: `licitaciones/adr/NNNN-titulo-en-minusculas.md`, numeración correlativa, nunca se
reutiliza un número.

### Formato obligatorio
```markdown
# ADR NNNN — Título
- Estado: Propuesto | Provisional | Aceptado | Sustituido por NNNN | Rechazado
- Fecha / Autor / Aprueba
## Contexto            (requisito del proyecto con su §, restricciones, datos medidos)
## Opciones            (al menos dos, con pros y contras y CRITERIOS MEDIBLES: cifra, umbral, cómo se mide)
## Decisión            (la elegida y por qué, referida a los criterios)
## Consecuencias       (qué se gana, qué se pierde, qué obliga a hacer, riesgos)
## Cómo se revisará    (qué medida o suceso reabre la decisión, y cuándo se comprueba)
```

### Reglas
- **Provisional** = falta el dato que la confirma. Dice qué medida la confirmará y dónde se publicará (p. ej. ADR 0006 →
  `licitaciones/docs/BENCH_GRAFO.md`). Una decisión provisional no bloquea el trabajo que no depende de ella.
- Lo no comprobado con una fuente real o una medida se escribe «POR VERIFICAR» (`NORMAS.md`).
- Un ADR aceptado **no se reescribe**: se crea otro que lo sustituye y se cambia el estado del antiguo a «Sustituido por NNNN».
  Se permiten correcciones de erratas y enlaces.
- Toda complejidad nueva (un servicio, una dependencia, una cola) necesita un ADR o una línea en uno existente con el requisito
  o la medida que la justifica.
- El ADR va en el mismo PR que el primer código que lo aplica, o en un PR propio si es previo (como los de la fase 0).
- Aprueba el responsable del motor al fusionar el PR; los ADR que afectan al Cerebro (0007) los revisa también quien mantiene
  el Cerebro.

## Consecuencias
- Coste: ~1 hora por decisión. Beneficio: las revisiones de PR se apoyan en criterios escritos, no en preferencias.
- El índice vive en `licitaciones/README.md` (sección «Decisiones»); hay que actualizarlo al añadir un ADR.

## Cómo se revisará
Al cerrar cada fase se repasan los ADR en estado Propuesto o Provisional: o se confirman con su medida, o se sustituyen.
Si un PR toma una decisión de arquitectura sin ADR, el revisor lo devuelve.
