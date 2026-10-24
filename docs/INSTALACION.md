# Instalación

> Para un servidor real, con HTTPS, Keycloak en producción y todo en un solo comando, usad [DESPLIEGUE.md](DESPLIEGUE.md). Esta guía describe los pasos sueltos.

## Requisitos

- Servidor Linux con Docker y Docker Compose
- Tarjeta NVIDIA con controladores y NVIDIA Container Toolkit (`nvidia-smi` debe funcionar dentro de Docker)
- 64 GB de RAM y 2 TB de SSD recomendados

## Pasos

1. `cp .env.example .env` y rellenar contraseñas (`POSTGRES_PASSWORD` es del propietario de la base de datos y
   `CEREBRO_APP_PASSWORD` la del rol con el que trabaja la aplicación: usad dos distintas). Elegir `PERFIL_HARDWARE` según la memoria de la tarjeta.
2. Descargar las voces de Piper en catalán y castellano en `servicios/voz/voces/`
   (https://huggingface.co/rhasspy/piper-voices).
3. `./scripts/iniciar.sh`
4. Entrar en Keycloak (http://localhost:8080, usuario `admin` y `KEYCLOAK_ADMIN_PASSWORD`), realm `cerebro`: crear los
   usuarios, asignar roles (`direccion`, `responsable`, `usuario`) y grupos de departamento. El panel pide ese
   inicio de sesión al entrar (http://localhost:3000). Fuera de localhost, poner en `.env` `PANEL_URL` y
   `KEYCLOAK_URL_PUBLICA` con sus direcciones https y añadir `PANEL_URL/*` en las URI del cliente `cerebro-panel`.
5. Cargar documentos: `docker compose exec api python /app/scripts/cargar_conocimiento.py /datos/conocimiento`.
6. ERPNext (incluido en `erpnext/docker-compose.yml`, basado en frappe_docker):
   - En `.env`: `ERPNEXT_DB_ROOT_PASSWORD`, `ERPNEXT_ADMIN_PASSWORD` y `ERPNEXT_SITE` (por defecto `erp.101.cat`).
   - `docker compose -f erpnext/docker-compose.yml --env-file .env up -d` (la primera vez tarda unos minutos:
     crea el sitio e instala ERPNext; necesita unos 6 GB de disco para las imágenes y 2-4 GB de memoria).
   - Entrad en http://localhost:8081 (usuario `Administrator`, contraseña `ERPNEXT_ADMIN_PASSWORD`) y completad el
     asistente inicial (empresa, plan contable, ejercicio fiscal), o hacedlo por línea de comandos con
     `bench --site <sitio> execute frappe.desk.page.setup_wizard.setup_wizard.setup_complete --kwargs '{"args": {...}}'`.
     ERPNext no trae el Plan General Contable español: se usó «Standard with Numbers»; pedid a la gestoría el plan
     que corresponda. Sin el asistente no se pueden crear facturas ni empleados.
   - Un usuario técnico por departamento, con solo los roles de su área, y su clave en `.env`:
     `python scripts/erpnext_usuario_tecnico.py --departamento finanzas --roles "Accounts User"`
     (para Dirección, que usa el Cerebro para leer clientes, proveedores y empleados al anonimizar:
     `--departamento direccion --roles "Sales User,Purchase User,HR User"`). Reiniciad la API después.
   - **Cada departamento cuyos agentes consultan el ERP necesita su propio usuario técnico** (`ERPNEXT_TOKEN_<DEPARTAMENTO>`); sin él, el agente
     responde con un error que lo dice. Con las fichas actuales usan el ERP: areas, atencion, comercial, direccion, finanzas, legal, licitaciones,
     marketing, operaciones, personas, tecnologia y telecom. Por ejemplo, para que Jarvis pueda consultar clientes con los agentes comerciales:
     `python scripts/erpnext_usuario_tecnico.py --departamento comercial --roles "Sales User"` y después
     `docker compose up -d --force-recreate --no-deps api worker beat` (la API solo lee las claves al arrancar). Dale a cada uno solo los roles que
     necesite; si un departamento no tiene clave propia se usa `ERPNEXT_TOKEN` (clave general, déjala vacía o de solo lectura).
   - `python scripts/erpnext_blindar.py` (una vez, y reiniciar `backend queue-short queue-long`): impide que los usuarios
     `cerebro.*` validen, cancelen o borren documentos, aunque su rol lo permita (el rol «Accounts User» puede validar
     facturas). Segunda barrera dentro del propio ERP, además de la política y del conector.
   - **Frappe CRM** (opcional, interfaz de CRM moderna sobre el mismo ERPNext): `./scripts/erpnext_crm.sh instalar`. Construye la imagen
     `cerebro-erpnext-crm` (la oficial + CRM v1.87.0), la activa, instala la app en el sitio y migra; antes hace una copia de la base. Queda en
     `http://localhost:8081/crm` (misma cuenta de ERPNext). Necesita acceso a github.com, npm y PyPI durante la construcción (10-20 min, unos
     5 GB de disco). No uses la rama `main` de CRM: es la línea 2.0 en desarrollo y no compila con Frappe 16.36. Los datos del CRM (CRM Lead,
     CRM Deal…) son documentos distintos de los Lead y Opportunity del módulo CRM de ERPNext que usan hoy los agentes: no se sincronizan solos.
   - La API del Cerebro lo ve como `http://erpnext:8080` (`ERPNEXT_URL`); el navegador, en `localhost:8081`.
7. Integraciones: en `config/integraciones.yaml`, poner el servidor IMAP/SMTP y la URL CalDAV del servidor de
   correo propio, y las URL de sindicación (ATOM) de las plataformas de contratación. Las cuentas van en `.env`
   (`CORREO_*`, `CALENDARIO_*`). Se recomienda una cuenta técnica por departamento, con acceso solo a su buzón.

## Comprobación

```bash
curl http://localhost:8000/salud
# {"estado":"ok","agentes":114,"departamentos":13,...}
```
