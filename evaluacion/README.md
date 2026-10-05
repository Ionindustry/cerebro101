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
