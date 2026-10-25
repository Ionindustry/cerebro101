# Cuadernos de investigación (como NotebookLM, en local)

Un agente que investiga reúne en un **cuaderno** las fuentes de un tema (páginas web públicas y sus propias notas) y después le
pregunta: la respuesta sale de esas fuentes y **cita cada dato** con su número ([1], [2]…) y el enlace.

NotebookLM no sirve para esto: Google no ofrece una API para preguntar a un cuaderno (la de NotebookLM Enterprise solo crea
cuadernos y añade fuentes, y pide Gemini Enterprise) y las librerías no oficiales usan las cookies de una cuenta de Google.
Los cuadernos del Cerebro viven en la base de datos propia (PostgreSQL + pgvector, embeddings `bge-m3`): no sale nada del servidor
salvo la visita a la página pública, con los mismos controles que la herramienta `web`.

## Cómo se usa

En Jarvis basta con pedirlo: «Investiga en internet las obligaciones de los carteles de videovigilancia, guárdalo en un cuaderno
llamado *Carteles videovigilancia* y respóndeme citando las fuentes». El agente:

1. `investigar`: busca el tema y guarda las mejores páginas (4 por defecto, hasta 8) en el cuaderno; lo crea si no existe.
2. `consultar`: recupera los fragmentos que responden a la pregunta, numerados.
3. Responde citando y lista las fuentes.

Más adelante se puede volver a preguntar al mismo cuaderno («¿Qué dice el cuaderno *Carteles videovigilancia* sobre el plazo de
conservación?») o ampliarlo con `guardar_web` (una página concreta) o `guardar_nota` (un resumen o datos de otra herramienta).

## Quién lo tiene

Los agentes que investigan, todos de sensibilidad baja: Asistente general (Dirección), Analista de Noticias, Analista de
Competencia y Radar de Tendencias (Marketing), Explorador de Fabricantes (Operaciones), Inteligencia Competitiva y Viabilidad
(Licitaciones). La lista está en `INVESTIGAN` de `scripts/generar_fichas.py`.

Si una petición habla de un **cuaderno** y el reparto la manda a un departamento o agente sin cuadernos (el modelo rápido la
confundía con la base de conocimiento), el sistema la corrige hacia quien sí los tiene (`corregir_por_cuaderno` en `grafo/nodos.py`).

## Reglas (en el código)

- **Cada cuaderno es de un departamento**: un agente solo ve los del suyo; el departamento lo pone el sistema, no el modelo.
- **Traer páginas de internet** (`investigar`, `guardar_web`) solo con sensibilidad baja; las búsquedas pasan el filtro de la
  herramienta `web` (sin nombres de clientes, empleados ni datos personales) y la lectura respeta `robots.txt` y no llega a la red interna.
- Hasta 100 fuentes por cuaderno y 20 000 caracteres por fuente; una URL repetida no se guarda dos veces.
- Solo se leen páginas HTML o de texto (los PDF enlazados aún no).

## Siguientes pasos

- Pantalla «Cuadernos» en el panel para que las personas los vean y les pregunten.
- Resúmenes de audio de un cuaderno con las voces de Piper.
