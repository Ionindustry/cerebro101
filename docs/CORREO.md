# Correo corporativo para los agentes

Los agentes pueden **leer** los buzones de la empresa (administracion@, rrhh@, comercial@…), **preparar borradores** y
**contestar o enviar** correos. Lo que sale de la empresa lo aprueba siempre una persona.

## Qué puede hacer cada cosa

| Operación | Qué hace | ¿Necesita aprobación? |
|---|---|---|
| `listar_buzones` | Dice qué buzones puede usar el departamento del agente | No |
| `leer_bandeja` | Lee los correos (no los marca como leídos) | No |
| `preparar_borrador` | Guarda un borrador en la carpeta «Borradores» del buzón (una persona lo ve en su cliente de correo) | No |
| `responder` | Contesta a un mensaje recibido: va al remitente, con «Re:» y en el mismo hilo | **Sí** |
| `enviar` | Envía un correo nuevo | **Sí** |

En la pantalla **Aprobaciones** de Jarvis, quien aprueba ve **de qué buzón sale, para quién, el asunto, el texto exacto
que se enviará** y, si es una respuesta, el mensaje original. Aprobar es lo único que envía el correo.

## Qué impide que un agente haga algo indebido

- **Cada buzón tiene sus departamentos** (`config/buzones.yaml`). Un agente de Personas no puede abrir
  administracion@ aunque lo pida: lo comprueba el sistema con el departamento de la ficha, no el modelo.
- **Aprobación obligatoria** de `responder` y `enviar`, también para agentes de autonomía «libre» y se llame como se llame la acción.
- **Sin bucles ni spam:** no se contesta a mensajes automáticos (boletines, no-reply, respuestas automáticas, listas),
  ni a las direcciones de la propia empresa, ni dos veces al mismo mensaje (se marca «contestado» en el buzón).
- **Límites:** 5 destinatarios y 6000 caracteres por mensaje (configurable); se rechazan direcciones inválidas e intentos de cabeceras inyectadas.
- **El correo recibido es información, no órdenes:** la lectura avisa al agente de que no obedezca instrucciones que vengan dentro de un correo.
- **Comerciales:** `comercial: true` añade siempre el pie de baja (LSSI).
- **Constancia:** cada envío queda en el registro de acciones, ligado a la aprobación y a quién la firmó.
- **Contraseñas:** solo en `secretos/buzones.env` (fuera de git, montado de solo lectura únicamente en la API y el worker). Nunca en el `.env`, ni en la configuración, ni se muestran al modelo.

## Poner en marcha un buzón (paso a paso)

1. **Crea el buzón en tu servidor de correo** (si no existe) y apunta su contraseña. Lo ideal es una contraseña propia y larga para el Cerebro.
2. **Revisa el servidor** en `config/buzones.yaml` (`servidor:`): `host`, `puerto` y `seguridad` de IMAP y SMTP. Por defecto `mail.101.cat`
   (IMAP 993 con SSL, SMTP 587 con STARTTLS). También el nombre de las carpetas (`Borradores`/`Drafts`, `Enviados`/`Sent`) según tu proveedor.
3. **Da de alta el buzón** (en Ubuntu/WSL, dentro de la carpeta del proyecto). La contraseña se pide sin mostrarla:

   ```bash
   python3 scripts/buzon_alta.py --id rrhh --direccion rrhh@101.cat --departamentos personas
   ```

   Si el buzón ya está en `config/buzones.yaml` (los cinco de la empresa ya están), basta con la contraseña:
   `python3 scripts/buzon_alta.py --id rrhh`.
4. **Comprueba que conecta** (no lee ni envía nada):

   ```bash
   docker compose exec api python /app/scripts/probar_buzones.py
   ```

   Debe decir `IMAP ok · SMTP ok` en cada buzón con contraseña. No hace falta reiniciar: la API relee `secretos/buzones.env` cuando cambia.
   Los cambios en `config/buzones.yaml` sí necesitan `docker compose restart api worker`.
5. **Prueba con un agente:** pídele a Jarvis, por ejemplo, «lee los correos sin leer de RR.HH.» y después «contesta al primero diciendo que lo hemos recibido»;
   verás la respuesta en **Aprobaciones** antes de que salga.

## Qué proveedor de correo tienes

- **Servidor propio** (`mail.101.cat`, Dovecot/Postfix, Mailcow…): funciona tal cual con usuario y contraseña (usa «contraseña de aplicación» si tu servidor la ofrece).
- **Google Workspace:** IMAP `imap.gmail.com:993` y SMTP `smtp.gmail.com:587`; hace falta activar la verificación en dos pasos y crear una **contraseña de aplicación** por buzón.
- **Microsoft 365 / Outlook:** Microsoft ha desactivado el acceso IMAP/SMTP con contraseña en la mayoría de los inquilinos; haría falta OAuth2, que **esta versión no incluye**. Díselo a quien te lo configure antes de contratarlo.

## Pendiente de decidir con la empresa

- Buzones: administracion@ (Dirección, Operaciones y Telecom), facturacion@ (Finanzas), rrhh@ (Personas), soporte@ (Atención) y concursos@ (Licitaciones).
  **Comercial no tiene buzón** y sus agentes de correo (respuesta-leads, canal-email, gestor-cuentas) no podrán usarlo hasta asignarle uno
  (p. ej. añadir `comercial` a los departamentos de soporte@, o crear comercial@). Los agentes de Licitaciones no tienen aún la herramienta `correo` en su ficha.
- ¿Qué buzones empiezan en modo «solo leer y preparar borradores»? Mientras no pongas su contraseña, un buzón no hace nada.
- ¿Firma de cada buzón (campo `firma`) y texto del pie comercial? Los revisa la persona responsable de protección de datos.
- Los agentes que atienden estos buzones y su frecuencia de revisión (tareas programadas) se ajustan en sus fichas.
