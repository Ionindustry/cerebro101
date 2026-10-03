# Índice de agentes

13 departamentos, 60 subáreas y 114 agentes. Generado por `scripts/generar_fichas.py`.

## Dirección General

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Director General** | Coordinación | rapido | libre | 0 7 * * 1-5 | Recibe todas las peticiones, las enruta al departamento correcto, prioriza conflictos entre áreas y genera el resumen diario |
| Secretaría de Dirección | Coordinación | principal | simple | bajo petición | Agenda de dirección, actas de reuniones y seguimiento de acuerdos y fechas límite |
| Estratega | Estrategia | principal | libre | 0 8 * * 1 | Objetivos trimestrales, análisis de escenarios y alertas de desviación |
| Analista BI | Inteligencia de negocio | principal | libre | 30 6 * * * | Consolida los KPI de todos los departamentos en el panel diario y semanal |
| Previsión de Demanda | Anticipación y lanzamiento | principal | libre | 0 5 * * 1 | Prevé la demanda por área de servicio con histórico, tendencias, licitaciones, ayudas y estacionalidad |
| Paquetizador de Servicios | Anticipación y lanzamiento | principal | simple | bajo petición | Convierte cada servicio en un paquete estándar con precio cerrado, kit de material, horas tipo y plantilla |
| Capacidad y Planificación | Anticipación y lanzamiento | principal | simple | 0 6 * * 1 | Cruza la previsión con stock, distribuidora e instaladores y reserva capacidad y material |
| Lanzamiento Rápido | Anticipación y lanzamiento | principal | doble | bajo petición | Lleva una oportunidad aprobada al mercado: oferta, material, instaladores, campaña y formación |

## Finanzas y Contabilidad

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Contable** | Contabilidad | principal | doble | 0 4 1 * * | Asientos en borrador, conciliación bancaria, cierre mensual y cuenta de resultados explicada |
| Control de Gastos | Contabilidad | rapido | simple | bajo petición | Clasifica tickets y facturas de proveedor y controla el presupuesto por departamento |
| Tesorero | Tesorería | principal | libre | 0 7 * * 1 | Previsión de caja a 30/60/90 días, alertas de liquidez y calendario de pagos |
| Facturación | Facturación y cobros | principal | doble | bajo petición | Prepara facturas en borrador según la normativa vigente para su validación |
| Cobros | Facturación y cobros | principal | simple | 0 9 * * 1-5 | Detecta impagados y redacta recordatorios graduados según el historial del cliente |
| Fiscal | Fiscalidad | principal | doble | 0 8 1 * * | Calendario de modelos fiscales y documentación para la gestoría |

## Comercial y Ventas

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Director Comercial / CRM** | Gestión de clientes | principal | libre | 0 8 * * 1-5 | Mantiene fichas y pipeline al día y detecta oportunidades paradas |
| Prospector | Prospección | rapido | libre | bajo petición | Construye listas de clientes potenciales según el perfil ideal y las puntúa |
| Detector de Intención | Prospección | rapido | libre | 0 3 * * * | Busca señales públicas de interés (obras, aperturas, ofertas de empleo) y las convierte en leads |
| Respuesta a Leads | Prospección | principal | simple | bajo petición | Contesta cada consulta entrante en minutos y propone fechas de reunión |
| Orquestador de Campañas | Captación multicanal | principal | simple | 0 9 * * 1-5 | Diseña la secuencia por canal, reparte leads y detiene la secuencia cuando alguien responde |
| Email | Captación multicanal | principal | simple | bajo petición | Secuencias de email personalizadas respetando consentimientos y bajas |
| LinkedIn | Captación multicanal | principal | simple | bajo petición | Prepara mensajes y contenido para que una persona los publique o envíe |
| Teléfono y WhatsApp | Captación multicanal | principal | simple | bajo petición | Guiones de llamada, agenda de llamadas y WhatsApp Business solo con autorización |
| Analista de Captación | Captación multicanal | principal | libre | 0 7 * * 1 | Coste por lead y conversión por canal y campaña |
| Propuestas y Presupuestos | Propuestas | principal | doble | bajo petición | Convierte notas de reunión en propuestas y presupuestos con precios históricos |
| Gestor de Cuentas | Postventa | principal | simple | 0 9 * * 1 | Renovaciones, ventas adicionales y satisfacción de clientes clave |

## Marketing

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Estratega de Contenidos** | Contenido | principal | libre | 0 8 1 * * | Calendario editorial mensual según lo que vende y la temporada |
| Redactor | Contenido | principal | simple | bajo petición | Artículos, newsletters y textos web en catalán, castellano e inglés |
| Social Media | Redes sociales | principal | simple | bajo petición | Prepara y programa publicaciones y responde comentarios rutinarios |
| SEO/GEO | SEO y visibilidad IA | principal | simple | 0 4 * * 1 | Auditoría web y posicionamiento en buscadores y asistentes de IA |
| Publicidad | Publicidad | principal | doble | 0 7 * * 1 | Analiza campañas de pago, propone presupuesto y redacta anuncios |
| Guardián de Marca | Marca | rapido | libre | bajo petición | Guía de estilo y tono; revisa que todo lo publicado sea coherente |
| Radar de Tendencias | Inteligencia de mercado | rapido | libre | 0 */2 * * * | Vigila X y la web en tiempo real con Grok y envía alertas puntuadas |
| Analista de Noticias de Mercado | Inteligencia de mercado | principal | libre | 0 2 * * * | Prensa sectorial, boletines, ayudas, normativa y competidores; fichas de oportunidad |
| Analista de Competencia | Inteligencia de mercado | principal | libre | 0 1 * * 1 | Ficha de cada competidor a partir de su web pública; avisa de cambios semanales |
| Diseñador de Ofertas | Inteligencia de mercado | principal | doble | bajo petición | Convierte una oportunidad aprobada en oferta con catálogo, costes y argumentario |

## Atención al Cliente

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Soporte Nivel 1** | Soporte | rapido | simple | bajo petición | Responde consultas frecuentes por email y chat con la base de conocimiento |
| Escalado | Soporte | rapido | libre | bajo petición | Clasifica incidencias complejas y las pasa a una persona con todo el contexto |
| Reseñas | Reputación | rapido | simple | 0 10 * * * | Vigila reseñas públicas y redacta respuestas para aprobar |
| Reactivación | Fidelización | principal | simple | 0 9 * * 1 | Detecta clientes inactivos y prepara mensajes de recuperación |

## Operaciones y Servicio

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Jefe de Proyectos** | Gestión de proyectos | principal | libre | 0 7 * * 1-5 | Planifica tareas, plazos y recursos de cada proyecto y avisa de retrasos |
| Entrega | Entrega | rapido | simple | bajo petición | Checklists de entrega al cliente y confirmación de cierre |
| Calidad | Calidad | principal | libre | bajo petición | Registra incidencias, analiza causas y propone mejoras de proceso |
| Compras | Compras y proveedores | principal | doble | bajo petición | Compara proveedores, prepara pedidos en borrador y controla plazos |
| Catálogo de Proveedores | Compras y proveedores | rapido | libre | 0 1 * * * | Importa tarifas (Visiotech, ETT, Asecur, Saltoki, distribuidora propia), cruza productos y avisa de cambios |
| Explorador de Fabricantes | Compras y proveedores | principal | libre | 0 2 * * 3 | Busca y evalúa fabricantes nuevos; tarifas y acuerdos vía la distribuidora propia |
| Inventario y Recursos | Compras y proveedores | rapido | libre | 0 6 * * * | Control de stock, licencias y material |
| Cotizador | Cotización de instalaciones | principal | doble | bajo petición | Aplica el motor del contador y deja el presupuesto en borrador en el ERP |
| Medidor Técnico | Cotización de instalaciones | vision | simple | bajo petición | Saca cantidades de planos y fotos y ajusta las horas de cada partida al caso |
| Tiempos Reales | Cotización de instalaciones | principal | simple | 0 3 * * 1 | Compara horas presupuestadas con partes reales y propone actualizar la tabla de tiempos |
| Captador de Instaladores | Red de instaladores | principal | libre | 0 2 * * 2 | Busca empresas instaladoras por zona y especialidad y verifica habilitaciones |
| Negociador | Red de instaladores | principal | doble | bajo petición | Contacta y negocia tarifa hora por categoría dentro del rango fijado por dirección |
| Acuerdos y Documentación | Red de instaladores | principal | doble | bajo petición | Acuerdo marco y documentación obligatoria de cada instalador |
| Comparador de Presupuestos | Red de instaladores | juez | doble | bajo petición | Pide presupuesto a instaladores con acuerdo y propone el mejor por precio, rapidez y eficiencia |
| Evaluación de Instaladores | Red de instaladores | juez | libre | 0 4 * * 1 | Puntúa cada trabajo terminado y mantiene el ranking |

## Personas (RRHH)

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Selección** | Selección | principal | doble | bajo petición | Ofertas de empleo, cribado según criterios fijados y agenda de entrevistas (sin servicios externos) |
| Onboarding | Incorporación | principal | simple | bajo petición | Checklist de primer día, accesos, documentación y plan de bienvenida |
| Administración de Personal | Administración de personal | principal | doble | 0 8 25 * * | Datos de nómina para la gestoría, vacaciones, bajas y registro horario |
| Formación | Desarrollo | principal | simple | 0 8 1 * * | Plan de formación anual y seguimiento de cursos |
| Clima Laboral | Desarrollo | principal | simple | 0 9 1 */3 * | Encuestas internas periódicas y resumen para dirección |

## Legal y Cumplimiento

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Contratos** | Contratos | principal | doble | bajo petición | Revisa contratos, marca cláusulas de riesgo y mantiene plantillas |
| RGPD | Protección de datos | principal | simple | bajo petición | Registro de tratamientos, derechos y revisión legal de cada campaña |
| Cumplimiento | Cumplimiento normativo | principal | libre | 0 8 * * 1 | Calendario de obligaciones legales y requisitos por área de servicio |
| Responsable del Sistema Integrado | Sistemas de gestión | principal | doble | 0 8 1 * * | Coordina ENS, 27001, 9001 y 14001 como un único sistema y prepara la revisión por la dirección |
| ENS | Sistemas de gestión | principal | doble | bajo petición | Categorización, análisis de riesgos, declaración de aplicabilidad y plan de adecuación |
| ISO 27001 | Sistemas de gestión | principal | doble | bajo petición | SGSI, evaluación de riesgos, aplicabilidad de controles y plan de tratamiento |
| ISO 9001 | Sistemas de gestión | principal | doble | bajo petición | Procesos, indicadores, satisfacción, proveedores y competencia |
| ISO 14001 | Sistemas de gestión | principal | doble | bajo petición | Aspectos ambientales, requisitos legales, residuos y emergencias |
| Documentación y Evidencias | Auditoría y evidencias | vision | simple | 0 3 * * 0 | Control documental y paquete de evidencias por requisito (solo hechos reales) |
| Auditoría Interna | Auditoría y evidencias | juez | simple | 0 3 1 * * | Programa anual, listas de comprobación y simulacros por norma |
| No Conformidades y Mejora | Auditoría y evidencias | principal | simple | 0 8 * * 1 | Registra no conformidades y sigue acciones correctivas hasta cerrarlas |
| Despliegue en Departamentos | Auditoría y evidencias | principal | simple | bajo petición | Convierte cada política en tareas, flujos y registros por departamento |

## Tecnología y Sistemas

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Infraestructura** | Infraestructura | rapido | simple | 0 * * * * | Monitoriza el servidor, copias de seguridad y actualizaciones |
| Seguridad | Seguridad | rapido | simple | */15 * * * * | Revisa accesos y registros y alerta de comportamientos anómalos |
| Web | Web y desarrollo | principal | simple | bajo petición | Mantenimiento de la web 101.cat e incidencias técnicas |
| Datos | Datos | principal | libre | 0 0 * * * | Integra fuentes y vigila la calidad de los datos |

## Conocimiento y Supervisión

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Bibliotecario** | Base de conocimiento | rapido | libre | 30 0 * * * | Indexa documentos, correos y actas para todos los agentes |
| Procedimientos | Procedimientos | principal | simple | bajo petición | Redacta y actualiza los procesos internos de cada departamento |
| Auditor del Cerebro | Supervisión de agentes | juez | libre | 0 5 * * * | Revisa una muestra de respuestas de cada agente y propone ajustes |

## Licitaciones Públicas

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Director de Licitaciones** | Vigilancia de oportunidades | principal | libre | 0 7 * * 1-5 | Coordina el ciclo completo de cada concurso y controla todos los plazos |
| Rastreador | Vigilancia de oportunidades | rapido | libre | 0 6 * * * | Revisa a diario las plataformas de contratación y filtra por CPV, importe y zona |
| Viabilidad | Vigilancia de oportunidades | juez | libre | bajo petición | Puntúa solvencia, plazos, presupuesto, capacidad, competencia y certificaciones; informe ir/no ir |
| Administrativo | Documentación administrativa | principal | doble | bajo petición | DEUC, declaraciones responsables, solvencia y certificados vigentes |
| Presentación y Requerimientos | Documentación administrativa | principal | doble | bajo petición | Calendario, aclaraciones, paquete de oferta listo para que una persona firme y presente, y subsanaciones |
| Analista de Pliegos | Oferta técnica | vision | libre | bajo petición | Extrae requisitos, criterios, puntuación y formato; crea la matriz de cumplimiento |
| Arquitecto de Solución | Oferta técnica | principal | simple | bajo petición | Diseña la mejor solución criterio a criterio dentro del presupuesto |
| Redactor de Memoria | Oferta técnica | principal | simple | bajo petición | Redacta la memoria con la estructura exacta del pliego, sin mezclar sobres |
| Evaluador | Oferta técnica | juez | libre | bajo petición | Simula la puntuación de la mesa y detecta incumplimientos excluyentes |
| Costes | Oferta económica | principal | simple | bajo petición | Coste real con convenio, subrogaciones, materiales, gastos generales y riesgos |
| Precio | Oferta económica | principal | doble | bajo petición | Simula la fórmula económica y el umbral de baja anormal y propone el precio |
| Inteligencia Competitiva | Seguimiento | principal | libre | 0 4 * * * | Actas de adjudicación, competidores y precios ganadores; plazos de recurso |

## Telecom mayorista

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Director de Telecom** | Acuerdos con mayoristas | principal | libre | 0 8 * * 1 | Coordina el departamento, decide el catálogo y sigue margen, altas y bajas |
| Gestor de Mayoristas | Acuerdos con mayoristas | principal | doble | bajo petición | Compara y negocia tarifas, comisiones y niveles de servicio con mayoristas |
| Catálogo de Tarifas | Acuerdos con mayoristas | principal | doble | 0 2 * * 1 | Oferta de venta con margen (fibra, móvil, centralita, SIP, SD-WAN, SIM M2M) |
| Estudio de Cobertura y Ahorro | Venta y contratación | vision | libre | bajo petición | Cobertura por dirección, dimensionado y comparación con la factura actual |
| Contratación | Venta y contratación | principal | doble | bajo petición | Contrato, identidad, domiciliación, consentimientos y portabilidades |
| Provisión | Provisión y soporte | rapido | simple | */30 * * * * | Altas con el mayorista, instalación, activación y portabilidades |
| Soporte Telecom | Provisión y soporte | rapido | simple | bajo petición | Incidencias de línea y tickets con el mayorista dentro de plazo |
| Facturación de Servicios | Facturación y cartera | principal | doble | 0 3 1 * * | Consumos, facturación mensual y conciliación con la factura mayorista |
| Retención y Cartera | Facturación y cartera | principal | simple | 0 9 * * 1 | Riesgo de baja, fin de permanencias y paquetes combinados |
| Cumplimiento Telecom | Regulación | principal | libre | 0 8 * * 1 | Obligaciones de operador ante la CNMC, consumo, conservación de datos y portabilidad |

## Áreas de Servicio

| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |
| --- | --- | --- | --- | --- | --- |
| **Director de Áreas de Servicio** | Coordinación | principal | simple | 0 8 * * 1 | Coordina especialistas, prioriza áreas según la previsión y diseña paquetes combinados |
| Especialista CCTV | Seguridad | principal | libre | bajo petición | Videovigilancia, lectura de matrículas y analítica; equipos y protección de datos |
| Especialista Contra Incendios | Seguridad | principal | libre | bajo petición | Detección y extinción según reglamento y planes de mantenimiento obligatorio |
| Especialista Control de Accesos | Seguridad | principal | libre | bajo petición | Accesos para comunidades, oficinas y aparcamientos; integración con videoportero |
| Especialista Redes | Conectividad e infraestructuras | principal | libre | bajo petición | Cableado estructurado, wifi, fibra interior y certificación |
| Especialista Televisión e ICT | Conectividad e infraestructuras | principal | libre | bajo petición | Antenas e ICT en edificios, proyectos y boletines |
| Especialista Localización | Conectividad e infraestructuras | principal | libre | bajo petición | Seguimiento de flotas y activos con SIM M2M de Telecom |
| Especialista Renovables | Energía y hogar | principal | libre | bajo petición | Autoconsumo, baterías y recarga; cálculo del ahorro |
| Especialista Domótica | Energía y hogar | principal | libre | bajo petición | Hogar y edificio conectado, eficiencia e integración |
| Especialista Construcción | Obra | principal | libre | bajo petición | Obra civil asociada: canalizaciones, zanjas y pequeñas reformas |
| Coordinación de Obra y Prevención | Obra | principal | simple | bajo petición | Plan de seguridad y salud, coordinación con instaladores y documentación de subcontratación |
| Mantenimientos Programados | Servicios recurrentes y tramitación | rapido | simple | 0 6 * * * | Contratos de mantenimiento, calendario de visitas, actas e ingresos recurrentes |
| Tramitación y Legalizaciones | Servicios recurrentes y tramitación | principal | doble | bajo petición | Legalizaciones eléctricas y fotovoltaicas, boletines, ICT y licencias |
| Ayudas y Subvenciones | Servicios recurrentes y tramitación | principal | simple | 0 3 * * 2 | Detecta ayudas aplicables a cada cliente y prepara la solicitud |
