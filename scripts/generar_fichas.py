"""Genera las fichas de agente (config/agentes/*.yaml), el mapa de departamentos
(config/departamentos.yaml) y el índice docs/AGENTES.md a partir de los datos
maestros de este fichero, que reflejan el documento «Cerebro 101.cat».

Uso:  python scripts/generar_fichas.py

Para cambiar un agente: edita su fila aquí y vuelve a ejecutar el script.
El primer agente de cada departamento es su agente director.

Campos de cada fila:
  id, nombre, subárea, tareas, modelo, herramientas, aprobación, horario, sensibilidad
  - modelo: rapido | principal | vision | juez
  - aprobación: libre | simple | doble  (ver config/politicas_aprobacion.yaml)
  - horario: expresión cron (hora local) o None si solo actúa bajo petición
  - sensibilidad: baja | media | alta  (decide qué servicios externos puede usar)
"""
from __future__ import annotations

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent

DEPARTAMENTOS = {
    "direccion": "Dirección General",
    "finanzas": "Finanzas y Contabilidad",
    "comercial": "Comercial y Ventas",
    "marketing": "Marketing",
    "atencion": "Atención al Cliente",
    "operaciones": "Operaciones y Servicio",
    "personas": "Personas (RRHH)",
    "legal": "Legal y Cumplimiento",
    "tecnologia": "Tecnología y Sistemas",
    "conocimiento": "Conocimiento y Supervisión",
    "licitaciones": "Licitaciones Públicas",
    "telecom": "Telecom mayorista",
    "areas": "Áreas de Servicio",
}

K = ["conocimiento"]  # herramienta base que tienen todos los agentes

# Agentes que investigan: tienen cuadernos de investigación (herramienta «cuaderno», como NotebookLM pero en local)
INVESTIGAN = {"asistente-general", "analista-noticias", "analista-competencia", "radar-tendencias",
              "explorador-fabricantes", "inteligencia-competitiva", "viabilidad"}

AGENTES = {
    "direccion": [
        ("director-general", "Director General", "Coordinación", "Recibe todas las peticiones, las enruta al departamento correcto, prioriza conflictos entre áreas y genera el resumen diario", "rapido", K + ["jev"], "libre", "0 7 * * 1-5", "media"),
        ("asistente-general", "Asistente general", "Coordinación", "Responde cualquier duda general o de actualidad con la fecha y hora actuales y consultando internet (buscador propio y lectura de páginas públicas); también lo del sector (precios de mercado, productos de fabricantes, competidores, noticias), citando las fuentes; nunca con datos de clientes ni de personas, y lo que necesita datos internos o hacer algo lo redirige al departamento que corresponde", "principal", K + ["web"], "libre", None, "baja"),
        ("secretaria-direccion", "Secretaría de Dirección", "Coordinación", "Agenda de dirección, actas de reuniones y seguimiento de acuerdos y fechas límite", "principal", K + ["calendario", "correo"], "simple", None, "media"),
        ("estratega", "Estratega", "Estrategia", "Objetivos trimestrales, análisis de escenarios y alertas de desviación", "principal", K + ["erpnext"], "libre", "0 8 * * 1", "media"),
        ("analista-bi", "Analista BI", "Inteligencia de negocio", "Consolida los KPI de todos los departamentos en el panel diario y semanal", "principal", K + ["erpnext"], "libre", "30 6 * * *", "media"),
        ("prevision-demanda", "Previsión de Demanda", "Anticipación y lanzamiento", "Prevé la demanda por área de servicio con histórico, tendencias, licitaciones, ayudas y estacionalidad", "principal", K + ["erpnext"], "libre", "0 5 * * 1", "media"),
        ("paquetizador-servicios", "Paquetizador de Servicios", "Anticipación y lanzamiento", "Convierte cada servicio en un paquete estándar con precio cerrado, kit de material, horas tipo y plantilla", "principal", K + ["erpnext", "cotizador"], "simple", None, "media"),
        ("capacidad-planificacion", "Capacidad y Planificación", "Anticipación y lanzamiento", "Cruza la previsión con stock, distribuidora e instaladores y reserva capacidad y material", "principal", K + ["erpnext"], "simple", "0 6 * * 1", "media"),
        ("lanzamiento-rapido", "Lanzamiento Rápido", "Anticipación y lanzamiento", "Lleva una oportunidad aprobada al mercado: oferta, material, instaladores, campaña y formación", "principal", K + ["erpnext", "correo"], "doble", None, "media"),
    ],
    "finanzas": [
        ("contable", "Contable", "Contabilidad", "Asientos en borrador, conciliación bancaria, cierre mensual y cuenta de resultados explicada", "principal", K + ["erpnext"], "doble", "0 4 1 * *", "alta"),
        ("control-gastos", "Control de Gastos", "Contabilidad", "Lee las facturas de proveedor que llegan por correo (PDF, escaneos y fotos, con OCR), las deja en borrador en el ERP para su validación, clasifica tickets y controla el presupuesto por departamento", "principal", K + ["erpnext", "correo", "jev"], "simple", None, "alta"),
        ("tesorero", "Tesorero", "Tesorería", "Previsión de caja a 30/60/90 días, alertas de liquidez y calendario de pagos", "principal", K + ["erpnext"], "libre", "0 7 * * 1", "alta"),
        ("facturacion", "Facturación", "Facturación y cobros", "Prepara facturas en borrador según la normativa vigente para su validación", "principal", K + ["erpnext"], "doble", None, "alta"),
        ("cobros", "Cobros", "Facturación y cobros", "Detecta impagados y redacta recordatorios graduados según el historial del cliente", "principal", K + ["erpnext", "correo", "jev"], "simple", "0 9 * * 1-5", "alta"),
        ("fiscal", "Fiscal", "Fiscalidad", "Calendario de modelos fiscales y documentación para la gestoría", "principal", K + ["erpnext"], "doble", "0 8 1 * *", "alta"),
    ],
    "comercial": [
        ("director-comercial", "Director Comercial / CRM", "Gestión de clientes", "Mantiene fichas y pipeline al día y detecta oportunidades paradas", "principal", K + ["erpnext"], "libre", "0 8 * * 1-5", "media"),
        ("prospector", "Prospector", "Prospección", "Construye listas de clientes potenciales según el perfil ideal y las puntúa", "rapido", K + ["erpnext", "jev"], "libre", None, "media"),
        ("detector-intencion", "Detector de Intención", "Prospección", "Busca señales públicas de interés (obras, aperturas, ofertas de empleo) y las convierte en leads", "rapido", K + ["scrapegraph", "grok", "jev"], "libre", "0 3 * * *", "baja"),
        ("respuesta-leads", "Respuesta a Leads", "Prospección", "Contesta cada consulta entrante en minutos y propone fechas de reunión", "principal", K + ["correo", "calendario", "erpnext", "jev"], "simple", None, "media"),
        ("orquestador-campanas", "Orquestador de Campañas", "Captación multicanal", "Diseña la secuencia por canal, reparte leads y detiene la secuencia cuando alguien responde", "principal", K + ["erpnext"], "simple", "0 9 * * 1-5", "media"),
        ("canal-email", "Email", "Captación multicanal", "Secuencias de email personalizadas respetando consentimientos y bajas", "principal", K + ["correo"], "simple", None, "media"),
        ("canal-linkedin", "LinkedIn", "Captación multicanal", "Prepara mensajes y contenido para que una persona los publique o envíe", "principal", K, "simple", None, "media"),
        ("canal-telefono", "Teléfono y WhatsApp", "Captación multicanal", "Guiones de llamada, agenda de llamadas y WhatsApp Business solo con autorización", "principal", K + ["calendario"], "simple", None, "media"),
        ("analista-captacion", "Analista de Captación", "Captación multicanal", "Coste por lead y conversión por canal y campaña", "principal", K + ["erpnext"], "libre", "0 7 * * 1", "media"),
        ("propuestas", "Propuestas y Presupuestos", "Propuestas", "Convierte notas de reunión en propuestas y presupuestos con precios históricos", "principal", K + ["erpnext", "cotizador"], "doble", None, "media"),
        ("gestor-cuentas", "Gestor de Cuentas", "Postventa", "Renovaciones, ventas adicionales y satisfacción de clientes clave", "principal", K + ["erpnext", "correo"], "simple", "0 9 * * 1", "media"),
    ],
    "marketing": [
        ("estratega-contenidos", "Estratega de Contenidos", "Contenido", "Calendario editorial mensual según lo que vende y la temporada", "principal", K + ["erpnext"], "libre", "0 8 1 * *", "baja"),
        ("redactor", "Redactor", "Contenido", "Artículos, newsletters y textos web en catalán, castellano e inglés", "principal", K, "simple", None, "baja"),
        ("social-media", "Social Media", "Redes sociales", "Prepara y programa publicaciones y responde comentarios rutinarios", "principal", K, "simple", None, "baja"),
        ("seo-geo", "SEO/GEO", "SEO y visibilidad IA", "Auditoría web y posicionamiento en buscadores y asistentes de IA", "principal", K + ["scrapegraph"], "simple", "0 4 * * 1", "baja"),
        ("publicidad", "Publicidad", "Publicidad", "Analiza campañas de pago, propone presupuesto y redacta anuncios", "principal", K, "doble", "0 7 * * 1", "baja"),
        ("guardian-marca", "Guardián de Marca", "Marca", "Guía de estilo y tono; revisa que todo lo publicado sea coherente", "rapido", K + ["jev"], "libre", None, "baja"),
        ("radar-tendencias", "Radar de Tendencias", "Inteligencia de mercado", "Vigila X y la web en tiempo real con Grok y envía alertas puntuadas", "rapido", K + ["grok", "agent_reach", "jev"], "libre", "0 */2 * * *", "baja"),
        ("analista-noticias", "Analista de Noticias de Mercado", "Inteligencia de mercado", "Prensa sectorial, boletines, ayudas, normativa y competidores; fichas de oportunidad", "principal", K + ["scrapegraph", "agent_reach", "jev"], "libre", "0 2 * * *", "baja"),
        ("analista-competencia", "Analista de Competencia", "Inteligencia de mercado", "Busca competidores en internet y hace la ficha de cada uno a partir de su web pública; avisa de cambios semanales", "principal", K + ["web", "scrapegraph", "agent_reach"], "libre", "0 1 * * 1", "baja"),
        ("disenador-ofertas", "Diseñador de Ofertas", "Inteligencia de mercado", "Convierte una oportunidad aprobada en oferta con catálogo, costes y argumentario", "principal", K + ["erpnext", "cotizador"], "doble", None, "media"),
    ],
    "atencion": [
        ("soporte-n1", "Soporte Nivel 1", "Soporte", "Responde consultas frecuentes por email y chat con la base de conocimiento", "rapido", K + ["correo", "erpnext", "jev"], "simple", None, "media"),
        ("escalado", "Escalado", "Soporte", "Clasifica incidencias complejas y las pasa a una persona con todo el contexto", "rapido", K + ["erpnext", "jev"], "libre", None, "media"),
        ("resenas", "Reseñas", "Reputación", "Vigila reseñas públicas y redacta respuestas para aprobar", "rapido", K + ["scrapegraph", "jev"], "simple", "0 10 * * *", "baja"),
        ("reactivacion", "Reactivación", "Fidelización", "Detecta clientes inactivos y prepara mensajes de recuperación", "principal", K + ["erpnext", "correo"], "simple", "0 9 * * 1", "media"),
    ],
    "operaciones": [
        ("jefe-proyectos", "Jefe de Proyectos", "Gestión de proyectos", "Planifica tareas, plazos y recursos de cada proyecto y avisa de retrasos", "principal", K + ["erpnext", "calendario", "jev"], "libre", "0 7 * * 1-5", "media"),
        ("entrega", "Entrega", "Entrega", "Checklists de entrega al cliente y confirmación de cierre", "rapido", K + ["erpnext"], "simple", None, "media"),
        ("calidad", "Calidad", "Calidad", "Registra incidencias, analiza causas y propone mejoras de proceso", "principal", K + ["erpnext", "jev"], "libre", None, "media"),
        ("compras", "Compras", "Compras y proveedores", "Compara proveedores, prepara pedidos en borrador y controla plazos", "principal", K + ["erpnext", "documentos_subidos"], "doble", None, "media"),
        ("catalogo-proveedores", "Catálogo de Proveedores", "Compras y proveedores", "Importa tarifas (Visiotech, ETT, Asecur, Saltoki, distribuidora propia), cruza productos y avisa de cambios", "rapido", K + ["erpnext", "ficheros", "jev", "documentos_subidos", "listas_precios"], "libre", "0 1 * * *", "media"),
        ("explorador-fabricantes", "Explorador de Fabricantes", "Compras y proveedores", "Busca y evalúa fabricantes nuevos; tarifas y acuerdos vía la distribuidora propia", "principal", K + ["scrapegraph", "agent_reach", "grok"], "libre", "0 2 * * 3", "baja"),
        ("inventario", "Inventario y Recursos", "Compras y proveedores", "Control de stock, licencias y material", "rapido", K + ["erpnext"], "libre", "0 6 * * *", "media"),
        ("cotizador", "Cotizador", "Cotización de instalaciones", "Aplica el motor del contador y deja el presupuesto en borrador en el ERP", "principal", K + ["cotizador", "erpnext"], "doble", None, "media"),
        ("medidor-tecnico", "Medidor Técnico", "Cotización de instalaciones", "Saca cantidades de planos y fotos y ajusta las horas de cada partida al caso", "vision", K + ["ficheros", "cotizador"], "simple", None, "media"),
        ("tiempos-reales", "Tiempos Reales", "Cotización de instalaciones", "Compara horas presupuestadas con partes reales y propone actualizar la tabla de tiempos", "principal", K + ["erpnext", "cotizador"], "simple", "0 3 * * 1", "media"),
        ("captador-instaladores", "Captador de Instaladores", "Red de instaladores", "Busca empresas instaladoras por zona y especialidad y verifica habilitaciones", "principal", K + ["scrapegraph", "erpnext"], "libre", "0 2 * * 2", "baja"),
        ("negociador", "Negociador", "Red de instaladores", "Contacta y negocia tarifa hora por categoría dentro del rango fijado por dirección", "principal", K + ["correo", "erpnext"], "doble", None, "media"),
        ("acuerdos-instaladores", "Acuerdos y Documentación", "Red de instaladores", "Acuerdo marco y documentación obligatoria de cada instalador", "principal", K + ["erpnext", "ficheros"], "doble", None, "alta"),
        ("comparador-presupuestos", "Comparador de Presupuestos", "Red de instaladores", "Pide presupuesto a instaladores con acuerdo y propone el mejor por precio, rapidez y eficiencia", "juez", K + ["comparador_instaladores", "correo", "erpnext"], "doble", None, "media"),
        ("evaluacion-instaladores", "Evaluación de Instaladores", "Red de instaladores", "Puntúa cada trabajo terminado y mantiene el ranking", "juez", K + ["erpnext"], "libre", "0 4 * * 1", "media"),
    ],
    "personas": [
        ("seleccion", "Selección", "Selección", "Ofertas de empleo, cribado según criterios fijados y agenda de entrevistas (sin servicios externos)", "principal", K + ["correo", "calendario"], "simple", None, "alta"),
        ("onboarding", "Onboarding", "Incorporación", "Checklist de primer día, accesos, documentación y plan de bienvenida", "principal", K + ["erpnext"], "simple", None, "alta"),
        ("administracion-personal", "Administración de Personal", "Administración de personal", "Datos de nómina para la gestoría, vacaciones, bajas y registro horario", "principal", K + ["erpnext"], "doble", "0 8 25 * *", "alta"),
        ("formacion", "Formación", "Desarrollo", "Plan de formación anual y seguimiento de cursos", "principal", K + ["erpnext"], "simple", "0 8 1 * *", "alta"),
        ("clima-laboral", "Clima Laboral", "Desarrollo", "Encuestas internas periódicas y resumen para dirección", "principal", K, "simple", "0 9 1 */3 *", "alta"),
    ],
    "legal": [
        ("contratos", "Contratos", "Contratos", "Revisa contratos, marca cláusulas de riesgo y mantiene plantillas", "principal", K + ["ficheros"], "doble", None, "alta"),
        ("rgpd", "RGPD", "Protección de datos", "Registro de tratamientos, derechos y revisión legal de cada campaña", "principal", K + ["jev"], "simple", None, "alta"),
        ("cumplimiento", "Cumplimiento", "Cumplimiento normativo", "Calendario de obligaciones legales y requisitos por área de servicio", "principal", K + ["jev"], "libre", "0 8 * * 1", "media"),
        ("responsable-sig", "Responsable del Sistema Integrado", "Sistemas de gestión", "Coordina ENS, 27001, 9001 y 14001 como un único sistema y prepara la revisión por la dirección", "principal", K + ["ficheros"], "doble", "0 8 1 * *", "media"),
        ("ens", "ENS", "Sistemas de gestión", "Categorización, análisis de riesgos, declaración de aplicabilidad y plan de adecuación", "principal", K + ["ficheros"], "doble", None, "media"),
        ("iso27001", "ISO 27001", "Sistemas de gestión", "SGSI, evaluación de riesgos, aplicabilidad de controles y plan de tratamiento", "principal", K + ["ficheros"], "doble", None, "media"),
        ("iso9001", "ISO 9001", "Sistemas de gestión", "Procesos, indicadores, satisfacción, proveedores y competencia", "principal", K + ["ficheros", "erpnext"], "doble", None, "media"),
        ("iso14001", "ISO 14001", "Sistemas de gestión", "Aspectos ambientales, requisitos legales, residuos y emergencias", "principal", K + ["ficheros"], "doble", None, "media"),
        ("documentacion-evidencias", "Documentación y Evidencias", "Auditoría y evidencias", "Control documental y paquete de evidencias por requisito (solo hechos reales)", "vision", K + ["ficheros"], "simple", "0 3 * * 0", "media"),
        ("auditoria-interna", "Auditoría Interna", "Auditoría y evidencias", "Programa anual, listas de comprobación y simulacros por norma", "juez", K + ["ficheros"], "simple", "0 3 1 * *", "media"),
        ("no-conformidades", "No Conformidades y Mejora", "Auditoría y evidencias", "Registra no conformidades y sigue acciones correctivas hasta cerrarlas", "principal", K + ["erpnext", "jev"], "simple", "0 8 * * 1", "media"),
        ("despliegue-departamentos", "Despliegue en Departamentos", "Auditoría y evidencias", "Convierte cada política en tareas, flujos y registros por departamento", "principal", K + ["erpnext"], "simple", None, "media"),
    ],
    "tecnologia": [
        ("infraestructura", "Infraestructura", "Infraestructura", "Monitoriza el servidor, copias de seguridad y actualizaciones", "rapido", K, "simple", "0 * * * *", "alta"),
        ("seguridad", "Seguridad", "Seguridad", "Revisa accesos y registros y alerta de comportamientos anómalos", "rapido", K, "simple", "*/15 * * * *", "alta"),
        ("web", "Web", "Web y desarrollo", "Mantenimiento de la web 101.cat e incidencias técnicas", "principal", K + ["agent_reach"], "simple", None, "baja"),
        ("datos", "Datos", "Datos", "Integra fuentes y vigila la calidad de los datos", "principal", K + ["erpnext"], "libre", "0 0 * * *", "alta"),
    ],
    "conocimiento": [
        ("bibliotecario", "Bibliotecario", "Base de conocimiento", "Indexa documentos, correos y actas para todos los agentes", "rapido", K + ["ficheros"], "libre", "30 0 * * *", "media"),
        ("procedimientos", "Procedimientos", "Procedimientos", "Redacta y actualiza los procesos internos de cada departamento", "principal", K, "simple", None, "media"),
        ("auditor-cerebro", "Auditor del Cerebro", "Supervisión de agentes", "Revisa una muestra de respuestas de cada agente y propone ajustes", "juez", K + ["jev"], "libre", "0 5 * * *", "media"),
    ],
    "licitaciones": [
        ("director-licitaciones", "Director de Licitaciones", "Vigilancia de oportunidades", "Coordina el ciclo completo de cada concurso y controla todos los plazos; lleva el seguimiento de cada licitación en el CRM (tratos, notas y tareas)", "principal", K + ["calendario", "licitaciones", "erpnext"], "libre", "0 7 * * 1-5", "baja"),
        ("rastreador", "Rastreador", "Vigilancia de oportunidades", "Cada día pide a Viabilidad el informe ir/no ir de las licitaciones detectadas con mejor encaje (tarea del calendario «rastreo_embudo»); no decide ni presenta nada", "rapido", K + ["plataformas_contratacion", "licitaciones", "jev"], "libre", None, "baja"),
        ("viabilidad", "Viabilidad", "Vigilancia de oportunidades", "Puntúa solvencia, plazos, presupuesto, capacidad, competencia y certificaciones; informe ir/no ir", "juez", K + ["licitaciones", "jev"], "libre", None, "baja"),
        ("administrativo-licitaciones", "Administrativo", "Documentación administrativa", "DEUC, declaraciones responsables, solvencia y certificados vigentes", "principal", K + ["ficheros", "licitaciones", "pliegos", "ofertas", "plantillas"], "doble", None, "media"),
        ("presentacion-requerimientos", "Presentación y Requerimientos", "Documentación administrativa", "Calendario, aclaraciones, paquete de oferta listo para que una persona firme y presente, y subsanaciones", "principal", K + ["plataformas_contratacion", "calendario", "correo"], "doble", None, "media"),
        ("analista-pliegos", "Analista de Pliegos", "Oferta técnica", "Extrae requisitos, criterios, puntuación y formato; crea la matriz de cumplimiento", "vision", K + ["licitaciones", "pliegos", "ficheros", "scrapegraph", "jev"], "libre", None, "baja"),
        ("arquitecto-solucion", "Arquitecto de Solución", "Oferta técnica", "Diseña la mejor solución criterio a criterio dentro del presupuesto", "principal", K + ["erpnext", "licitaciones", "pliegos", "ofertas"], "simple", None, "media"),
        ("redactor-memoria", "Redactor de Memoria", "Oferta técnica", "Redacta la memoria con la estructura exacta del pliego, sin mezclar sobres", "principal", K + ["ficheros", "licitaciones", "pliegos", "ofertas"], "simple", None, "media"),
        ("evaluador-ofertas", "Evaluador", "Oferta técnica", "Simula la puntuación de la mesa y detecta incumplimientos excluyentes", "juez", K + ["jev"], "libre", None, "media"),
        ("costes-licitacion", "Costes", "Oferta económica", "Coste real con convenio, subrogaciones, materiales, gastos generales y riesgos", "principal", K + ["erpnext", "cotizador", "licitaciones", "ofertas"], "simple", None, "alta"),
        ("precio-licitacion", "Precio", "Oferta económica", "Simula la fórmula económica y el umbral de baja anormal y propone el precio", "principal", K + ["erpnext", "licitaciones", "ofertas"], "doble", None, "alta"),
        ("inteligencia-competitiva", "Inteligencia Competitiva", "Seguimiento", "Actas de adjudicación, competidores y precios ganadores; plazos de recurso", "principal", K + ["scrapegraph", "plataformas_contratacion", "jev"], "libre", "0 4 * * *", "baja"),
    ],
    "telecom": [
        ("director-telecom", "Director de Telecom", "Acuerdos con mayoristas", "Coordina el departamento, decide el catálogo y sigue margen, altas y bajas", "principal", K + ["erpnext"], "libre", "0 8 * * 1", "media"),
        ("gestor-mayoristas", "Gestor de Mayoristas", "Acuerdos con mayoristas", "Compara y negocia tarifas, comisiones y niveles de servicio con mayoristas", "principal", K + ["correo"], "doble", None, "media"),
        ("catalogo-tarifas", "Catálogo de Tarifas", "Acuerdos con mayoristas", "Oferta de venta con margen (fibra, móvil, centralita, SIP, SD-WAN, SIM M2M)", "principal", K + ["erpnext"], "doble", "0 2 * * 1", "media"),
        ("cobertura-ahorro", "Estudio de Cobertura y Ahorro", "Venta y contratación", "Cobertura por dirección, dimensionado y comparación con la factura actual", "vision", K + ["mayorista", "ficheros"], "libre", None, "media"),
        ("contratacion-telecom", "Contratación", "Venta y contratación", "Contrato, identidad, domiciliación, consentimientos y portabilidades", "principal", K + ["erpnext", "mayorista"], "doble", None, "alta"),
        ("provision", "Provisión", "Provisión y soporte", "Altas con el mayorista, instalación, activación y portabilidades", "rapido", K + ["mayorista", "erpnext"], "simple", "*/30 * * * *", "alta"),
        ("soporte-telecom", "Soporte Telecom", "Provisión y soporte", "Incidencias de línea y tickets con el mayorista dentro de plazo", "rapido", K + ["mayorista", "erpnext"], "simple", None, "alta"),
        ("facturacion-servicios", "Facturación de Servicios", "Facturación y cartera", "Consumos, facturación mensual y conciliación con la factura mayorista", "principal", K + ["mayorista", "erpnext"], "doble", "0 3 1 * *", "alta"),
        ("retencion-cartera", "Retención y Cartera", "Facturación y cartera", "Riesgo de baja, fin de permanencias y paquetes combinados", "principal", K + ["erpnext", "jev"], "simple", "0 9 * * 1", "media"),
        ("cumplimiento-telecom", "Cumplimiento Telecom", "Regulación", "Obligaciones de operador ante la CNMC, consumo, conservación de datos y portabilidad", "principal", K, "libre", "0 8 * * 1", "media"),
    ],
    "areas": [
        ("director-areas", "Director de Áreas de Servicio", "Coordinación", "Coordina especialistas, prioriza áreas según la previsión y diseña paquetes combinados", "principal", K + ["erpnext"], "simple", "0 8 * * 1", "media"),
        ("esp-cctv", "Especialista CCTV", "Seguridad", "Videovigilancia, lectura de matrículas y analítica; equipos y protección de datos", "principal", K + ["erpnext", "cotizador"], "libre", None, "media"),
        ("esp-incendios", "Especialista Contra Incendios", "Seguridad", "Detección y extinción según reglamento y planes de mantenimiento obligatorio", "principal", K + ["erpnext", "cotizador"], "libre", None, "media"),
        ("esp-accesos", "Especialista Control de Accesos", "Seguridad", "Accesos para comunidades, oficinas y aparcamientos; integración con videoportero", "principal", K + ["erpnext", "cotizador"], "libre", None, "media"),
        ("esp-redes", "Especialista Redes", "Conectividad e infraestructuras", "Cableado estructurado, wifi, fibra interior y certificación", "principal", K + ["erpnext", "cotizador"], "libre", None, "media"),
        ("esp-television", "Especialista Televisión e ICT", "Conectividad e infraestructuras", "Antenas e ICT en edificios, proyectos y boletines", "principal", K + ["erpnext", "cotizador"], "libre", None, "media"),
        ("esp-localizacion", "Especialista Localización", "Conectividad e infraestructuras", "Seguimiento de flotas y activos con SIM M2M de Telecom", "principal", K + ["erpnext"], "libre", None, "media"),
        ("esp-renovables", "Especialista Renovables", "Energía y hogar", "Autoconsumo, baterías y recarga; cálculo del ahorro", "principal", K + ["erpnext", "cotizador"], "libre", None, "media"),
        ("esp-domotica", "Especialista Domótica", "Energía y hogar", "Hogar y edificio conectado, eficiencia e integración", "principal", K + ["erpnext", "cotizador"], "libre", None, "media"),
        ("esp-construccion", "Especialista Construcción", "Obra", "Obra civil asociada: canalizaciones, zanjas y pequeñas reformas", "principal", K + ["erpnext", "cotizador"], "libre", None, "media"),
        ("coordinacion-obra", "Coordinación de Obra y Prevención", "Obra", "Plan de seguridad y salud, coordinación con instaladores y documentación de subcontratación", "principal", K + ["ficheros"], "simple", None, "alta"),
        ("mantenimientos", "Mantenimientos Programados", "Servicios recurrentes y tramitación", "Contratos de mantenimiento, calendario de visitas, actas e ingresos recurrentes", "rapido", K + ["erpnext", "calendario"], "simple", "0 6 * * *", "media"),
        ("tramitacion", "Tramitación y Legalizaciones", "Servicios recurrentes y tramitación", "Legalizaciones eléctricas y fotovoltaicas, boletines, ICT y licencias", "principal", K + ["ficheros"], "doble", None, "media"),
        ("ayudas", "Ayudas y Subvenciones", "Servicios recurrentes y tramitación", "Detecta ayudas aplicables a cada cliente y prepara la solicitud", "principal", K + ["scrapegraph", "agent_reach"], "simple", "0 3 * * 2", "baja"),
    ],
}

CAMPOS = ["id", "nombre", "subarea", "tareas", "modelo", "herramientas", "aprobacion", "horario", "sensibilidad"]


def construir() -> tuple[dict, dict]:
    departamentos = {}
    fichas_por_dep = {}
    for dep_id, nombre in DEPARTAMENTOS.items():
        filas = AGENTES[dep_id]
        fichas = []
        for i, fila in enumerate(filas):
            f = dict(zip(CAMPOS, fila))
            f["departamento"] = dep_id
            f["director"] = i == 0
            if f["id"] in INVESTIGAN:
                f["herramientas"] = f["herramientas"] + ["cuaderno"]
            fichas.append(f)
        subareas = list(dict.fromkeys(f["subarea"] for f in fichas))
        departamentos[dep_id] = {
            "nombre": nombre,
            "director": fichas[0]["id"],
            "subareas": subareas,
            "agentes": len(fichas),
        }
        fichas_por_dep[dep_id] = fichas
    return departamentos, fichas_por_dep


def escribir() -> None:
    departamentos, fichas_por_dep = construir()
    (RAIZ / "config" / "agentes").mkdir(parents=True, exist_ok=True)
    cabecera = "# Generado por scripts/generar_fichas.py — edita allí y vuelve a generar.\n"
    with open(RAIZ / "config" / "departamentos.yaml", "w", encoding="utf-8") as fh:
        fh.write(cabecera)
        yaml.safe_dump({"departamentos": departamentos}, fh, allow_unicode=True, sort_keys=False)
    for dep_id, fichas in fichas_por_dep.items():
        with open(RAIZ / "config" / "agentes" / f"{dep_id}.yaml", "w", encoding="utf-8") as fh:
            fh.write(cabecera)
            yaml.safe_dump({"agentes": fichas}, fh, allow_unicode=True, sort_keys=False, width=120)

    total = sum(len(f) for f in fichas_por_dep.values())
    subareas = sum(len(d["subareas"]) for d in departamentos.values())
    lineas = [
        "# Índice de agentes",
        "",
        f"{len(departamentos)} departamentos, {subareas} subáreas y {total} agentes. "
        "Generado por `scripts/generar_fichas.py`.",
        "",
    ]
    for dep_id, fichas in fichas_por_dep.items():
        lineas += [f"## {DEPARTAMENTOS[dep_id]}", "",
                   "| Agente | Subárea | Modelo | Aprobación | Horario | Tareas |",
                   "| --- | --- | --- | --- | --- | --- |"]
        for f in fichas:
            nombre = f"**{f['nombre']}**" if f["director"] else f["nombre"]
            lineas.append(f"| {nombre} | {f['subarea']} | {f['modelo']} | {f['aprobacion']} | "
                          f"{f['horario'] or 'bajo petición'} | {f['tareas']} |")
        lineas.append("")
    (RAIZ / "docs").mkdir(exist_ok=True)
    (RAIZ / "docs" / "AGENTES.md").write_text("\n".join(lineas), encoding="utf-8")
    print(f"{len(departamentos)} departamentos, {subareas} subáreas, {total} agentes")


if __name__ == "__main__":
    escribir()
