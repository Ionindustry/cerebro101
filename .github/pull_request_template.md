## Qué cambia
<!-- Una o dos frases. Un PR = un cambio; si hace dos cosas, mejor dos PR. -->

## Por qué
<!-- El problema o la petición que lo motiva. -->

## Cómo se ha probado
<!-- Pruebas automáticas, pruebas a mano, capturas si hay pantallas. Di también lo que NO has podido probar. -->

## Riesgos y despliegue
- [ ] Cambia cómo se aprueban o se envían cosas (aprobaciones, correo, ERP/CRM)
- [ ] Añade tablas, variables de entorno o servicios nuevos (indicar cuáles y cómo se aplican)
- [ ] Toca permisos, claves o accesos
- [ ] Necesita reconstruir contenedores (`docker compose up -d --build …`)

## Antes de fusionar
- [ ] CI en verde
- [ ] Sin secretos ni datos personales en el cambio
- [ ] Documentación actualizada si cambia algo que alguien tiene que saber (`docs/`)
