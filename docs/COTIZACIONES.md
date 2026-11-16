# Cotizaciones a proveedores

Cuando una referencia no tiene precio en las tarifas cargadas, se le pide **cotización** a un proveedor que la distribuya. Pantalla: **Jarvis → Cotizaciones** (Dirección y Licitaciones; solo Dirección envía).

## Reglas (decididas por Dirección)
1. **El correo lo redacta siempre el sistema**, con la plantilla de `config/cotizaciones.yaml`. No lo escribe un modelo ni una persona, y no se edita.
2. **Lleva solo tres datos: referencia, cantidad y plazo de entrega** (en días o con fecha límite). Nunca el cliente, la licitación, la marca, precios nuestros ni nada más. La licitación y la partida de las que viene solo se guardan en Jarvis.
3. **Dos modos, a elegir en cada caso:**
   - **«La envía el sistema cuando Dirección confirma»:** al pulsar «Enviar al proveedor» y confirmar, sale desde el buzón del departamento (`buzon_departamento` en la configuración; hoy `administracion@`). Queda constancia a nombre de quien firmó. Si el envío falla, sigue en borrador y se puede reintentar.
   - **«La mando yo»:** el sistema deja el correo redactado; se abre en tu programa de correo o se copia, y después se pulsa «Ya lo he enviado».
4. **Se guarda en los dos sitios:** en Jarvis (tabla `cotizaciones`) y, como **borrador**, en ERPNext como «Petición de cotización» (*Request for Quotation*). Para esto último el artículo y el proveedor tienen que existir en el ERP (no se crean desde aquí); si no, la pantalla dice por qué y la cotización sigue válida en Jarvis.

## Flujo
- **Partida sin coste → «Pedir cotización»** (Equipos y coste real): abre la pantalla con la referencia (la palabra con letras y números más larga del producto), la cantidad y la partida ya puestas.
- **Proveedor:** «¿Quién distribuye esta marca?» propone los proveedores de **Precios → Proveedores y marcas**. Su correo está en «Contactos de proveedores» (Dirección). No se aceptan direcciones de la propia empresa.
- **Respuesta:** se registra el precio unitario, la moneda (EUR, USD o GBP), el plazo y la validez. Desde ese momento la partida usa ese coste, marcado como **«cotización de proveedor»**, en euros con el mismo cálculo de siempre (cambio y canal «distribuidor»). Una cotización caducada deja de usarse.
- **Estados:** borrador → enviada → respondida (o cancelada). Una cotización enviada que lleva más de `dias_sin_respuesta` (3) días sin respuesta sale en **«Hoy»**; las de modo «enviar» que esperan confirmación, también (solo para Dirección).

## Lo que NO hace
- No elige proveedor ni envía nada sin que una persona lo decida.
- No negocia ni acepta ofertas: el precio de venta lo sigue fijando Dirección.
- No envía las cotizaciones ni los contactos a Claude ni a ChatGPT.

## Desde «Preparar la oferta»: cotizar de una vez lo que no tiene precio

En la tarjeta «Equipos y coste real» de la oferta, si hay partidas **sin coste en las tarifas**, sale el bloque «Preparar las cotizaciones». Elige el plazo de entrega (días) y el modo, y el sistema:

1. coge cada partida sin coste, con cantidad y sin otra cotización abierta;
2. saca la marca del producto (entre las de tus proveedores) y busca quién la distribuye (*Proveedores y marcas*);
3. crea el **borrador** con el proveedor que más artículos de esa marca tiene y correo de contacto; el correo lo redacta el sistema (solo referencia, cantidad y plazo).

No envía nada: lo revisas y lo envías desde Cotizaciones. Lo que no se puede preparar (sin cantidad, marca no reconocida, sin proveedor o sin su correo) se lista con el motivo.

## Productos que nombra el pliego

La tabla de equivalencias saca del texto del pliego los productos que **nombra** (marca y modelo, y si dice «o equivalente»): lo hace el código, sin modelo de IA, con las marcas conocidas (las de tus tarifas, `config/marcas_alias.yaml` y el ranking de fabricantes), y cada una lleva su cita y su página. Se buscan las fichas de esos modelos y sus datos fijan el mínimo que deben igualar o superar los equivalentes.
