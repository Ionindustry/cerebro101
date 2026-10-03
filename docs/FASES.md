# Plan de desarrollo por fases

Cada fase dura unas 4 semanas y solo empieza si la anterior cumple su criterio de paso.

## Fase 1 — Cimientos

- [x] Estructura del proyecto, docker-compose y esquema de base de datos
- [x] Registro de 114 agentes como configuración validada
- [x] Políticas de aprobación y de sensibilidad de datos en código
- [x] Grafo de orquestación: Director General → departamento → agente → aprobaciones
- [x] Panel de Jarvis con conversación, bandeja de aprobaciones y directorio de agentes
- [x] Motor de cotización (cuadra con el contador corregido) y comparador de instaladores
- [x] Conectores directos de correo (IMAP/SMTP), calendario (CalDAV) y datos abiertos de contratación, sin n8n
- [ ] Configurar el servidor de correo y las cuentas técnicas por departamento
- [ ] Confirmar el modelo de tarjeta gráfica y fijar `PERFIL_HARDWARE`
- [ ] Verificar las etiquetas exactas de los modelos en Ollama y descargarlos
- [x] Login del panel con Keycloak (OIDC, código + PKCE) en lugar de las cabeceras de desarrollo
- [ ] Cargar la base de conocimiento con los documentos actuales de la empresa
- [ ] Piloto de OpenJarvis como motor de la interfaz (validar multiusuario)
- [ ] Batería de 50 preguntas reales para medir la calidad de enrutado y respuestas

**Criterio de paso:** el Cerebro responde preguntas sobre la empresa con fuentes correctas y enruta bien al
menos el 90 % de la batería de preguntas.

## Fase 2 — Departamentos núcleo

- [ ] Instalar ERPNext (frappe_docker), crear usuarios técnicos por departamento y conectar la API
- [ ] Finanzas: facturas y asientos en borrador, conciliación, previsión de caja
- [ ] Comercial: CRM en ERPNext, Respuesta a Leads, Propuestas con el cotizador
- [ ] Licitaciones: Rastreador con las plataformas de contratación, Viabilidad, matriz de cumplimiento
- [ ] Telecom: elegir mayorista, conector de cobertura, alta y consumos; inscripción en la CNMC
- [ ] Atención al Cliente: Soporte Nivel 1 y Escalado
- [ ] Importación de tarifas de Visiotech, ETT, Asecur, Saltoki y la distribuidora propia

**Criterio de paso:** un mes de facturación, cobros, soporte y rastreo de concursos con el Cerebro sin
incidencias graves.

## Fase 3 — Crecimiento

- [ ] Marketing: Radar con Grok, Analista de Noticias y de Competencia (ScrapeGraphAI, Agent Reach)
- [ ] Proceso de captación multicanal con revisión legal de cada campaña
- [ ] Operaciones: red de instaladores (captación, acuerdos, comparador en producción)
- [ ] Áreas de Servicio: catálogo de paquetes por área y Previsión de Demanda
- [ ] Personas
- [ ] Voz de Jarvis (Whisper y Piper) en producción

**Criterio de paso:** calendario editorial, campañas y proyectos funcionando dentro del Cerebro.

## Fase 4 — Control y madurez

- [ ] Legal: sistema integrado ENS / ISO 27001 / 9001 / 14001 con evidencias desde Langfuse y el ERP
- [ ] Tecnología: monitorización, copias y alertas de seguridad
- [ ] Auditor del Cerebro con muestreo de respuestas por agente
- [ ] Panel de KPI completo y resumen diario de dirección automático

**Criterio de paso:** el resumen diario se genera solo y el Auditor reporta una tasa de error aceptable.
