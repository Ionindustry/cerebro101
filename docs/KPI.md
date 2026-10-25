# KPI de cada agente

En **Agentes**, al pulsar un agente se abre su panel. Solo lo ven Dirección y su departamento (los KPI llevan cifras del negocio). Se puede elegir el periodo: 7, 14, 30 o 90 días,
y cada cifra se compara con el periodo anterior de igual duración (▲ ▼).

## Qué hay en el panel
1. **KPI del cargo** — lo que importa del puesto (ver `config/kpis.yaml`):
   - Cifras del **ERP y del CRM**, de solo lectura, con la clave y la política del departamento (p. ej. Cobros: pendiente de cobro, facturas vencidas, importe vencido; Compras: pedidos e
     importe comprado; Atención: incidencias abiertas, nuevas y cerradas; Comercial: leads nuevos, oportunidades abiertas, presupuestos…).
   - **Uso de sus herramientas** (correos leídos, adjuntos analizados, borradores creados en el ERP, presupuestos calculados…).
   Los 24 agentes con un cargo muy específico tienen KPI propios; los demás, los de su departamento. Un indicador cuyo documento no existe en el ERP instalado (p. ej. RR.HH. sin HRMS)
   aparece como «No disponible» con el motivo, sin afectar al resto.
2. **Actividad por día** y **herramientas más usadas** (con errores).
3. **Rendimiento del agente** (igual para todos): peticiones atendidas, usos de herramientas, éxito (usos sin error), propuestas a aprobación, aprobadas, rechazadas, tasa de aprobación,
   pendientes de tu firma, tiempo medio hasta la decisión y acciones ejecutadas.
4. **Lo que ha propuesto firmar**: aprobadas, rechazadas y pendientes.

## De dónde salen las cifras
- Contadores diarios del propio Cerebro (tabla `kpi_uso`: peticiones, usos, errores, propuestas; solo cifras, nunca contenido), aprobaciones y registro de acciones.
- Las cifras del ERP se piden al ERP (con caché de 1 minuto) y nunca se escriben. Los KPI del cargo cuentan desde que se instaló esta versión; el histórico anterior no existe.

## Cambiar o añadir KPI
Se edita `config/kpis.yaml` (por agente, por departamento o por herramienta) y se reinicia la API. Un test (`test_kpis.py`) comprueba que todo agente tiene KPI, que los documentos del ERP que
se consultan los puede leer su departamento según `config/erp_acceso.yaml` y que las herramientas de uso existen. **Es una propuesta inicial: hay que revisar con cada responsable qué indicadores
quiere ver.**

## Dashboard de cada departamento
En **Agentes**, al elegir un departamento aparece «Dashboard de <departamento> →». Muestra los **KPI más específicos del área** agrupados (p. ej. Finanzas: cartera de clientes, proveedores y pagos, actividad del periodo;
Comercial: captación, oportunidades, presupuestos y ventas, clientes), con cifras del ERP/CRM, la actividad sumada de todos sus agentes, y una tabla del **equipo** (peticiones, usos, éxito, propuestas y firmas pendientes de cada agente,
con enlace a su propio panel). Se define en `paneles_departamento` de `config/kpis.yaml`. Hoy hay 103 KPI de departamento y KPI propios para 69 de los 114 agentes; el resto usa los de su departamento y los de uso de sus herramientas.
