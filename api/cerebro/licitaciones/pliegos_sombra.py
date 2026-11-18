"""Análisis «en sombra» de los pliegos: SOLO LECTURA, sin modelo y sin escribir en ninguna tabla operativa.

Cuatro comprobaciones deterministas sobre el texto ya extraído de los pliegos y sobre el plan de la oferta. Solo informan (avisos en la revisión previa, con el interruptor
`PLIEGOS_ANALISIS_SOMBRA` activado); no cambian el plan, ni las secciones, ni las fórmulas, ni los precios:

  detectar_sobres        cuántos sobres (o archivos electrónicos) pide el pliego, con la cita
  fugas_economicas       precio o mejoras valorables por fórmula escritos en una sección que NO es del sobre económico
  rectificaciones        qué documentos corrigen, aclaran o modifican a otros y qué cláusulas tocan (versión vigente)
  sugerir_formulas       qué fórmula de `reglas.FORMULAS` parece describir el pliego (una PERSONA la confirma; el cálculo sigue en `reglas.py`)

El texto del pliego es de terceros: aquí solo se busca con expresiones regulares, nunca se obedece.
"""
from __future__ import annotations

import os
import re
import unicodedata

NUMEROS = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}
LETRAS = {"a": 1, "b": 2, "c": 3, "d": 4}


def activo() -> bool:
    return os.environ.get("PLIEGOS_ANALISIS_SOMBRA", "").strip().lower() in ("1", "true", "si", "sí", "on")


def _sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def _plano(t: str) -> str:
    """Minúsculas, sin acentos y con los espacios colapsados; mantiene la longitud aproximada para poder citar."""
    return " ".join(_sin_acentos(str(t or "")).lower().split())


def _cita(t: str, ini: int, fin: int, margen: int = 70) -> str:
    return " ".join(t[max(0, ini - margen): fin + margen].split())[:240]


# ---- 1. Sobres ----

_RE_UNICO = re.compile(r"\b(?:un\s+)?(?:sobre|archivo electronico)\s+(?:electronico\s+)?unico\b|\bunico\s+(?:sobre|archivo electronico)\b|\bun\s+solo\s+(?:sobre|archivo)\b")
_RE_CUENTA = re.compile(r"\b(\d|un|uno|una|dos|tres|cuatro|cinco)\s+(?:sobres|archivos electronicos|archivos)\b")
_RE_ID = re.compile(r"\b(?:sobre|archivo electronico)\s+(?:electronico\s+)?(?:n(?:umero|[o.])?\s*[.º°]?\s*)?([1-5]|[a-d])\b")


def detectar_sobres(texto: str) -> dict:
    """{numero, via, identificadores, citas}. `via`: «explicito» (el pliego dice «dos sobres», «sobre único»), «identificadores» (se cuentan «sobre A, B, C») o None si no se puede saber."""
    t = _plano(texto)
    citas, explicito = [], []
    for m in _RE_UNICO.finditer(t):
        explicito.append(1)
        citas.append(_cita(t, m.start(), m.end()))
    for m in _RE_CUENTA.finditer(t):
        g = m.group(1)
        n = int(g) if g.isdigit() else NUMEROS[g]
        if 1 <= n <= 5:
            explicito.append(n)
            citas.append(_cita(t, m.start(), m.end()))
    ids = []
    for m in _RE_ID.finditer(t):
        g = m.group(1)
        n = int(g) if g.isdigit() else LETRAS[g]
        if n not in ids:
            ids.append(n)
        if len(citas) < 6:
            citas.append(_cita(t, m.start(), m.end()))
    if explicito:
        # si el pliego dice varias cifras gana la más repetida (empate: la mayor, que es la que obliga a más preparación)
        numero = max(set(explicito), key=lambda x: (explicito.count(x), x))
        return {"numero": numero, "via": "explicito", "identificadores": sorted(ids), "citas": citas[:4]}
    if ids:
        return {"numero": max(ids) if ids == list(range(1, max(ids) + 1)) or len(ids) == max(ids) else len(ids), "via": "identificadores", "identificadores": sorted(ids), "citas": citas[:4]}
    return {"numero": None, "via": None, "identificadores": [], "citas": []}


def comparar_sobres(detectado: dict, sobres_plan: tuple[str, ...] = ("administrativo", "tecnico", "economico")) -> list[dict]:
    """Avisos si el pliego pide un número de sobres distinto de los del plan de la oferta (hoy fijos: administrativo, técnico y económico)."""
    n = detectado.get("numero")
    if n is None:
        return [{"nivel": "ok", "texto": "No se ha podido deducir del pliego cuántos sobres pide: se usa el plan estándar de tres (administrativo, técnico y económico)"}]
    cita = f" («{detectado['citas'][0]}»)" if detectado.get("citas") else ""
    if n == len(sobres_plan):
        return [{"nivel": "ok", "texto": f"El pliego pide {n} sobres, como el plan de la oferta{cita}"}]
    return [{"nivel": "aviso", "texto": f"El pliego parece pedir {n} sobre(s) y la oferta se prepara en {len(sobres_plan)} (administrativo, técnico, económico){cita}: revisa cómo se agrupan antes de presentar"}]


# ---- 2. Fugas de lo económico ----

_RE_IMPORTE = re.compile(r"\d[\d.,]*\s*(?:€|eur\b|euros?\b)")
_RE_BAJA = re.compile(r"\b(?:baja|descuento|rebaja)\s+(?:de[l]?\s+|ofertada\s+)?\d[\d.,]*\s*(?:%|por ?ciento)|\b\d[\d.,]*\s*(?:%|por ?ciento)\s+de\s+(?:baja|descuento|rebaja)")
_RE_PALABRAS_OFERTA = re.compile(r"\b(?:oferta|ofert\w+|precio|baja)\b")
_RE_MEJORA_AUTOMATICA = re.compile(r"\bmejoras?\b[^.]{0,80}\b(?:sin coste|gratuit\w+|sin cargo|valorad\w+ (?:mediante|por) formula|evaluable\w* (?:mediante|por) formula)|\bcriterios? (?:evaluables? )?(?:de forma )?automatic\w+")


_RE_IMPORTE_DEL_PLIEGO = re.compile(r"(?:presupuesto|valor estimado|precio de licitacion|importe de licitacion|base de licitacion|tipo de licitacion)[^.\d]{0,60}$")
_RE_MEJORAS_EN_ECONOMICO = re.compile(r"\bmejoras?\b[^.]{0,160}\bsobre\s+(?:electronico\s+)?(?:c|3|economico)\b|\bsobre\s+(?:electronico\s+)?(?:c|3|economico)\b[^.]{0,160}\bmejoras?\b")


def mejoras_van_en_el_economico(texto_pliego: str) -> bool:
    """¿Manda el propio pliego las mejoras valorables por fórmula al sobre económico? Si no lo dice, no se asume: en muchos pliegos las mejoras van en otro sobre."""
    return bool(_RE_MEJORAS_EN_ECONOMICO.search(_plano(texto_pliego)))


def fugas_economicas(secciones: list[dict], mejoras_en_economico: bool = False) -> list[dict]:
    """Secciones que NO son del sobre económico y dejan ver el precio de la oferta (importes, baja) o mejoras valorables por fórmula. En los pliegos con sobres separados, adelantar el precio
    en el sobre administrativo o técnico puede excluir la oferta. Cada salida: {sobre, clave, titulo, tipo, fragmento}."""
    out = []
    for s in secciones:
        if s.get("sobre") == "economico":
            continue
        crudo = " ".join(str(s.get("contenido") or "").split())
        t = _plano(crudo)
        halladas = []
        for m in _RE_IMPORTE.finditer(t):
            frase = t[max(0, m.start() - 120): m.end() + 60]
            if _RE_IMPORTE_DEL_PLIEGO.search(t[max(0, m.start() - 70): m.start()]):
                continue      # «presupuesto de licitación (372.500 €)»: es un dato público del pliego, no el precio de la oferta
            if _RE_PALABRAS_OFERTA.search(frase):
                halladas.append(("precio", m))
                break
        for m in _RE_BAJA.finditer(t):
            halladas.append(("baja", m))
            break
        if mejoras_en_economico:
            for m in _RE_MEJORA_AUTOMATICA.finditer(t):
                halladas.append(("mejora_automatica", m))
                break
        for tipo, m in halladas:
            out.append({"sobre": s.get("sobre"), "clave": s.get("clave"), "titulo": s.get("titulo"), "tipo": tipo, "fragmento": _cita(t, m.start(), m.end(), 50)})
    return out


def avisos_fugas(fugas: list[dict]) -> list[dict]:
    if not fugas:
        return [{"nivel": "ok", "texto": "Ninguna sección de los sobres administrativo y técnico deja ver precio ni mejoras valorables por fórmula"}]
    nombre = {"precio": "un importe de la oferta", "baja": "la baja ofertada", "mejora_automatica": "mejoras valorables por fórmula"}
    return [{"nivel": "aviso", "texto": f"La sección «{f['titulo']}» del sobre {f['sobre']} deja ver {nombre[f['tipo']]} («{f['fragmento']}»): en el pliego esto va en el sobre económico"} for f in fugas]


# ---- 4. Tipo de documento, rectificaciones y versión vigente ----

TIPOS = ("rectificacion", "aclaracion", "pcap", "ppt", "modelo", "plano", "memoria", "otro")
_REGLAS_TIPO = (("rectificacion", r"rectific|correccion de errores|corrigenda|modificacion del pliego|modificacion de los pliegos|fe de erratas"),
                ("aclaracion", r"aclaracion|respuesta a (?:las )?consultas|preguntas y respuestas|consultas formuladas"),
                ("pcap", r"\bpcap\b|clausulas administrativas particulares|pliego administrativo|pliego de clausulas administrativas"),
                ("ppt", r"\bppt\b|\bpptp\b|prescripciones tecnicas|pliego tecnico"),
                ("modelo", r"modelo de (?:proposicion|oferta|declaracion)|\bdeuc\b|anexo [ivx\d]+\b"),
                ("plano", r"\bplanos?\b|planimetr"),
                ("memoria", r"\bmemoria\b|proyecto de ejecucion|estudio de seguridad"))
_RE_FECHA_NUM = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})\b")
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
_RE_FECHA_TXT = re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(_MESES) + r")\s+de\s+(20\d{2})\b")
_RE_CLAUSULA = re.compile(r"\b(?:clausula|apartado|articulo|anexo|epigrafe)\s+(\d+(?:\.\d+){0,3}|[ivx]+)\b")


def clasificar_documento(nombre: str, texto_inicio: str = "") -> str:
    """El tipo de un documento del pliego por su nombre y las primeras líneas. Gana la rectificación o aclaración sobre el resto (un «PCAP rectificado» es una rectificación)."""
    n, t = _plano(nombre), _plano(texto_inicio)[:1500]
    for tipo, patron in _REGLAS_TIPO:
        if re.search(patron, n):
            return tipo
    for tipo, patron in _REGLAS_TIPO[:2]:
        if re.search(patron, t[:600]):
            return tipo
    for tipo, patron in _REGLAS_TIPO[2:]:
        if re.search(patron, t):
            return tipo
    return "otro"


def _fecha(t: str) -> str | None:
    m = _RE_FECHA_TXT.search(t)
    if m:
        return f"{int(m.group(3)):04d}-{_MESES.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}"
    m = _RE_FECHA_NUM.search(t)
    if m and 1 <= int(m.group(1)) <= 31 and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def rectificaciones(documentos: list[dict]) -> list[dict]:
    """De {n, nombre, texto}: los documentos que rectifican o aclaran a otros, con su fecha, las cláusulas que dicen tocar y la cita. Ordenados del más antiguo al más reciente (el último manda).
    El pliego que sigue vigente es el original MÁS lo que digan estos, en ese orden."""
    out = []
    for d in documentos:
        tipo = d.get("tipo") or clasificar_documento(d.get("nombre", ""), d.get("texto", ""))
        if tipo not in ("rectificacion", "aclaracion"):
            continue
        t = _plano(d.get("texto", ""))[:20000]
        refs = []
        for m in _RE_CLAUSULA.finditer(t):
            r = f"{m.group(0)}"
            if r not in refs:
                refs.append(r)
        gatillo = re.search(r"(?:se modifica|queda modificad|se sustituye|queda sustituid|se rectifica|donde dice|se corrige|se anula)", t)
        out.append({"n": d.get("n"), "nombre": d.get("nombre"), "tipo": tipo, "fecha": _fecha(t[:3000]), "clausulas": refs[:12],
                    "cita": _cita(t, gatillo.start(), gatillo.end(), 90) if gatillo else ""})
    return sorted(out, key=lambda r: (r["fecha"] or "9999", r["n"] or 0))


def avisos_rectificaciones(lista: list[dict]) -> list[dict]:
    if not lista:
        return [{"nivel": "ok", "texto": "No hay rectificaciones ni aclaraciones entre los documentos del pliego"}]
    out = []
    for r in lista:
        tocan = ", ".join(r["clausulas"][:6]) if r["clausulas"] else "sin cláusulas identificadas"
        out.append({"nivel": "aviso", "texto": f"«{r['nombre']}» ({r['tipo']}{', ' + r['fecha'] if r['fecha'] else ', sin fecha legible'}) modifica o aclara: {tocan}. Lo que diga prevalece sobre el pliego original: léelo antes de apoyarte en esas cláusulas"})
    return out


# ---- 5. Fórmulas de puntuación sugeridas ----

_RE_PUNTUACION = re.compile(r"formula|puntuacion|se valorara|se puntuara|se otorgaran \d+ puntos")
VENTANA_FORMULA = 600       # lo que se mira tras la palabra clave: la fórmula y la definición de sus letras ocupan varias líneas


def sugerir_formulas(texto: str) -> list[dict]:
    """Sugerencias de {formula (de reglas.FORMULAS), puntos_precio?, baja_tope_pct?, cita}. Son PISTAS para que una persona las confirme en «Reglas de precio»: no se guardan ni se aplican solas.
    Una sugerencia por fórmula distinta (el mismo párrafo suele nombrarla varias veces)."""
    t = _plano(texto)
    out = []
    for m in _RE_PUNTUACION.finditer(t):
        frase = t[m.start(): m.start() + VENTANA_FORMULA]
        formula = None
        if re.search(r"proporcional\w* inversa|inversamente proporcional|\(1 ?- ?r\)|\(1 ?- ?b\)|oferta mas baja .*dividid", frase):
            formula = "inversa"
        elif re.search(r"proporcional\w* (?:directa )?a la baja|baja de la oferta .*mayor baja|(?:mayor|mejor|maxima) baja|baja .*/ ?baja", frase):
            formula = "proporcional_baja"
        elif re.search(r"(?:baja|descuento).{0,40}(?:maxim|tope|umbral|a partir de)|(?:maxim|tope|umbral).{0,40}(?:baja|descuento)|lineal", frase):
            formula = "lineal_umbral"
        if not formula or any(o["formula"] == formula for o in out):
            continue
        s = {"formula": formula, "cita": _cita(t, m.start(), m.start() + 160, 0)}
        p = re.search(r"(\d{1,3}(?:[.,]\d+)?)\s*puntos", t[max(0, m.start() - 160): m.start() + 300])
        if p:
            s["puntos_precio"] = float(p.group(1).replace(",", "."))
        if formula == "lineal_umbral":
            u = re.search(r"(\d{1,2}(?:[.,]\d+)?)\s*(?:%|por ?ciento)", frase)
            if u:
                s["baja_tope_pct"] = float(u.group(1).replace(",", "."))
        out.append(s)
        if len(out) >= 3:
            break
    return out


def avisos_formulas(sugerencias: list[dict], reglas_anotadas: dict | None) -> list[dict]:
    if reglas_anotadas:
        return []
    if not sugerencias:
        return [{"nivel": "ok", "texto": "No se ha reconocido ninguna fórmula de puntuación del precio en los pliegos: anótala a mano en «Reglas de precio» si el pliego la trae"}]
    s = sugerencias[0]
    extra = (f", {s['puntos_precio']:g} puntos" if s.get("puntos_precio") else "") + (f", baja tope {s['baja_tope_pct']:g} %" if s.get("baja_tope_pct") else "")
    return [{"nivel": "aviso", "texto": f"El pliego parece puntuar el precio con la fórmula «{s['formula']}»{extra} («{s['cita'][:140]}»). Confírmalo en «Reglas de precio»: sin reglas anotadas el simulador supone que gana la oferta más barata"}]


# ---- Todo junto (para la revisión previa) ----

def revisar(documentos: list[dict], secciones: list[dict], reglas_anotadas: dict | None = None) -> list[dict]:
    """Los avisos de las cuatro comprobaciones. `documentos`: [{n, nombre, texto}] con el texto completo de cada uno; `secciones`: las de la oferta con su contenido."""
    todo = "\n".join(str(d.get("texto") or "") for d in documentos)
    # los sobres, mejor en el PCAP; si no hay PCAP identificado, en todo el texto
    pcap = "\n".join(str(d.get("texto") or "") for d in documentos if clasificar_documento(d.get("nombre", ""), d.get("texto", "")) == "pcap") or todo
    return (comparar_sobres(detectar_sobres(pcap)) + avisos_fugas(fugas_economicas(secciones, mejoras_van_en_el_economico(pcap))) + avisos_rectificaciones(rectificaciones(documentos))
            + avisos_formulas(sugerir_formulas(pcap), reglas_anotadas))


async def revisar_licitacion(motor_id: str, documentos=None, secciones=None, reglas_anotadas=None) -> list[dict]:
    """La revisión en sombra de una licitación, leyendo SOLO de las tablas de pliegos, de la oferta y de las reglas (sin escribir nada). Si algo falla, un aviso, nunca una excepción."""
    from . import ofertas, pliegos, reglas as R
    try:
        if documentos is None:
            async with await pliegos._conectar() as conn:
                cur = await conn.execute("SELECT d.n, d.nombre, string_agg(p.texto, E'\\n' ORDER BY p.pagina) AS texto FROM pliegos_documentos d LEFT JOIN pliegos_paginas p ON p.documento_id = d.id "
                                         "WHERE d.motor_id = %s AND d.estado IN ('limpio', 'con_macros') GROUP BY d.id, d.n, d.nombre ORDER BY d.n", [motor_id])
                documentos = [{"n": f["n"], "nombre": f["nombre"], "texto": f["texto"] or ""} for f in await cur.fetchall()]
        if secciones is None:
            secciones = (await ofertas.leer(motor_id, con_contenido=True)).get("secciones") or []
        if reglas_anotadas is None:
            reglas_anotadas = await R.leer(motor_id)
        if not documentos:
            return [{"nivel": "ok", "texto": "Análisis en sombra: aún no hay pliegos analizados que revisar"}]
        return revisar(documentos, secciones, reglas_anotadas)
    except Exception as e:      # noqa: BLE001 — es un extra de solo lectura: no puede romper la revisión previa
        return [{"nivel": "ok", "texto": f"Análisis en sombra no disponible ({type(e).__name__})"}]
