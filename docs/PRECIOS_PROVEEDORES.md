# Tarifas de proveedores, precios de venta y propuesta de precios (plan)

Lo que Dirección ha pedido y cómo se construye, por pasos (cada uno, su PR). **Decisiones ya tomadas:**

- **Dos tipos de proveedor para el mismo producto:** el **fabricante** (precio de fábrica, p. ej. EXW; pide logística, aranceles y cambio) y el **distribuidor** (precio local con stock). El mismo producto puede venir de los dos:
  hay que reconocerlo por la referencia del fabricante y el EAN, guardar **un solo producto con varios costes (uno por proveedor)** y poder elegir el coste (el más barato, o el más barato con stock).
- **Moneda:** la del proveedor. Un fabricante que trabaja en dólares, en dólares; uno que trabaja en euros, en euros. El cambio y la logística son parámetros editables.
- **Tipo de cambio en línea:** el sistema baja cada día laborable el del **Banco Central Europeo** (`cerebro/cambio.py`, tarea a las 16:30 de Madrid, gratuito y sin clave) y usa el más reciente. El del fichero
  `config/precios.yaml` es solo el **respaldo** (sin tipo guardado o con más de `max_dias` días); en ese caso cada cálculo lo avisa. Se puede añadir un **colchón** (`colchon_pct`) contra variaciones. Primera carga a mano:
  `docker compose exec api python /app/scripts/actualizar_cambio.py`.
- **IVA aparte:** todos los precios se entienden **sin IVA**.
- **Márgenes por familia, sobre la venta:** `venta = coste ÷ (1 − margen)` (con coste 100 y margen 30 %: 142,86 €, no 130 €).
- **Datos de cada producto:** referencia, descripción, características técnicas, precio de coste, precio de venta y stock disponible; y documentación del proveedor (listas de precios, NDA, fichas técnicas, catálogos).
- **Actualización de precios:** por **archivo** (Excel o CSV, en formatos distintos), por **webservice** (API del proveedor) y otras vías.
- **Propuesta de precios:** los agentes analizan la **competencia y el mercado** (tiendas y distribuidores en internet, adjudicaciones de licitaciones y tarifas de competidores) y proponen **varias estrategias de precio**
  en columnas para revisar; **Dirección revisa y aprueba** antes de que nada se escriba en el ERP. Los importes los calcula código determinista, no la IA; el agente solo reúne referencias con su fuente y su fecha.
- **Fichas técnicas de internet:** los agentes pueden descargarlas con las mismas defensas que los pliegos (solo https, solo internet público, tamaño y cupo, tipo real por contenido, cuarentena y antivirus, lectura en proceso aparte);
  si un sitio bloquea las descargas automáticas, no se esquiva: se sube a mano. Adjuntarlas al ERP requiere aprobación.

## Pasos
1. **Lector de tarifas** (`cerebro/tarifas.py`, hecho): Excel con varias hojas y varias tablas, o CSV; cabecera en cualquier fila; columnas con nombres distintos; estados «próximamente», «fin de vida», «muestra»;
   características técnicas (columnas sobrantes o JSON); familia, stock, EAN, marca, precio recomendado; moneda del proveedor. Pura (sin BD ni red): se llamará desde un proceso aparte con límites.
2. **Conectado al importador** (`cerebro/listas_precios.py`, hecho): operación `proponer_tarifa` (el agente no dice las columnas; indica el proveedor y el **canal**, «fabricante» o «distribuidor»). El fichero se lee en un
   **proceso aparte con límites** (`tarifas.leer_aislado`). **Un artículo por marca y referencia**: el código es marca + referencia (en la tarifa del propio fabricante, su nombre), así que la tarifa del fabricante y la del
   distribuidor llegan al MISMO artículo y cada una pone su coste en su lista «Compra <proveedor>», con su moneda. Cada línea lleva el coste en euros y el precio de venta calculados con `precios` (cambio en línea,
   logística del canal, margen, redondeo) y sus avisos («provisional», «de respaldo»). Los productos **próximamente, fin de vida y muestras no se cargan** (se cuentan y se avisa). Sin escribir nada en el ERP hasta que
   una persona apruebe la vista previa (`aplicar`, repetible sin duplicar). El margen del **50 % sobre la venta** para todas las familias lo confirmó Dirección.
   Pendiente de este paso: el stock, el EAN y las características no se escriben aún en el ERP (se guardan en la propuesta); eso llega con el paso 3.
3. **Lista de precios «Venta» con aprobación** (`cerebro/precios_venta.py`, hecho): `proponer_venta` elige para cada artículo el **mejor coste ya en euros** (con logística y cambio; con stock si lo hay), aplica el margen
   de su familia y el redondeo, y lo compara con el precio que ya tiene la lista «Venta» del ERP (nuevo, sube, baja, igual). `ajustar_venta`: Dirección corrige precios a mano o excluye artículos. `aplicar_venta` (exige la
   aprobación de una persona, con vista previa de cambios, márgenes y valores provisionales) crea la lista si falta y crea o actualiza solo lo que ha cambiado; es repetible. **Decisión de Dirección: los precios solo cambian
   cuando Dirección los aprueba**; un coste o un tipo de cambio que cambian no tocan ningún precio de venta sin una propuesta nueva. Tabla `propuestas_venta`. El margen por familia se edita en `config/precios.yaml` (`margen.familias`).
4. **Competencia y estrategias de precio** (`cerebro/mercado.py`, `precios.estrategias_de_precio`, hecho): los agentes buscan precios con la herramienta `web` (tiendas y distribuidores), en otras tarifas o en adjudicaciones y los **anotan
   con su fuente y su fecha** (`anotar_mercado`; sin fuente no se anota; los precios de tienda llevan IVA y se les quita; los de más de 90 días no cuentan; las adjudicaciones son un importe de contrato, no un precio unitario: solo contexto).
   Con ellos el código calcula, para cada artículo, las estrategias de `config/precios.yaml` (competitivo, alineado, premium: parten del mínimo o la mediana de la competencia con un ajuste) **sin bajar nunca del margen mínimo**.
   La propuesta de precios de venta lleva por artículo el precio con tu margen, el PVP del fabricante, el mercado (mínimo, mediana, máximo, fecha) y las estrategias; Dirección elige con `elegir_estrategia` (todos, una familia o códigos)
   o ajusta a mano, y aprueba como siempre. Tabla `referencias_mercado`. **Pantalla «Precios» del panel, hecha** (solo Dirección): ver las propuestas con filtros (familia, cambio, texto, bajo el margen mínimo), ajustar un precio a mano, excluir artículos, aplicar una estrategia a todo o a una familia, ver la vista previa y **aplicar en el ERP con confirmación expresa** (firma única de Dirección, como en la bandeja; queda constancia de quién firmó). Ajustes y estrategias también dejan constancia. Nada llega al ERP sin ese paso.
5. Documentación del proveedor y fichas técnicas (descarga de internet y subida a mano).
6. Que Costes, Precio y Catálogo usen todo esto al preparar ofertas y licitaciones. **Hecho para Costes y Precio de licitaciones** (`cerebro/licitaciones/partidas.py`, ver `docs/PROYECTO_LICITACIONES.md`): las partidas de equipos salen de la tabla de equivalencias, una persona pone las cantidades y el código calcula el coste real con las tarifas; el modelo local de Costes y de Precio recibe esas cifras. **Catálogo, hecho** (herramienta `catalogo`, ver abajo).
7. Actualización periódica de precios por archivo y por webservice. **Hecho** (`cerebro/tarifas_auto.py`, `config/tarifas_auto.yaml`; ver más abajo).

Las tarifas reales de los proveedores son confidenciales: **no se guardan en el repositorio**; las pruebas usan ficheros sintéticos con la misma estructura.


## Actualización periódica de tarifas (por carpeta y por servicio web)

Cada día a las 6:40 (y al pulsar «Comprobar ahora» en **Jarvis → Precios → Tarifas de proveedores**) el sistema mira cada proveedor de `config/tarifas_auto.yaml`. La lista viene **vacía**: añade tus proveedores (el fichero trae un ejemplo comentado).

- **Por carpeta:** deja el Excel o CSV en `/datos/tarifas/<id>/` con `./scripts/tarifa_subir.sh <id> /ruta/a/la_tarifa.xlsx` (ventana Ubuntu; en WSL tus ficheros de Windows están en `/mnt/c/Users/TU_USUARIO/Downloads/`). Cualquier fichero con contenido nuevo cuenta; los ya vistos no se repiten.
- **Por servicio web:** una dirección `https` de un dominio de `hosts` (cada redirección se revalida; anti-SSRF, tamaño máximo). Formatos `csv`, `xlsx` o `json` (la lista y las columnas del JSON se indican en la configuración). Si pide clave, en la configuración solo va el **nombre** (`clave_secreto`); la clave va en `secretos/tarifas.env` (una línea `NOMBRE=valor`, fuera de git; no la pegues en ningún chat) y no sale en ningún registro.

Cada fichero nuevo pasa por la **misma tubería** que una tarifa subida a mano (cuarentena, antivirus, lectura aislada, coste en euros con cambio y logística) y deja **una propuesta de importación** con su resumen frente a la última cargada: artículos nuevos y retirados, cuántos suben y bajan, variación media y los mayores cambios. Si parece **sospechosa** (desaparece más de un tercio de los artículos, o la mayoría cambia más de un 40 %: lo típico de una columna movida o un fichero a medias) se avisa con fuerza, y aparece como urgente en «Hoy».

**Nada se aplica solo.** En la pantalla «Precios» Dirección ve la vista previa, firma (confirmación expresa, queda constancia) y se cargan en el ERP el proveedor, los artículos nuevos y sus costes. **Cargar costes no cambia ningún precio de venta**: después se calcula una propuesta de precios y se aprueba aparte. Un fallo de un proveedor (descarga rota, clave que falta) no frena a los demás y se ve en su línea.


## Catálogo de Proveedores con todo esto

El agente **Catálogo de Proveedores** (que trabaja cada noche a la 1:00 y a petición) tiene ahora la herramienta `catalogo`, de **solo lectura**: `buscar` (por referencia, nombre, marca o familia: mejor coste en euros, proveedor, stock y si trae enlace de ficha), `proveedores_de` (lo que ofrece cada proveedor del mismo artículo, ordenado por coste, con moneda, canal, stock y avisos), `ficha` (fichas técnicas ya cargadas de una referencia), `fichas_pendientes` (cuántas se podrían cargar y qué dominios quedan sin autorizar) y `tarifas_pendientes` (tarifas nuevas por revisar y proveedores cuya comprobación ha fallado). Así su trabajo diario es avisar a Dirección de las tarifas nuevas y de lo que falla. **Los costes los calcula el código** (mismo cálculo que la lista de venta); el agente no escribe cifras ni aplica nada.

**Confidencialidad:** las herramientas con tarifas o costes (`catalogo` y `listas_precios`) están marcadas como confidenciales: **en cuanto el agente usa una con éxito, el resto de esa petición solo va a modelos locales** (nunca a Claude ni a ChatGPT, aunque la consulta sea «compleja»).


## Avisos de precios en «Hoy»
Para Dirección, «Hoy» muestra una tarjeta por cada propuesta de precios de venta pendiente (las 3 más nuevas) con enlace directo a ella (`/precios?propuesta=N`). Dice si hay artículos por debajo del margen mínimo, si usa costes provisionales o de respaldo y, si lleva 7 días o más sin revisar, que sus costes y el cambio pueden estar desactualizados (urgente a partir de 14 días o si falló al aplicarse). Solo lee: no cambia ningún precio.

## Ventas por tipo (Jarvis → Ventas, solo Dirección)
Los 5, 10, 15 o 25 artículos y fabricantes que más venden en cada tipo (videovigilancia, control de accesos, intrusión, incendio, intercom, redes, software, servicios), por importe neto de los pedidos de venta confirmados del ERP en 30 días a 2 años. El tipo de cada línea sale de `config/tipos_producto.yaml`: primero el grupo de artículo del ERP y, si no encaja, palabras del nombre; lo que no encaja va a «Otros» y la pantalla avisa si pesa más del 25 %.
Dirección necesita permiso de lectura de «Sales Order» (ya lo tiene en `config/erp_acceso.yaml`). La lectura usa campos de la línea del pedido (artículo, grupo, marca, cantidad, importe neto) y está probada con datos simulados, no con tu ERP real: si ERPNext rechaza la consulta, la pantalla dice que no ha podido leer los pedidos.

## Descarga de tarifas por servicio web: qué se rechaza
Respuestas cortadas a medias, tiempos de espera, conexión rechazada, fichero vacío, una página web en lugar de la tarifa (sesión caducada o clave rechazada), un «Excel» que no es un .xlsx, `Content-Length` por encima del máximo, redirecciones a http o a otro dominio, JSON sin productos o demasiado anidado. En todos los casos el proveedor queda como «con fallo» con un mensaje claro y no se carga nada.
