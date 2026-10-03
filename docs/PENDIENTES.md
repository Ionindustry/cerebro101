# Decisiones e integraciones pendientes

| Tema | Qué falta | Dónde se conecta |
| --- | --- | --- |
| Tarjeta gráfica | Confirmar el modelo exacto («A200» no existe en el catálogo de NVIDIA) | `PERFIL_HARDWARE` en `.env` |
| Etiquetas de modelos | Verificar en ollama.com/library las de `config/modelos.yaml` | `config/modelos.yaml` |
| Jev / jeff | Conector hecho (`POST /v1/systemone`). Falta `JEV_API_KEY` y `USAR_JEV_NUBE=true`, probarlo contra la API real y desplegar jeff (autoalojado) en la red `cerebro` | `.env`, `herramientas/decision.py` |
| Grok | Verificar modelo y formato de búsqueda en docs.x.ai | `herramientas/grok.py` |
| ERPNext | Instalación y tokens por departamento | `.env`, `herramientas/erpnext.py` |
| Correo y calendario | Servidor IMAP/SMTP, URL CalDAV y cuentas técnicas por departamento | `config/integraciones.yaml`, `.env` |
| Mayorista de telecom | Elegir mayorista e implementar sus 5 operaciones con su API | `herramientas/mayorista.py` |
| Plataformas de contratación | URL de sindicación vigentes, prefijos CPV de interés y prueba con un fichero real | `config/integraciones.yaml`, `herramientas/contratacion.py` |
| Tarifas de proveedores | Formato que ofrece cada proveedor (API, BMEcat, Excel) | agente Catálogo de Proveedores |
| Login | Keycloak en el panel (OIDC) | `panel/app/cerebro/[...ruta]/route.js` |
| OpenJarvis | Piloto como motor de la interfaz | Fase 1 |
| Registro CNMC | Inscripción como operador antes de vender telecom | Cumplimiento Telecom |
| Operaciones vinculadas | Precio de mercado y documentación de las compras a la distribuidora propia | asesor fiscal |
