# Aprobaciones

## Quién firma
**Todo lo que requiere aprobación lo firma Dirección, una sola persona**, sea cual sea el departamento. Es la política actual de `config/politicas_aprobacion.yaml`
(`simple` y `doble` piden `[direccion]`). Antes «doble» exigía además al responsable del departamento y una segunda persona; el motor sigue admitiendo varios firmantes
(se vuelve a exigir poniendo `[responsable_departamento, direccion]` en el nivel que se quiera) y sigue impidiendo que una misma persona firme dos veces.
Todo, también lo más delicado (nivel «doble»), se puede firmar en el panel o por voz (`voz_permitida` en `niveles`).

## Qué necesita firma
La firma depende de **la operación**, no del agente (`supervision` en `config/politicas_aprobacion.yaml`):
- **Estándar:** lecturas, consultas, borradores, propuestas, cálculos… No piden firma, se ejecutan.
- **Supervisada:** lo que sale de la empresa o tiene impacto externo (enviar correo, crear cita…). Pide la firma de Dirección.
- **Reservada:** compromisos económicos o legales (`presentar_licitacion`, `pedido_proveedor`, `mayorista.alta`…). Firma individual (no se agrupa en un objetivo); también por voz.

## Firmar un objetivo, no cada subtarea
Si una petición genera **varias acciones supervisadas**, el sistema crea **una sola solicitud** con el objetivo y la lista completa de acciones: se revisa y se firma una vez,
y se ejecutan todas. Las reservadas siguen siendo individuales. Rechazar la solicitud rechaza todo el objetivo.

## Pantalla «Aprobaciones»
- **Pendientes:** lo que falta por decidir. Cada solicitud es una etiqueta; **al pulsarla se despliega toda la información** para verificarla antes de decidir:
  quién la propone, la acción y, según el caso, el correo completo (De, Para, Asunto, mensaje original y respuesta exacta) o todos los datos de la acción. Dentro están
  el comentario opcional y los botones **Aprobar** y **Rechazar**.
- **Historial:** al decidir, la solicitud sale de «Pendientes» y queda guardada para siempre en «Historial» (las aprobaciones no se pueden borrar). Cada una se despliega y muestra
  qué se pidió, **quién decidió, cuándo, por qué canal y con qué comentario**, y, si se aprobó, **lo que se ejecutó** (resultado). Se puede filtrar (todas, aprobadas, rechazadas), buscar y paginar.
- Dirección ve todas; el resto de personas, las de sus departamentos.
