# EET Europarts: precio y stock en tiempo real

EET (proveedor) ofrece un intercambio de documentos XML por HTTPS (`developer.eetgroup.com`, documento «XML with EET Group»). Esto integra **la consulta de precio y stock** (PA Request / PA Response). Es **solo lectura**: no hace pedidos.

## Qué hace
La herramienta `eet` (operación `consultar`) pregunta a EET, por una o varias referencias (hasta 50), el **precio de compra, el stock** y, en la versión ampliada, el stock por tipo (local, entrante, remoto) con su plazo, el EAN y una descripción corta. La usa el agente **Catálogo de Proveedores**. Los precios son costes de compra: **confidencial**, así que tras usarla el agente solo trabaja con modelos locales.
- EET da el precio en **céntimos**; el código lo pasa a euros. El documento de EET **no dice la moneda**: es la de tu cuenta (`moneda` en `config/eet.yaml`; compruébalo con EET).
- Una referencia que EET no conoce sale como «no existe en EET».
- EET pide usarla **a demanda**, no en bucle: para volcados continuos ofrecen exportaciones aparte (se pueden cargar como tarifa: `./scripts/tarifa_subir.sh eet <fichero>`).

## Qué necesitas de EET (te lo da su comercial)
Número de cliente, **AuthCode**, identificador de empresa **CId** (2 letras, la sociedad EET con la que trabajas) y la **dirección https** a la que enviar. Pídeles también la moneda de los precios.

## Cómo se activa
1. En tu servidor, crea `secretos/eet.env` con dos líneas (sin comillas; **no las pegues en el chat**): `EET_CLIENTE=...` y `EET_CLAVE=...`.
2. Rellena en `config/eet.yaml`: `url`, `hosts` (el dominio de esa dirección), `cid` y `moneda`. Mientras `url` esté vacía la integración está apagada y la herramienta lo dice.
3. Actualiza y reinicia la API y el worker.

## Seguridad
Solo https y solo el dominio de `hosts`; sin redirecciones; el XML se lee sin DTD ni entidades; la respuesta tiene tamaño máximo; las referencias se validan antes de ir dentro del XML; la clave no aparece en los mensajes de error ni en los registros.

## Lo que NO está hecho (y por qué)
- **Pedidos a EET (Order Request).** Sale dinero de la empresa: haría falta borrador, firma de Dirección y el control de «pedido ya registrado» (MsgID). Es otra fase.
- **Confirmaciones de pedido, avisos de envío, facturas y abonos.** EET **envía** esos XML a una dirección pública tuya (o por email/FTP). Tu instalación es local y no es accesible desde fuera: antes hay que decidir cómo recibirlos (email o FTP son lo más sencillo).
- **No probado contra EET real**: solo con un EET simulado, siguiendo el documento. Hará falta una primera consulta real con tus credenciales para confirmar la dirección, la moneda y los formatos.

## Proveedor en el ERP
«EET Europarts» (distribuidor, EUR) está en `config/tarifas_auto.yaml`. Se **da de alta en el ERP cuando firmas la primera tarifa** suya (el proveedor y sus artículos se crean en esa carga). Si no tienes fichero de tarifa, dímelo y se prepara un alta directa.
