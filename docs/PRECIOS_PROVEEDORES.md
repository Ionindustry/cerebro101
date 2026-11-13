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
6. Que Costes, Precio y Catálogo usen todo esto al preparar ofertas y licitaciones. **Hecho para Costes y Precio de licitaciones** (`cerebro/licitaciones/partidas.py`, ver `docs/PROYECTO_LICITACIONES.md`): las partidas de equipos salen de la tabla de equivalencias, una persona pone las cantidades y el código calcula el coste real con las tarifas; el modelo local de Costes y de Precio recibe esas cifras. Pendiente: Catálogo.
7. Actualización periódica de precios por archivo y por webservice.

Las tarifas reales de los proveedores son confidenciales: **no se guardan en el repositorio**; las pruebas usan ficheros sintéticos con la misma estructura.
