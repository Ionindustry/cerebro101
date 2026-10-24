# Decisiones e integraciones pendientes

| Tema | Qué falta | Dónde se conecta |
| --- | --- | --- |
| Tarjeta gráfica | Es una RTX A2000 (6 o 12 GB): perfiles `minima` y `mediana` creados y elegidos solos por `desplegar.sh`. Falta medirlos en la tarjeta real y decidir si 6/12 GB bastan (`docs/SERVIDOR_A2000.md`) | `config/modelos.yaml`, `despliegue/desplegar.sh` |
| Etiquetas de modelos | Verificadas contra registry.ollama.ai (excepto `prometheus2:7b`, que no existe y se ha quitado). Revisar al cambiar de modelo y mantener la tabla de tamaños de `api/tests/test_perfiles_modelos.py` | `config/modelos.yaml` |
| Jev / jeff | Jev funciona y ahora se anonimiza antes de salir (`docs/SEGURIDAD.md`). Falta: contrato de encargado de tratamiento y retención cero con TypeSafe, validar con vuestro asesor, ampliar `evaluacion/anonimizacion_*.yaml` con casos reales, ERPNext para la lista de entidades, y desplegar jeff (autoalojado) | `.env`, `herramientas/decision.py`, `anonimizacion.py` |
| Grok | Verificar modelo y formato de búsqueda en docs.x.ai | `herramientas/grok.py` |
| ERPNext | Instalado, con asistente completado (empresa «101.cat», EUR, ejercicio 2026, plan «Standard with Numbers») y blindado contra validar/borrar desde el Cerebro. Falta: sustituir el plan contable por el PGC con la gestoría, la razón social real (la actual es provisional), el IVA y las plantillas de impuestos, usuarios técnicos de Comercial, Operaciones y Telecom, datos reales y HTTPS si se expone | `erpnext/`, `scripts/erpnext_*.py`, `.env` |
| Frappe CRM | Instalado y comprobado en navegador (v1.87.0). Falta decidir si los agentes comerciales trabajan sobre sus documentos (CRM Lead/Deal) o siguen con el módulo CRM de ERPNext (Lead/Opportunity), y configurar etapas, orígenes y usuarios | `erpnext/Dockerfile.crm`, `scripts/erpnext_crm.sh`, `herramientas/erpnext.py` |
| Acceso al ERP/CRM por departamento | Hecho: política en el código, un rol propio por departamento y auditoría limpia. Falta que la empresa **revise la política** (`docs/POLITICA_ERP.md`, con preguntas por departamento), decidir si los borradores del ERP necesitan aprobación previa, instalar **HRMS** si RR. HH. debe funcionar (sus documentos no existen en este ERP) y decidir la visibilidad de leads y tratos del CRM (jerarquía de ventas) | `config/erp_acceso.yaml`, `scripts/erpnext_roles_cerebro.py`, `scripts/auditar_acceso_erp.py` |
| Correo | Servidor IMAP/SMTP, contraseñas y qué departamento usa cada buzón (`docs/CORREO.md`) | `config/buzones.yaml`, `secretos/buzones.env` |
| Calendario | URL CalDAV y cuentas técnicas por departamento | `config/integraciones.yaml`, `.env` |
| Mayorista de telecom | Elegir mayorista e implementar sus 5 operaciones con su API | `herramientas/mayorista.py` |
| Plataformas de contratación | URL de sindicación vigentes, prefijos CPV de interés y prueba con un fichero real | `config/integraciones.yaml`, `herramientas/contratacion.py` |
| Tarifas de proveedores | Formato que ofrece cada proveedor (API, BMEcat, Excel) | agente Catálogo de Proveedores |
| Login | Hecho. Falta producción: HTTPS, `PANEL_URL`/`KEYCLOAK_URL_PUBLICA` reales y sus URI en el cliente de Keycloak; las sesiones ya van a un Redis propio cifradas (falta probar el inicio de sesión completo con Keycloak real en el servidor) | `panel/lib/sesion.js`, `config/keycloak/realm-cerebro.json` |
| OpenJarvis | Piloto como motor de la interfaz | Fase 1 |
| Registro CNMC | Inscripción como operador antes de vender telecom | Cumplimiento Telecom |
| Operaciones vinculadas | Precio de mercado y documentación de las compras a la distribuidora propia | asesor fiscal |
| Evidencias ISO 27001 | Decidir retención de trazas (licencia Enterprise de Langfuse o borrado periódico tras exportar); limitar las variables de `.env` que recibe cada servicio; programar copias y exportaciones mensuales y probar la restauración | `docs/SEGURIDAD.md`, `scripts/` |
| Despliegue en servidor | Probar `despliegue/desplegar.sh instalar` de principio a fin en un servidor real (GPU, Let's Encrypt, `nvidia-container-toolkit`); DNS de los cuatro nombres; cortafuegos; programar la copia nocturna | `despliegue/`, `docs/DESPLIEGUE.md` |
