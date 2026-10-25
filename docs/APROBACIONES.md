# Aprobaciones

## Quién firma
**Todo lo que requiere aprobación lo firma Dirección, una sola persona**, sea cual sea el departamento. Es la política actual de `config/politicas_aprobacion.yaml`
(`simple` y `doble` piden `[direccion]`). Antes «doble» exigía además al responsable del departamento y una segunda persona; el motor sigue admitiendo varios firmantes
(se vuelve a exigir poniendo `[responsable_departamento, direccion]` en el nivel que se quiera) y sigue impidiendo que una misma persona firme dos veces.
Lo más delicado (nivel «doble») se firma solo en el panel, no por voz.

## Pantalla «Aprobaciones»
- **Pendientes:** lo que falta por decidir. Cada solicitud es una etiqueta; **al pulsarla se despliega toda la información** para verificarla antes de decidir:
  quién la propone, la acción y, según el caso, el correo completo (De, Para, Asunto, mensaje original y respuesta exacta) o todos los datos de la acción. Dentro están
  el comentario opcional y los botones **Aprobar** y **Rechazar**.
- **Historial:** al decidir, la solicitud sale de «Pendientes» y queda guardada para siempre en «Historial» (las aprobaciones no se pueden borrar). Cada una se despliega y muestra
  qué se pidió, **quién decidió, cuándo, por qué canal y con qué comentario**, y, si se aprobó, **lo que se ejecutó** (resultado). Se puede filtrar (todas, aprobadas, rechazadas), buscar y paginar.
- Dirección ve todas; el resto de personas, las de sus departamentos.

## Resumen y departamentos (panel)

- **Pestaña «Resumen»:** pendientes de tu firma, la que más tiempo lleva esperando, aprobadas y rechazadas del periodo (7, 30 o 90 días), tasa de aprobación, tiempo medio de decisión, reparto por departamento (clic en un departamento = sus pendientes), gráfico por día y agentes y acciones que más piden. Datos de `GET /aprobaciones/resumen?dias=30`.
- **Clasificar por departamento:** en **Pendientes** e **Historial** hay un filtro por departamento (con el número de solicitudes de cada uno). El historial lo filtra el servidor (`/aprobaciones/historial?departamento=…`).
- **Quién ve qué:** Dirección ve todos los departamentos; quien no lo es, solo los suyos (también en el resumen y en el filtro).
- **Una sola firma, la tuya:** toda aprobación, de cualquier departamento y nivel, la firma Dirección (`config/politicas_aprobacion.yaml`); la etiqueta es siempre «Requiere tu firma». Dirección puede firmar todo desde el panel. Lo delicado (pagos, facturas, contratos, precios, ofertas, licitaciones) no se firma por voz, solo en el panel con usuario identificado.
