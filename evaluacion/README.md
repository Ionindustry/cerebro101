# Evaluación del enrutado

`bateria_enrutado.yaml` son 50 peticiones con el departamento y el agente que deben atenderlas.
`scripts/evaluar_enrutado.py` las envía a `POST /jarvis/enrutar` (solo enruta, no ejecuta agentes ni crea
aprobaciones) y guarda un informe en `resultados/`.

## Resultados

| Fecha | Modelo | Cambio | Departamento | Agente |
| --- | --- | --- | --- | --- |
| 2026-10-03 | ministral-3:3b (CPU) | base | 29/50 (58 %) | 29/50 (58 %) |
| 2026-10-03 | ministral-3:3b (CPU) | el Director General ve los agentes de cada departamento y una regla para «areas» | 32/50 (64 %) | 32/50 (64 %) |

Notas de la segunda medición:
- 3 preguntas fallaron por `ReadTimeout` de Ollama (CPU saturada), no por enrutado; cuentan como fallo.
- La diferencia entre 58 % y 64 % está dentro del ruido de un modelo de 3B (9 preguntas mejoran y 6 empeoran).
- Con un modelo de 3B el criterio del 90 % no es realista. Hay que repetirla con los modelos del perfil
  `pequena` o `grande` en la tarjeta gráfica del servidor, y ampliar la batería con peticiones reales.


## Anonimización para Jev

`anonimizacion_corpus.yaml`, `anonimizacion_ciego.yaml` y `anonimizacion_ciego2.yaml` (textos sintéticos, sin datos
reales). Se miden con `python scripts/evaluar_anonimizacion.py --corpus evaluacion/<fichero>.yaml`.

| Conjunto | Capa | Primera medición | Tras corregir lo que falló |
| --- | --- | --- | --- |
| `corpus` (con el que se desarrolló el detector) | datos con formato | 21/21 | 21/21 |
| | entidades conocidas | 12/12 | 12/12 |
| | nombres libres | 7/8 (88 %) | 10/10 |
| | categorías especiales bloqueadas | 5/5 | 5/5 |
| `ciego` (escrito después) | datos con formato | 7/13 (54 %) | 13/13 |
| | entidades conocidas | 3/4 (75 %) | 4/4 |
| | nombres libres | 11/14 (79 %) | 13/14 (93 %) |
| | categorías especiales bloqueadas | 2/3 | 3/3 |
| `ciego2` (escrito después de los dos) | datos con formato | 11/14 (79 %) | 14/14 |
| | entidades conocidas | 1/2 (50 %) | 2/2 |
| | nombres libres | 10/12 (83 %) | 12/12 |
| | categorías especiales bloqueadas | 0/5 | 5/5 |

Cómo leerlo: la columna «primera medición» es la cobertura **antes** de ajustar el detector contra ese conjunto, y es
la que se parece a lo que pasará con textos reales nuevos. Los conjuntos `ciego` y `ciego2` dejaron de ser ciegos al
corregir sus fallos, así que su columna final solo sirve como prueba de regresión. Las correcciones fueron generales
(IBAN en minúsculas o sin espacios, teléfonos fijos, direcciones con coma, DNI con puntos, fechas con letras,
dominios sin `http`, nombres en mayúsculas, empresas sin «SL», prefijos de palabra en las categorías especiales),
no casos sueltos, pero con textos reales aparecerán fallos distintos.

Limitaciones conocidas que no se cubren: nombres en minúsculas sin ninguna pista previa («habló con josep»,
«laura gómez»).


## Uso de herramientas por los agentes

`herramientas_casos.yaml` son 16 peticiones que exigen una herramienta concreta; `scripts/evaluar_herramientas.py` hace
**una** llamada al modelo del agente por petición (sin ejecutar nada) y comprueba si usa una herramienta de su ficha, si la
operación existe, si los argumentos son válidos y si es la correcta. Se ejecuta dentro del contenedor de la API (donde está el modelo).

| Prompt | Llamadas válidas | Operación inventada | Argumentos inválidos | JSON cortado o inválido |
| --- | --- | --- | --- | --- |
| Antiguo (una frase por herramienta) | 1/16 (6 %) | 11 | 0 | 4 |
| Con el esquema exacto de cada herramienta | **13/16 (81 %)** | 0 | 2 | 1 |

(ministral-3:3b en CPU, temperatura 0, salida limitada a 500 tokens, una sola ejecución. Informe: `resultados/herramientas.json`.)

Antes, el modelo se inventaba el nombre de la operación casi siempre (`leer_bandeja_entrada`, `extraer_tarifas_productos`,
`consulta_stock_articulos`…). Ahora el prompt lleva, para cada herramienta de la ficha, sus operaciones con sus argumentos
exactos (derivados de las firmas reales de las funciones, y los identificadores válidos del cotizador leídos del catálogo),
y un ejemplo. Los tres fallos que quedan son argumentos añadidos de más (`consideraciones_adicionales`, `item_name`) o JSON
cortado; en el bucle del agente reciben un mensaje que dice qué argumentos están permitidos y pueden corregirse.

Límites de la medición: 16 casos escritos por mí, una sola muestra por caso y un modelo pequeño en CPU. Con los modelos
reales de la GPU habrá que repetirla; el script es el mismo.

## Calidad de las respuestas (`scripts/evaluar_calidad.py`)

19 casos en `calidad_casos.yaml` que pasan por el agente real (modelo, herramientas y prompts de producción) y se comprueban con
reglas automáticas: las cifras las calcula el motor (no el modelo), y se vigila que no invente datos, que no ejecute ni
afirme haber ejecutado nada externo, que no revele instrucciones o claves, y el idioma y la longitud.

Medición con `ministral-3:3b` en CPU (ERPNext apagado, Jev sin acceso → modelo local):

| Tipo | Resultado | Fallos |
| --- | --- | --- |
| Cifras (4) | 3/4 → 4/4 | C04 fallaba porque el modelo rellenaba «pesos» (objeto libre) con texto y claves inventadas; ahora la herramienta lo explica y la ayuda dice que se omita. Repetido: pasa (296 s en CPU) |
| No inventar (4) | 3/4 | C06: bucle hasta el tope de 4096 tokens |
| Seguridad (5) | 5/5 | — |
| Redacción (4) | 3/4 | C17: bucle hasta el tope de tokens. C15 falló por una regla mal escrita (corregida) |
| Criterio (2) | 2/2 | — |
| **Total** | **16/19 tras corregir C15 y repetir C01** | C01 agotó el tiempo una vez por saturación de CPU y pasó al repetirlo |

Lo que enseña: con cifras de por medio, el modelo usa el motor y copia el importe bien; en seguridad no ejecutó ni afirmó
nada que no debía. Los fallos reales son dos: el modelo pequeño a veces no cierra la respuesta (se corta en el tope de
tokens) y no sabe llamar al comparador con los argumentos correctos. Los casos que «pasan» no siempre son buenas respuestas
(p. ej. C11 y C18 dan un rodeo inútil): esta batería detecta lo grave, no mide la utilidad. Hay que repetirla con los modelos
de GPU del perfil real; los umbrales de tiempo de esta medición son de CPU.
