"""ARES Funding Intelligence: radar de subvenciones y financiación pública (España, Andorra y Unión Europea).

Capas separadas (cada una se puede cambiar sin tocar las demás):
  conectores/   obtención de datos de cada fuente oficial (contrato común, un fallo no para a las demás)
  normalizar    validación y normalización de fechas, importes, estados y territorios (código puro)
  deduplicar    identificador canónico y resolución de coincidencias entre fuentes
  sincronizar   la tubería de un conector: validar → normalizar → deduplicar → guardar → historial → métricas
  almacen       la base de datos (y una versión en memoria para las pruebas)
  consulta      búsqueda, fichas, «mis oportunidades» y estado de los conectores
  registro      el catálogo de fuentes (config/subvenciones.yaml → funding_sources)

Principios: el código decide estados, plazos y duplicados; la IA, cuando intervenga (fase de análisis documental), solo propone y cita su fuente.
Lo que no se sabe es null, nunca una estimación sin etiquetar.
"""
