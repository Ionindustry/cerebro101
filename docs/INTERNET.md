# Internet, fecha y hora para Jarvis

## Qué hay

- **Fecha y hora:** cada agente recibe en sus instrucciones la fecha y la hora actuales (zona `TZ`, por defecto Europa/Madrid), con el día de la semana. Los modelos no tienen reloj: sin esto se las inventaban.
- **Asistente general** (Dirección): responde cualquier duda general o de actualidad. El Director General le manda las preguntas que no son del negocio. Usa la herramienta `web`.
- **Herramienta `web`:** `buscar` (web o noticias, con periodo opcional) y `leer` (el texto de una página pública). Solo la usan agentes de sensibilidad **baja**.
- **Buscador propio:** el servicio `searxng` de `docker-compose.yml` (SearXNG). Sin claves ni cuentas; solo se alcanza desde la red interna; su configuración está en `servicios/searxng/settings.yml`.

## Qué no puede pasar (lo comprueba el código)

- **Una búsqueda no lleva datos de la empresa:** si la consulta contiene nombres de clientes, proveedores o empleados del ERP, DNI/NIE, CIF, IBAN, tarjetas, correos o teléfonos, no se hace y se le dice al agente que la reformule. Si el ERP no responde y no se puede comprobar, tampoco se busca.
- **Leer una página no llega a servicios internos:** solo http/https por los puertos 80 y 443; se rechaza todo lo que resuelva a una IP privada, de bucle o de enlace local (ERPNext, base de datos, Ollama…). Se conecta a la IP ya comprobada, y cada redirección se vuelve a comprobar. Solo texto, con tope de tamaño y de tiempo, y respetando `robots.txt`.
- Las consultas externas siguen siendo lecturas: no hay nada que aprobar. Lo que el agente proponga hacer con la información (enviar, publicar…) sigue pasando por la bandeja de aprobaciones.

## Puesta en marcha

```bash
git pull origin main
docker compose up -d --build api worker beat
docker compose up -d searxng
```

Para probarlo, en Jarvis: «¿qué día es hoy?» y «¿qué novedades hay sobre la normativa de videovigilancia?». Si el buscador no responde: `docker compose logs --tail 30 searxng`.

## Qué falta

- El servicio `searxng` no se ha podido arrancar en el entorno de desarrollo (sin Docker): la configuración sigue la imagen oficial, pero la primera ejecución real puede pedir un ajuste.
- Los buscadores públicos pueden limitar o bloquear las consultas desde un servidor (CAPTCHA); si pasa, SearXNG devuelve menos resultados. La alternativa es un buscador de pago (Brave) o Grok, ya integrado.
- La calidad de las respuestas con internet depende del modelo local; para consultas complejas se puede conectar Claude o ChatGPT (`docs/MODELOS_EXTERNOS.md`).
