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
