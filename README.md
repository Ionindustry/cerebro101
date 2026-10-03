# Cerebro 101.cat

Sistema multiagente que gestiona 101.cat —instaladora de sistemas de seguridad y telecomunicaciones— con
**114 agentes en 13 departamentos y 60 subáreas**, todo alojado en el servidor de la empresa. Las personas
hablan con **Jarvis** (voz o panel); el **Director General** reparte cada petición al departamento, y los
agentes trabajan con modelos de IA locales, el ERP y las herramientas permitidas en su ficha. Nada sale de la
empresa sin aprobación humana.

Este repositorio es la implementación del documento de proyecto «Cerebro 101.cat — Propuesta de proyecto».

## Arranque rápido

```bash
cp .env.example .env        # rellena contraseñas, tokens de ERPNext y claves externas
./scripts/iniciar.sh        # levanta servicios, descarga modelos y arranca el panel
```

- Panel de Jarvis: http://localhost:3000
- API y documentación interactiva: http://localhost:8000/docs
- Registro de decisiones (Langfuse): http://localhost:3001

Para probar sin Keycloak: `CEREBRO_MODO=desarrollo` en `.env` y `PANEL_USUARIO_DESARROLLO=tu-nombre` en el panel.
La guía completa está en [docs/INSTALACION.md](docs/INSTALACION.md).

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `config/` | Fichas de los 114 agentes, departamentos, modelos, políticas de aprobación, herramientas, integraciones y parámetros del contador |
| `api/cerebro/` | Núcleo en Python: registro de agentes, políticas, router de modelos, grafo LangGraph, herramientas e integraciones directas (correo, calendario, contratación), aprobaciones, cotizador, API y tareas programadas |
| `api/tests/` | Pruebas del cotizador (cuadra con el Excel corregido), comparador, políticas y aprobaciones |
| `panel/` | Panel web de Jarvis (Next.js): conversación con voz, bandeja de aprobaciones y directorio de agentes |
| `servicios/voz/` | Voz a texto (Whisper) y texto a voz (Piper), en local |
| `servicios/agent-reach/` | Agent Reach aislado, solo lectura de contenido público |
| `db/` | Esquema de PostgreSQL + pgvector |
| `scripts/` | Arranque, descarga de modelos, carga de conocimiento y generador de fichas |
| `docs/` | Arquitectura, fases de desarrollo, seguridad, índice de agentes y pendientes |

## Cómo se añade o cambia un agente

Los agentes son configuración, no código. Edita su fila en `scripts/generar_fichas.py` (tareas, modelo,
herramientas, nivel de aprobación, horario, sensibilidad) y ejecuta:

```bash
python scripts/generar_fichas.py
```

Se regeneran `config/agentes/*.yaml`, `config/departamentos.yaml` y `docs/AGENTES.md`. Las pruebas comprueban
que todas las fichas son válidas.

## Pruebas

```bash
cd api && python -m pytest        # o: python -m unittest discover -s tests
```

## Estado

Versión 0.1: esqueleto completo y funcional de la Fase 1 (cimientos) con el motor de cotización y la red de
instaladores ya operativos. Lo que falta por conectar está en [docs/PENDIENTES.md](docs/PENDIENTES.md) y el
plan por fases en [docs/FASES.md](docs/FASES.md).
