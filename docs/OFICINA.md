# Pestaña «Oficina» de Jarvis

Una vista isométrica de la empresa: cada departamento es una sala con sus mesas, y cada agente es una cápsula negra en su puesto
(estilo gris y negro con coral como señal, como la imagen de referencia). Está en el menú de Jarvis, entre «Jarvis» y «Aprobaciones».

## Qué se ve
- **Coral y movimiento:** el agente está trabajando (su pantalla se enciende en coral y la cápsula «respira»).
- **Ámbar con anillo:** el agente ha propuesto algo y espera una aprobación (Aprobaciones).
- **Negro quieto y pantalla apagada:** en reposo.
- El director de cada sala lleva una banda blanca y se sienta en el primer puesto.
- Pasando el ratón por un agente: su nombre, su área, su estado y qué está haciendo («Usando correo · leer_adjunto», «Pensando»…).
- Pulsando una sala (o su etiqueta) la vista se acerca y la lista lateral muestra sus agentes; «← Toda la oficina» vuelve a la vista general.
- «Lista» muestra u oculta el panel con todos los departamentos y la última actividad. Con lector de pantalla, esa lista siempre está disponible: es la versión en texto de la escena.
- «Ver demostración» pone estados de ejemplo (marcados como tales) para ver cómo se anima; no son datos reales.

## De dónde salen los datos
- La API (`GET /oficina`) junta las fichas de agentes, la tabla `actividad_agentes` (qué hace cada agente ahora), las aprobaciones pendientes y las últimas acciones del registro.
- Cada vez que un agente trabaja (`grafo/nodos.py`), marca «trabajando» con la herramienta que usa y, al terminar, vuelve a reposo y guarda cuál fue su última tarea. También lo hacen
  el Director General al repartir una petición y el director del departamento al elegir agente. Las tareas programadas pasan por el mismo camino.
- No se guarda el texto de lo que pide la persona (puede llevar datos personales): solo qué herramienta usa el agente.
- Si la base de datos falla, el trabajo de los agentes no se ve afectado (la actividad es solo información) y la oficina se muestra en reposo.
- Un «trabajando» sin novedades durante 10 minutos se muestra como reposo (agente colgado o contenedor reiniciado).
- Se refresca cada 4 segundos.

## Privacidad
Quien no es de dirección ve el **estado** de todos los agentes, pero el **detalle** de lo que hacen (herramienta, última tarea, últimas acciones) solo de los de sus propios departamentos.

## Ponerlo en marcha
`git pull` y `docker compose up -d --build api worker beat panel`. La tabla `actividad_agentes` la crea el servicio «migraciones» al arrancar.
