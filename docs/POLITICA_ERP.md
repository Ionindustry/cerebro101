# Política de acceso al ERP y al CRM: qué puede tocar cada departamento

Fuente de verdad: `config/erp_acceso.yaml` (esta página se generó a partir de él). **Es una propuesta inicial para revisar con la empresa.**
Para cada departamento: **leer** = puede consultar; **borrador** = además puede crear y modificar en borrador (validar, cancelar y borrar no los puede nadie); **maestros** = datos maestros que solo escribe un proceso ya aprobado por una persona; **sistema** = documentos que solo lee un proceso del sistema, con una lista cerrada de campos (los agentes no los ven con la herramienta `erpnext`).

Cómo revisarla: para cada departamento, mira si le sobra algo (principio de mínimo privilegio) o le falta algo que sus agentes necesiten, y contesta las preguntas. Después se edita el YAML y se aplica con:
```
python3 scripts/erpnext_roles_cerebro.py --todos      # rol por departamento y usuario técnico con solo ese rol
python3 scripts/auditar_acceso_erp.py                 # comprueba que cada uno ve lo que dice la política y nada más
```
Después, `docker compose up -d --force-recreate --no-deps api worker beat` (la API lee la política y las claves al arrancar).

## areas  (11 agentes: director-areas, esp-cctv, esp-incendios, esp-accesos, esp-redes, esp-television…)

- **Leer:** Customer, Contact, Address, Item, Item Price, Bin, Serial No, Project, Task, Quotation, Sales Order, Supplier, Warranty Claim, Maintenance Schedule, Maintenance Visit
- **Borrador (crear y modificar):** Quotation, Task, Maintenance Visit, Warranty Claim
- **Preguntas para decidir:**
  - ¿Cada línea técnica (CCTV, incendios, accesos…) tiene sus propios artículos y proyectos, o se comparten?

## atencion  (3 agentes: soporte-n1, escalado, reactivacion)

- **Leer:** Customer, Contact, Address, Issue, Project, Task, Item, Serial No, Warranty Claim, Maintenance Schedule, Maintenance Visit
- **Borrador (crear y modificar):** Issue, Task, Warranty Claim, Maintenance Visit
- **Preguntas para decidir:**
  - ¿Usáis `Issue` y `Warranty Claim` para incidencias y garantías?

## comercial  (7 agentes: director-comercial, prospector, respuesta-leads, orquestador-campanas, analista-captacion, propuestas…)

- **Leer:** Customer, Contact, Address, Lead, Opportunity, Prospect, Quotation, Sales Order, Item, Campaign, Territory, Customer Group, Project, CRM Lead, CRM Deal, CRM Organization, CRM Task, FCRM Note, CRM Call Log, CRM Lead Source, CRM Lead Status, CRM Deal Status, CRM Product, CRM Industry, CRM Territory, CRM Lost Reason
- **Borrador (crear y modificar):** Lead, Opportunity, Prospect, Quotation, Contact, Address, CRM Lead, CRM Deal, CRM Organization, CRM Task, FCRM Note
- **Preguntas para decidir:**
  - ¿Deben los agentes comerciales dar de alta clientes (`Customer`)? Hoy no pueden: crean Lead, Oportunidad, Presupuesto, Contacto y los documentos del CRM.
  - ¿Necesitan ver el estado de cobro (`Sales Invoice`) para postventa? Hoy no.

## direccion  (6 agentes: estratega, analista-bi, prevision-demanda, paquetizador-servicios, capacidad-planificacion, lanzamiento-rapido)

- **Leer:** Customer, Supplier, Employee, Item, Sales Order, Purchase Invoice, Purchase Order, Quotation, Opportunity, Lead, Project, Task, Campaign, Territory, Customer Group, Bin, CRM Lead, CRM Deal, CRM Organization
- **Borrador (crear y modificar):** — ninguno
- **Preguntas para decidir:**
  - ¿Inteligencia de negocio necesita facturas (`Sales Invoice`) o apuntes (`GL Entry`)? Hoy no. ¿Es correcto que lea `Employee` (lo usa la anonimización)?

## finanzas  (6 agentes: contable, control-gastos, tesorero, facturacion, cobros, fiscal)

- **Leer:** Sales Invoice, Purchase Invoice, Payment Entry, Journal Entry, GL Entry, Account, Bank Account, Cost Center, Payment Request, Customer, Supplier, Sales Order, Item, Project
- **Borrador (crear y modificar):** Sales Invoice, Purchase Invoice, Payment Entry, Journal Entry, Payment Request
- **Preguntas para decidir:**
  - ¿Hace falta `Purchase Order` o `Budget`? Se quitaron porque el rol estándar no los daba; con el rol propio se pueden devolver.
  - ¿Pueden dejar `Payment Entry` o `Journal Entry` en borrador sin que nadie lo apruebe antes? Hoy sí (un humano los valida después).

## legal  (3 agentes: iso9001, no-conformidades, despliegue-departamentos)

- **Leer:** Contract, Customer, Supplier, Project, Task, Non Conformance, Quality Goal, Quality Procedure, Quality Review, Quality Action
- **Borrador (crear y modificar):** Contract, Non Conformance, Quality Goal, Quality Review, Quality Action, Task
- **Preguntas para decidir:**
  - ¿Qué documentos de calidad (ISO 9001) existen realmente en vuestro ERP? La política incluye los de Quality Management.

## licitaciones  (arquitecto-solucion, costes-licitacion, precio-licitacion, director-licitaciones…)

- **Leer:** Customer, Contact, Opportunity, Quotation, Project, Task, Item, Item Price, Supplier, Contract, CRM Deal, CRM Organization, CRM Task, FCRM Note, CRM Deal Status
- **Borrador (crear y modificar):** Opportunity, Quotation, Task, FCRM Note, CRM Task (los agentes anotan y programan tareas en el trato de la licitación)
- **Maestros (solo el sistema, no los agentes):** CRM Deal, CRM Organization. El trato de cada licitación y el organismo comprador los crea y mueve de etapa el Cerebro según el embudo (`cerebro/licitaciones/crm.py`); un agente no abre ni cierra tratos por su cuenta.
- **Sistema (solo lo lee el proceso de la documentación administrativa, no los agentes):** Company, Address, Contact. De ahí salen los datos de la sociedad con la que se presenta una oferta (`cerebro/licitaciones/empresa.py`); solo se piden los campos necesarios (nombre, NIF, dirección, contacto del representante…), nunca cuentas bancarias.
- **Preguntas para decidir:**
  - ¿Necesitan leer facturas anteriores para justificar precios? Hoy no.

## marketing  (2 agentes: estratega-contenidos, disenador-ofertas)

- **Leer:** Campaign, Lead, Item, Item Price, Customer Group, Territory, CRM Lead Source, CRM Industry
- **Borrador (crear y modificar):** Campaign
- **Preguntas para decidir:**
  - ¿Necesitan segmentar clientes (`Customer`)? Hoy no, por protección de datos: solo ven Lead, Campaign y catálogo.

## operaciones  (13 agentes: jefe-proyectos, entrega, calidad, compras, catalogo-proveedores, inventario…)

- **Leer:** Item, Item Price, Price List, Bin, Warehouse, Stock Entry, Material Request, Purchase Order, Purchase Receipt, Delivery Note, Supplier, Project, Task, Timesheet, Work Order, BOM, Sales Order, Customer, Contact, Address
- **Borrador (crear y modificar):** Material Request, Purchase Order, Stock Entry, Delivery Note, Work Order, Task, Timesheet, Project
- **Datos maestros (`maestros`):** Supplier, Item, Item Price, Price List. **Solo los escribe un proceso del sistema que ya ha pasado por la aprobación de una persona** (la importación de listas de precios,
  [IMPORTAR_LISTAS_PRECIOS.md](IMPORTAR_LISTAS_PRECIOS.md)). La operación genérica «crear_borrador» no puede crearlos: ningún agente da de alta un proveedor ni cambia un precio por su cuenta.
- **Preguntas para decidir:**
  - ¿Es aceptable que creen `Purchase Order` y `Stock Entry` en borrador sin aprobación previa? Hoy sí.

## personas  (3 agentes: onboarding, administracion-personal, formacion)

- **Leer:** Employee, Department, Designation, Holiday List, Leave Application, Attendance, Job Opening, Job Applicant, Employee Onboarding, Training Event, Training Program, Salary Structure, Salary Slip
- **Borrador (crear y modificar):** Leave Application, Job Opening, Employee Onboarding, Training Event
- **Preguntas para decidir:**
  - Casi todos sus documentos son de RR. HH. y **no existen en este ERP**: hace falta instalar la aplicación HRMS de Frappe. ¿Se instala?

## tecnologia  (1 agentes: datos)

- **Leer:** Item, Serial No, Asset, Warehouse, Bin, Project, Task
- **Borrador (crear y modificar):** — ninguno
- **Preguntas para decidir:**
  - Solo el agente `datos`. ¿Debe ver algo más que artículos, proyectos y tareas?

## telecom  (7 agentes: director-telecom, catalogo-tarifas, contratacion-telecom, provision, soporte-telecom, facturacion-servicios…)

- **Leer:** Customer, Contact, Address, Item, Item Price, Sales Order, Quotation, Project, Task, Supplier, Purchase Order, Subscription, Subscription Plan
- **Borrador (crear y modificar):** Quotation, Sales Order, Task
- **Preguntas para decidir:**
  - ¿Trabajan con `Subscription` (cuotas recurrentes) o con otra herramienta?

## Datos maestros de solo selección (todos los departamentos)

Un borrador necesita poder *enlazar* algunos datos (cuentas, monedas, territorios…). Para eso el rol recibe solo el permiso de **selección**: ve los nombres, no el contenido.
Lista actual (`referencias`): Account, Company, Currency, Cost Center, Warehouse, UOM, Item Group, Customer Group, Territory, Price List, Mode of Payment, Sales Taxes and Charges Template, Purchase Taxes and Charges Template, Payment Terms Template, Project.

## Dos cosas que decidir para todos
1. **Los borradores se crean sin aprobación previa.** La bandeja de aprobaciones gobierna las *acciones propuestas*; crear un borrador en el ERP lo hace el agente directamente y una persona lo valida después. ¿Os parece bien, o algunos documentos deben pasar por aprobación antes de crearse?
2. **Visibilidad de leads y tratos del CRM.** Frappe CRM solo deja ver a cada usuario los leads y tratos de los que es propietario o que se le asignan. Un agente ve lo que crea (la herramienta le pone como propietario) y lo que se le asigne. Para que vea los del equipo, hay que ponerlo en la jerarquía de ventas del CRM (Ajustes de CRM).
