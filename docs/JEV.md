# JEV: motor de decisiones cerradas

Jev (TypeSafe) contesta preguntas cerradas —elegir entre opciones, puntuar de 0 a 10, sí/no— con una probabilidad. Los agentes lo usan con la herramienta `jev` (también existe `jeff`).
Hay tres vías, siempre con la misma interfaz, y **los agentes pasan solos de una a la siguiente si falla**:

| Vía | Qué es | Cuándo se usa |
|---|---|---|
| **Jev (nube)** | API de TypeSafe | Datos de sensibilidad baja o media, y siempre **anonimizados** (`docs/SEGURIDAD.md`). Necesita `USAR_JEV_NUBE=true` y `JEV_API_KEY` |
| **jeff (autoalojado)** | Servicio propio (`servicios/jeff`) con la **misma API** que Jev, servido por el modelo «juez» de Ollama. Ningún dato sale del servidor | Datos sensibles (RR.HH., clientes, económicos), y como respaldo si Jev no está activo, falla o el texto no es apto para la nube |
| **Modelo local** | El modelo del agente con salida estructurada | Último recurso si jeff tampoco responde |

## Comprobar que está operativo
- En **Agentes** hay un indicador «Decisiones (JEV)»; al pulsarlo se ve el estado de cada vía, qué usará cada sensibilidad de datos y un botón **Comprobar ahora** (hace una pregunta real, la de la nube sin datos de nadie).
- Por terminal: `curl http://localhost:8000/salud/jev?probar=true`. Nunca devuelve la clave.

## Poner Jev (nube) operativo
```bash
python3 scripts/jev_activar.py           # pide la clave (de console.typesafe.ai) sin mostrarla, la prueba y, si funciona, la guarda en el .env
docker compose up -d --force-recreate --no-deps api worker beat
```
Comprobar solo la clave que ya hay: `python3 scripts/jev_activar.py --probar`. La clave solo vive en el `.env`; no se sube a git ni se pega en ningún chat.
Antes de usarlo con datos reales: contrato de encargado de tratamiento y retención cero con TypeSafe (`docs/PENDIENTES.md`).

## jeff
Arranca solo con `docker compose up -d` (servicio `jeff`, solo en la red interna). Usa el modelo `juez` del perfil de hardware (o `JEFF_MODELO`). Si el panel dice «jeff: No arrancado»:
`docker compose up -d --build jeff`. Si dice que falta el modelo, `docker compose exec ollama ollama pull <modelo>`.

## Qué agentes lo usan
Tienen la herramienta `jev`: Director General, Prospector, Detector de Intención, Respuesta a Leads, Soporte N1, Escalado, Reseñas, Reactivación de cartera, Cobros, Control de Gastos, Jefe de Proyectos,
Calidad, No Conformidades, Cumplimiento, RGPD, Auditor del Cerebro, y los de Licitaciones, Marca y Mercado que ya la tenían. Selección (RR.HH.) **no** la tiene a propósito: trabaja sin servicios externos. Los agentes con datos de sensibilidad alta (Cobros, Control de Gastos…) usan **jeff**
automáticamente aunque pidan Jev. Para dársela a otro agente, se añade `"jev"` a su fila en `scripts/generar_fichas.py` y se regenera.


## El estado en el panel (Agentes → «Decisiones (JEV)»)

El estado normal es una **comprobación ligera**: ¿responde jeff y tiene su modelo?, ¿están la clave y la activación de Jev? No se hace ninguna pregunta real a los modelos, así que el chip sale al momento y no gasta tarjeta ni uso de la nube. Jev sale como «Configurado (sin probar)» hasta que se prueba.

**Comprobar ahora** hace la pregunta de prueba de verdad (sin datos de nadie) a jeff y a Jev y muestra cuánto tardan. Antes el estado hacía esa pregunta cada minuto: tardaba hasta 15 s (más con el modelo cargándose) y el chip no aparecía hasta que acababa.
