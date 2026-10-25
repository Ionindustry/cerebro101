# Pestaña «Oficina» de Jarvis

Una vista isométrica de la empresa: cada departamento es una sala con sus mesas, y cada agente es una cápsula negra en su puesto
(estilo gris y negro con coral como señal, como la imagen de referencia). Está en el menú de Jarvis, entre «Jarvis» y «Aprobaciones».

## Qué se ve
Una escena 3D (three.js) con luz y sombras suaves, grises claros, muros bajos, árboles low-poly y los agentes como cápsulas negras de pie delante de su mesa. Se centra sola
en la pantalla al entrar.
- **Coral y movimiento:** el agente está trabajando (su pantalla se enciende en coral, la cápsula «respira» y le flota un punto coral).
- **Ámbar con anillo:** ha propuesto algo y espera una aprobación.
- **Negro quieto y pantalla apagada:** en reposo. El director de cada sala lleva una banda blanca y ocupa el primer puesto.
- **Mover la cámara:** arrastra para girar un poco y desplazar; rueda del ratón para acercar. **Esc** o «← Toda la oficina» vuelven a la vista general.
- **Pasar el ratón** por un agente: nombre, área, estado y qué hace ahora.
- **Pulsar una sala** (o su etiqueta): la cámara vuela hasta ella y la lista lateral muestra sus agentes.
- **Pulsar un agente — entrar en él:** la cámara se acerca a su puesto y se abre su ficha con: estado y qué hace ahora, qué hace en la empresa, herramientas y nivel de aprobación,
  lo que **espera tu aprobación** (con destinatario y asunto, y enlace a Aprobaciones), los **pasos recientes** (línea de tiempo: «Pensando», «Usando correo · leer_adjunto»,
  «Propone enviar_correo y espera aprobación», «Ejecuta … (aprobada)») y las **acciones registradas**. Se refresca cada 2,5 s mientras está abierta.
- «Lista» muestra u oculta el panel con todos los departamentos y la última actividad. Con lector de pantalla esa lista siempre está disponible: es la versión en texto de la escena.
- «Ver demostración» pone estados de ejemplo (marcados como tales) para ver cómo se anima; no son datos reales.
- Si el navegador no admite WebGL, se avisa y queda la lista.

## De dónde salen los datos
- La API (`GET /oficina`) junta las fichas de agentes, la tabla `actividad_agentes` (qué hace cada agente ahora), las aprobaciones pendientes y las últimas acciones del registro.
  `GET /oficina/agentes/{id}` da la ficha de un agente y, si es de tu departamento, sus pasos recientes (`actividad_eventos`, los últimos ~40 por agente), acciones y aprobaciones pendientes.
- Cada vez que un agente trabaja (`grafo/nodos.py`), marca «trabajando» con la herramienta que usa y, al terminar, vuelve a reposo y guarda cuál fue su última tarea. También lo hacen
  el Director General al repartir una petición y el director del departamento al elegir agente. Las tareas programadas pasan por el mismo camino.
- No se guarda el texto de lo que pide la persona (puede llevar datos personales): solo qué herramienta usa el agente.
- Si la base de datos falla, el trabajo de los agentes no se ve afectado (la actividad es solo información) y la oficina se muestra en reposo.
- Un «trabajando» sin novedades durante 10 minutos se muestra como reposo (agente colgado o contenedor reiniciado).
- Se refresca cada 4 segundos.

## Privacidad
Quien no es de dirección ve el **estado** y la ficha pública de todos los agentes, pero el **detalle** de lo que hacen (herramienta, pasos, acciones, aprobaciones pendientes) solo de los de sus propios departamentos.

## Ponerlo en marcha
`git pull` y `docker compose up -d --build api worker beat panel`. La tabla `actividad_agentes` la crea el servicio «migraciones» al arrancar.
