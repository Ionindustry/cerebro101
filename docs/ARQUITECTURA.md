# Arquitectura

## Recorrido de una petición

1. **Jarvis** recibe voz (Whisper la pasa a texto) o texto desde el panel e identifica al usuario (Keycloak).
2. **Director General** (`grafo/nodos.py: enrutar`) elige el departamento con el modelo rápido y salida estructurada.
3. **Director del departamento** (`elegir_agente`) elige el agente adecuado entre los de su departamento.
4. **Agente** (`ejecutar_agente`) trabaja en un bucle de hasta 5 pasos: en cada paso usa una herramienta o da
   su respuesta final con las acciones que propone.
5. **Aprobaciones**: cada acción propuesta pasa por `politicas.nivel_para`. Las que requieren aprobación se
   registran en la bandeja y el grafo **se detiene** (`interrupt` de LangGraph) hasta que las personas deciden.
6. **Ejecución**: las acciones aprobadas se ejecutan con `aprobada=True`; las rechazadas quedan registradas.

El estado de cada conversación se guarda en PostgreSQL (checkpointer de LangGraph), así que una aprobación
puede llegar horas después y el flujo continúa donde se quedó.

## Piezas

| Pieza | Fichero | Función |
| --- | --- | --- |
| Registro de agentes | `cerebro/registro.py` | Carga y valida las fichas YAML |
| Políticas | `cerebro/politicas.py` | Niveles de aprobación, acciones prohibidas, sensibilidad de datos por herramienta |
| Router de modelos | `cerebro/router_modelos.py` | Modelo rápido, principal, visión o juez según ficha, imágenes y dificultad |
| Cliente de modelos | `cerebro/llm.py` | Ollama con salida JSON validada; reintento con el modelo principal |
| Herramientas | `cerebro/herramientas/` | Punto único `usar()` con control de permisos y registro |
| Grafo | `cerebro/grafo/` | Orquestación con LangGraph |
| Aprobaciones | `cerebro/aprobaciones/` | Reglas (probadas) y persistencia de la bandeja |
| Cotizador | `cerebro/cotizador/motor.py` | Motor determinista del contador de instalaciones |
| Red de instaladores | `cerebro/red_instaladores/comparador.py` | Puntuación por precio, rapidez y eficiencia |
| API | `cerebro/api/main.py` | Endpoints para panel, Jarvis y aprobaciones |
| Tareas programadas | `cerebro/tareas/celery_app.py` | Calendario generado a partir del horario de cada ficha |

## Principios

- **Los importes no los calcula la IA.** El cotizador, el comparador y los precios son código determinista;
  los modelos solo rellenan datos y redactan.
- **Las reglas de seguridad están en código**, no en las instrucciones del modelo: aunque un modelo se equivoque,
  `usar()` bloquea las operaciones externas sin aprobación y las herramientas que no están en su ficha.
- **Los documentos del ERP se crean siempre en borrador**; la validación es humana.
- **Los datos sensibles no salen**: cada herramienta externa declara la sensibilidad máxima que admite, y si
  hay alternativa local (jeff en lugar de Jev) se usa automáticamente.

## Uso de la tarjeta gráfica

Ollama mantiene cargados el modelo rápido, el principal y los embeddings; visión y juez se cargan bajo demanda
(`keep_alive` de 5 minutos). Jarvis lo atiende la API directamente, sin cola; las tareas programadas van a la
cola `lote` y están concentradas de noche en las fichas.
