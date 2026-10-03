# Seguridad y cumplimiento

## Aprobaciones

| Nivel | Ejemplos | Quién decide | Voz |
| --- | --- | --- | --- |
| Libre | Analizar, resumir, clasificar, borradores internos | El agente | — |
| Simple | Enviar a clientes, publicar, responder reseñas | Responsable del departamento | Sí |
| Doble | Pagos, facturas, contratos, precios, licitaciones | Responsable + dirección, dos personas distintas | No, solo panel |
| Prohibido | Borrar datos, cambiar permisos, firmar, validar documentos del ERP | Solo personas | — |

Cualquier acción con impacto externo pasa por la bandeja aunque la ficha del agente diga «libre».

## Datos y servicios externos

| Servicio | Sensibilidad máxima | Alternativa local |
| --- | --- | --- |
| Grok | Baja (temas públicos) | — |
| Jev | Media, solo con retención cero y anonimización (`USAR_JEV_NUBE=true`) | jeff o modelo local |
| Agent Reach | Baja, contenedor aislado, sin cookies personales | — |
| ScrapeGraphAI | Baja; respeta robots.txt y espacia las visitas | Funciona con modelo local |

Personas (RRHH) no usa ningún servicio externo.

## Integraciones

Correo, calendario y contratación pública se conectan directamente desde el Cerebro, sin plataformas
intermedias: todo el tráfico queda en el mismo registro de auditoría. Cada departamento usa su propia cuenta
técnica de correo y calendario, con acceso solo a su buzón. La lectura de correo es de solo lectura (no marca
mensajes como leídos), los borradores se guardan en la carpeta de borradores del departamento y el envío
requiere aprobación. Los mensajes comerciales llevan siempre el pie de baja.

Las ofertas de licitación no se presentan automáticamente: el Cerebro prepara el paquete y la lista de
comprobación, y una persona firma y presenta en la plataforma.

## Evidencias para ENS e ISO 27001

- Langfuse registra cada llamada a modelo y herramienta.
- La tabla `aprobaciones` guarda quién aprobó qué, cuándo y por qué canal.
- La tabla `registro_acciones` guarda cada acción ejecutada.
- Los agentes nunca generan evidencias de actividades que no han ocurrido.

## Red

Todos los puertos se publican solo en `127.0.0.1`. Para acceder desde la oficina, poner delante un proxy
inverso con HTTPS (por ejemplo Caddy o Traefik) y limitar el acceso a la red interna o a la VPN.
