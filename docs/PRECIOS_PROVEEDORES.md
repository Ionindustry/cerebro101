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
3. Márgenes por familia y lista de precios «Venta» con aprobación.
4. Propuesta de precios con mercado, competencia y estrategias, y tabla de revisión para Dirección.
5. Documentación del proveedor y fichas técnicas (descarga de internet y subida a mano).
6. Que Costes, Precio y Catálogo usen todo esto al preparar ofertas y licitaciones.
7. Actualización periódica de precios por archivo y por webservice.

Las tarifas reales de los proveedores son confidenciales: **no se guardan en el repositorio**; las pruebas usan ficheros sintéticos con la misma estructura.
