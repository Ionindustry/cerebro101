# Decisiones e integraciones pendientes

| Tema | Qué falta | Dónde se conecta |
| --- | --- | --- |
| Tarjeta gráfica | Confirmar el modelo exacto («A200» no existe en el catálogo de NVIDIA) | `PERFIL_HARDWARE` en `.env` |
| Etiquetas de modelos | Verificar en ollama.com/library las de `config/modelos.yaml` | `config/modelos.yaml` |
| Jev / jeff | Jev funciona y ahora se anonimiza antes de salir (`docs/SEGURIDAD.md`). Falta: contrato de encargado de tratamiento y retención cero con TypeSafe, validar con vuestro asesor, ampliar `evaluacion/anonimizacion_*.yaml` con casos reales, ERPNext para la lista de entidades, y desplegar jeff (autoalojado) | `.env`, `herramientas/decision.py`, `anonimizacion.py` |
| Grok | Verificar modelo y formato de búsqueda en docs.x.ai | `herramientas/grok.py` |
| ERPNext | Instalación y tokens por departamento | `.env`, `herramientas/erpnext.py` |
| Correo y calendario | Servidor IMAP/SMTP, URL CalDAV y cuentas técnicas por departamento | `config/integraciones.yaml`, `.env` |
| Mayorista de telecom | Elegir mayorista e implementar sus 5 operaciones con su API | `herramientas/mayorista.py` |
| Plataformas de contratación | URL de sindicación vigentes, prefijos CPV de interés y prueba con un fichero real | `config/integraciones.yaml`, `herramientas/contratacion.py` |
| Tarifas de proveedores | Formato que ofrece cada proveedor (API, BMEcat, Excel) | agente Catálogo de Proveedores |
| Login | Hecho. Falta producción: HTTPS, `PANEL_URL`/`KEYCLOAK_URL_PUBLICA` reales y sus URI en el cliente de Keycloak; sesiones en memoria (se pierden al reiniciar el panel; valorar Redis si hay varias réplicas) | `panel/lib/sesion.js`, `config/keycloak/realm-cerebro.json` |
| OpenJarvis | Piloto como motor de la interfaz | Fase 1 |
| Registro CNMC | Inscripción como operador antes de vender telecom | Cumplimiento Telecom |
| Operaciones vinculadas | Precio de mercado y documentación de las compras a la distribuidora propia | asesor fiscal |
| Evidencias ISO 27001 | Decidir retención de trazas (licencia Enterprise de Langfuse o borrado periódico tras exportar); limitar las variables de `.env` que recibe cada servicio; programar copias y exportaciones mensuales y probar la restauración | `docs/SEGURIDAD.md`, `scripts/` |
