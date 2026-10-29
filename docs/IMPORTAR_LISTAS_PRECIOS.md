# Importar una lista de precios de un proveedor

Sube la lista (Excel `.xlsx`, CSV o PDF) con el botón 📎 del chat de Jarvis y escribe, por ejemplo: **«Importa esta lista de precios de Visiotech»**. El agente **Catálogo de Proveedores** (Operaciones)
la prepara, y **una persona de Dirección la aprueba** en la bandeja de aprobaciones antes de que se escriba nada en el ERP.

## Qué pasa, paso a paso
1. **El sistema lee la tabla del documento**, no el modelo. El agente solo mira las primeras filas (`tabla`) y dice quién es el proveedor y qué columna es la referencia, el precio, la descripción, la unidad o el
   descuento. Con un modelo local, transcribir cientos de líneas tardaría horas y se equivocaría: así cada línea sale tal cual del documento.
2. **Se valida** (`proponer`): precios que no son números, ambiguos (`1.234`), cero, negativos o absurdos se **rechazan** con el motivo y la fila; las referencias repetidas se descartan avisando si traen otro precio;
   un título de sección o una nota se omiten. Si se rechazan más filas de las que valen, se para: las columnas no parecen las correctas. Si los precios del documento llevan IVA incluido, se indica y se descuenta.
3. **Se comprueba contra el ERP** (solo lectura): qué artículos ya existen y si el proveedor existe (por NIF o por nombre). Se guarda la **propuesta**; todavía no se ha escrito nada.
4. **Aprobación.** En la bandeja ves: proveedor (nuevo o existente), la lista de precios («Compra <proveedor>»), cuántos artículos se crean y cuántos solo reciben precio, el rango de precios, los avisos y las
   primeras líneas. Al aprobar se ejecuta `aplicar`.
5. **Aplicar** da de alta el proveedor (si no existe), la lista de precios, los artículos nuevos (código `<PREFIJO>-<referencia>`, para que dos proveedores con la misma referencia no choquen) y los precios.
   **Se puede repetir sin duplicar**: lo que ya está no se vuelve a crear, un precio distinto se actualiza, y si el ERP falla a mitad se guarda lo hecho y se reintenta por donde iba.

## Lo que hay que saber
- **Permisos:** Operaciones tiene `maestros: [Supplier, Item, Item Price, Price List]` en `config/erp_acceso.yaml`. Solo los usa este proceso aprobado; la operación genérica del ERP no puede crearlos.
  Hay que **dar esos permisos al usuario técnico en ERPNext**: `python3 scripts/erpnext_roles_cerebro.py --todos` y después `python3 scripts/auditar_acceso_erp.py`.
- **Valores por defecto** (`config/integraciones.yaml` → `listas_precios`): grupo de artículos `Products`, unidad `Nos`, grupo de proveedor `All Supplier Groups`. **POR VERIFICAR con vuestro ERPNext**: si no existen, la carga
  lo dice (error de ERPNext) y se repite tras crearlos o cambiar el valor.
- **PDF:** se lee el texto con columnas separadas por espacios; es el formato menos fiable. Revisa la vista previa con cuidado. Excel y CSV son lo recomendado.
- **El nombre y el NIF del proveedor** los pone el agente; si no aparecen en el texto del documento se avisa en la aprobación (puede venir en un logo).
- **Qué NO hace:** no cruza artículos de distintos proveedores ni los fusiona con el catálogo existente (solo reconoce los suyos por código), no crea el grupo de artículos ni las unidades, y no compra nada.
