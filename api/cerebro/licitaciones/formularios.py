"""Plantillas de la documentación administrativa de una licitación (declaración responsable, anexos…): detectar sus huecos y rellenarlos SIN rehacer el documento.

Los concursos traen sus propias plantillas y hay que rellenarlas tal cual: mismo texto, mismo formato, mismos anexos. Aquí se edita una COPIA del documento original, tocando solo el texto de
los huecos (el original no se modifica), de modo que lo que sale está listo para revisar y firmar con certificado digital.

  Word (.docx)  huecos de texto (___, …, ....), celdas vacías junto a su etiqueta, controles de contenido de texto. Se edita el XML con cambios quirúrgicos (no se vuelve a generar el fichero)
                para no perder estilos, tablas, cabeceras ni nada de lo que lleve.
  PDF           campos de formulario (AcroForm). Un PDF sin campos no se puede rellenar así: se dice, y se pide la versión en Word.

Este módulo no sabe nada de la empresa ni de la base de datos: detecta, propone qué dato corresponde a cada hueco y rellena con los valores que se le dan. Quién decide los valores y de dónde
salen (el ERP) está en plantillas.py. Un documento de terceros es hostil por defecto: se limita lo que se descomprime y no se usa ningún analizador de XML en la entrada (solo expresiones regulares).
Se ejecuta en un proceso aparte con límites (ver `ejecutar_aislado`)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_XML = 30 << 20               # lo que se admite descomprimir de word/document.xml
MAX_TOTAL = 300 << 20            # y de todo el fichero
MAX_ENTRADAS = 3000
MAX_CAMPOS = 400
FORMATOS = ("docx", "pdf")
SIN_DATO = "al_firmar"           # clave especial: lo completa quien firma (la fecha)

RE_P = re.compile(r"<w:p(?:\s[^>]*?)?(?<!/)>.*?</w:p>", re.S)
RE_T = re.compile(r"<w:t(?:\s[^>]*?)?(?<!/)>([^<]*)</w:t>")
RE_T_ELEMENTO = re.compile(r"<w:t(?:\s[^>]*?)?(?<!/)>[^<]*</w:t>")
RE_TOKEN = re.compile(r"<w:t(?:\s[^>]*?)?(?<!/)>[^<]*</w:t>|<w:tab\s*/>|<w:br\s*/>|<w:noBreakHyphen\s*/>")
RE_TR = re.compile(r"<w:tr(?:\s[^>]*?)?(?<!/)>.*?</w:tr>", re.S)
RE_TC = re.compile(r"<w:tc(?:\s[^>]*?)?(?<!/)>.*?</w:tc>", re.S)
RE_SDT = re.compile(r"<w:sdt>.*?</w:sdt>", re.S)
RE_P_VACIO = re.compile(r"<w:p(\s[^>]*?)?/>")
RE_BLANCO = re.compile(r"_{3,}|(?:\.\s?){4,}|…{2,}|(?<![\w.])\.{4,}")
RE_CASILLA = re.compile(r"☐|\[\s?\]")
RE_FECHA = re.compile(r"(?i)\ba\b\s*[_.…\s]{2,}\s*de\s*[_.…\s]{3,}\s*de\s*(?:20)?[_.…\s\d]*")
RE_ANEXO = re.compile(r"(?i)^\s*(anexo|annex|anexe|modelo|model|formulario|declaraci[oó]n responsable)\b.{0,110}$")
RE_OPCIONAL = re.compile(r"(?i)\b(fax|opcional|en su caso|si procede|si lo hubiera|si lo tuviera|si existe)\b")


class ErrorFormulario(ValueError):
    pass


def _sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t or "") if unicodedata.category(c) != "Mn")


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", _sin_acentos(t).lower()).strip()


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _unesc(t: str) -> str:
    return t.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _valor_xml(v: str) -> str:
    """Un valor listo para ir dentro de <w:t>: una sola línea, sin caracteres de control y con el XML escapado."""
    return _esc(_CTRL.sub("", re.sub(r"\s+", " ", str(v))).strip())


# ---- Emparejar un hueco con el dato que le corresponde ----

# (patrón sobre la etiqueta normalizada —lo que hay justo antes del hueco—, clave). El orden importa: lo más específico primero.
REGLAS = (
    # El precio y sus derivados (los pone una persona al fijar el precio de la oferta): «por el precio de ___ euros», «(en letra ___)», «IVA (21 %): ___», «Importe (IVA incluido): ___»
    (r"(en letras?|en letra y cifra|cantidad en letras?)[\s:,)]*$", "oferta.precio_letras"),
    (r"(importe|precio|total)\b.{0,50}(iva incluido|con iva|incluido (el )?iva|iva incl\.?)[\s:,)]*$", "oferta.precio_con_iva"),
    (r"((importe|cuota|cantidad) (del|de) iva|(^|\s)iva\s*\(\s*\d{1,2}(,\d+)?\s*%\s*\))\s*[:,]?$", "oferta.iva"),
    (r"((tipo|porcentaje|%)( de)? iva|(^|\s)iva\s*(\(%\)|%))\s*[:,]?$", "oferta.iva_pct"),
    (r"((por )?(el )?(precio|importe)( de la oferta| ofertado| del contrato| de licitacion)?( \(?(sin iva|iva excluido|excluido (el )?iva|iva no incluido|antes de iva)\)?)?"
     r"|por (un )?importe de|por la (cantidad|suma) de|oferta (la cantidad|el precio) de|ofrece (el precio|la cantidad) de)\s*(de|:|,)?\s*$", "oferta.precio"),
    (r"(d\.?\s*/\s*d(n|ñ)?a\.?|don|dona|d\.|dna\.?|nombre y apellidos|apellidos y nombre|el abajo firmante|firmante|apoderado/a?|representante legal)\s*[:,]?$", "representante.nombre"),
    (r"(en representacion de|en nombre de|razon social|denominacion social|denominacion de la (empresa|sociedad|entidad)|nombre de la (empresa|sociedad|entidad)|empresa|sociedad|entidad|licitador|contratista|empresario)\s*[:,]?$",
     "empresa.razon_social"),
    (r"(nombre( y apellidos)?|apellidos) (del|de la) (representante|firmante|apoderad[ao])( legal)?\s*[:,]?$", "representante.nombre"),
    (r"(dni|d\.n\.i\.?|nie|nif)\b.{0,30}(representante|firmante|apoderad[ao])( legal)?\s*[:,]?$", "representante.dni"),
    (r"(dni|d\.n\.i\.?|nie|documento nacional de identidad)\s*(n[º°o.]|numero)?\s*[:,]?$", "representante.dni"),
    (r"(nif|cif|n\.i\.f\.?|c\.i\.f\.?|nif\s*/\s*cif|cif\s*/\s*nif)\s*(n[º°o.]|numero)?\s*[:,]?$", "nif"),
    (r"(codigo postal|c\.?\s?p\.?)\s*[:,]?$", "empresa.cp"),
    (r"(localidad|municipio|poblacion|ciudad)\s*[:,]?$", "empresa.localidad"),
    (r"provincia\s*[:,]?$", "empresa.provincia"),
    (r"(domicilio|direccion|sede|domiciliad[ao])( social| fiscal)?( en)?\s*[:,]?$", "empresa.domicilio"),
    (r"(telefono|tfno\.?|tel\.?|movil|telefono movil)\s*[:,]?$", "empresa.telefono"),
    (r"(correo( electronico)?|e-?mail|email|direccion de correo( electronico)?)\s*[:,]?$", "empresa.email"),
    (r"(en calidad de|con el cargo de|cargo|caracter|actuando como|en su condicion de|en su calidad de)\s*[:,]?$", "representante.cargo"),
    (r"(poder|escritura|notario|protocolo)\b.*$", "representante.poder"),
    (r"(registro mercantil|inscrita en|inscripcion)\b.*$", "empresa.registro"),
    (r"(numero de expediente|n[º°o.]? de expediente|expediente( n[º°o.])?|referencia)\s*[:,]?$", "licitacion.expediente"),
    (r"(organo de contratacion)\s*[:,]?$", "licitacion.organo"),
    (r"(objeto del contrato|contrato de|licitacion denominada|denominad[ao]|para la contratacion de|objeto)\s*[:,]?$", "licitacion.objeto"),
)
_REP = re.compile(r"en representacion|en nombre de|actuando en nombre")


def emparejar(etiqueta: str, antes: str = "", en_tabla: bool = False, despues: str = "") -> str | None:
    """La clave del dato que corresponde a un hueco, mirando lo que hay justo antes (`etiqueta`) y todo el texto anterior (`antes`). None si no está claro: lo completa una persona
    (o un agente que elige la clave, nunca el valor)."""
    e = _norm(etiqueta)[-90:]
    todo = _norm(antes)
    if RE_FECHA.search(antes + " __"):
        return None
    if re.search(r"(^|\s)(en|lugar)\s*[:,]?$", e) and len(todo) < 12:
        return "empresa.localidad"                                   # «En ______, a … de … de 2026»
    for patron, clave in REGLAS:
        if re.search(patron, e):
            if clave == "oferta.precio_letras" and re.match(r"\s*(euros?\b|€|eur\b)", despues, re.I):
                return "oferta.precio_letras_sin_unidad"                  # el documento ya trae «euros» detrás del hueco: solo se escribe la cifra en letra
            if clave == "nif":
                if re.search(r"cif", e):
                    return "empresa.nif"                                   # un CIF es siempre de una empresa (y «NIF/CIF» también)
                if en_tabla:
                    return "representante.dni" if re.search(r"representante|firmante|apoderad", e) else "empresa.nif"
                return "empresa.nif" if _REP.search(todo) else "representante.dni"      # «D. …, con NIF …, en representación de …, con NIF …»
            return clave
    return None


# ---- Word ----

def _leer_docx(ruta: Path) -> tuple[zipfile.ZipFile, str]:
    try:
        z = zipfile.ZipFile(ruta)
    except (zipfile.BadZipFile, OSError):
        raise ErrorFormulario("El documento Word no se puede abrir (¿está dañado?)") from None
    infos = z.infolist()
    if len(infos) > MAX_ENTRADAS or sum(i.file_size for i in infos) > MAX_TOTAL:
        raise ErrorFormulario("El documento Word es demasiado grande para procesarlo")
    try:
        info = z.getinfo("word/document.xml")
    except KeyError:
        raise ErrorFormulario("No es un documento Word válido (falta word/document.xml)") from None
    if info.file_size > MAX_XML:
        raise ErrorFormulario("El texto del documento Word es demasiado grande para procesarlo")
    return z, z.read(info).decode("utf-8")


def _subrayado(xml: str, pos_t: int) -> bool:
    """¿El texto que empieza en `pos_t` está en un trozo (<w:r>) subrayado?"""
    ini = max(xml.rfind("<w:r>", 0, pos_t), xml.rfind("<w:r ", 0, pos_t))
    return ini >= 0 and re.search(r'<w:u\b(?![^>]*w:val="none")', xml[ini:pos_t]) is not None


class _Parrafo:
    """Un párrafo: su texto continuo y los trozos <w:t> que lo forman (con su posición en el XML, para editarlos sin tocar nada más)."""

    def __init__(self, xml: str, inicio: int):
        self.inicio, self.trozos, partes, pos = inicio, [], [], 0
        self.subrayados: list[tuple[int, int]] = []         # huecos hechos con espacios subrayados (lo más habitual en las plantillas de las administraciones)
        for m in RE_TOKEN.finditer(xml):
            if m.group(0).startswith("<w:t") and not m.group(0).startswith(("<w:tab", "<w:tbl")):
                texto = _unesc(RE_T.match(m.group(0)).group(1))
                self.trozos.append({"ini": inicio + m.start(), "fin": inicio + m.end(), "pos": pos, "texto": texto, "cambiado": False})
                if len(texto) >= 2 and not texto.strip() and _subrayado(xml, m.start()):
                    if self.subrayados and self.subrayados[-1][1] == pos:
                        self.subrayados[-1] = (self.subrayados[-1][0], pos + len(texto))       # trozos subrayados seguidos: un solo hueco
                    else:
                        self.subrayados.append((pos, pos + len(texto)))
                partes.append(texto)
                pos += len(texto)
            else:
                partes.append(" ")
                pos += 1
        self.subrayados = [(a, b) for a, b in self.subrayados if b - a >= 3]
        self.texto = "".join(partes)

    def sustituir(self, a: int, b: int, valor: str) -> None:
        """Pone `valor` en lugar de texto[a:b], repartiendo el cambio entre los trozos que ocupa ese rango."""
        primero = True
        for t in self.trozos:
            ini, fin = t["pos"], t["pos"] + len(t["texto"])
            if fin <= a or ini >= b:
                continue
            x, y = max(a, ini) - ini, min(b, fin) - ini
            t["texto"] = t["texto"][:x] + (valor if primero else "") + t["texto"][y:]
            t["cambiado"] = True
            primero = False
        if primero:                                                   # el hueco cae en un tab/salto: no hay dónde escribirlo
            raise ErrorFormulario("El hueco no está en un texto editable")

    def ediciones(self) -> list[tuple[int, int, str]]:
        return [(t["ini"], t["fin"], f'<w:t xml:space="preserve">{_esc(t["texto"])}</w:t>') for t in self.trozos if t["cambiado"]]


def _texto_xml(xml: str) -> str:
    xml = re.sub(r"<w:instrText[^>]*>.*?</w:instrText>", " ", xml, flags=re.S)           # las instrucciones de campo (FORMTEXT…) no son texto que se lea
    return _norm(_unesc(re.sub(r"<[^>]+>", "", re.sub(r"<w:tab\s*/>|<w:br\s*/>|</w:p>|</w:tc>", " ", xml))))


def _celdas_vacias(x: str, fuera: list[tuple[int, int]]) -> list[dict]:
    """Celdas vacías que están a la derecha de una celda con texto (etiqueta | hueco): lo típico de «Razón social | ______»."""
    out = []
    for fila in RE_TR.finditer(x):
        txt = fila.group(0)
        if "<w:tbl>" in txt or any(a <= fila.start() < b for a, b in fuera):
            continue
        celdas = list(RE_TC.finditer(txt))
        if not 2 <= len(celdas) <= 4:
            continue
        for i in range(1, len(celdas)):
            c, previa = celdas[i], _texto_xml(celdas[i - 1].group(0))
            if _texto_xml(c.group(0)) == "" and previa and len(previa) <= 120 and not RE_BLANCO.search(previa) and "<w:drawing" not in c.group(0) and "<w:pict" not in c.group(0):
                out.append({"ini": fila.start() + c.start(), "fin": fila.start() + c.end(), "etiqueta": previa})
    return out


def _rellenar_celda(celda_xml: str, valor: str) -> str:
    run = f'<w:r><w:t xml:space="preserve">{_valor_xml(valor)}</w:t></w:r>'
    if "</w:p>" in celda_xml:
        i = celda_xml.index("</w:p>")
        return celda_xml[:i] + run + celda_xml[i:]
    m = RE_P_VACIO.search(celda_xml)
    if m:
        return celda_xml[:m.start()] + f"<w:p{m.group(1) or ''}>{run}</w:p>" + celda_xml[m.end():]
    return celda_xml


def _controles(x: str) -> list[dict]:
    """Controles de contenido de TEXTO con el marcador de posición todavía puesto (o vacíos). Casillas, listas y fechas no se tocan."""
    out = []
    for m in RE_SDT.finditer(x):
        s = m.group(0)
        pr = re.search(r"<w:sdtPr>.*?</w:sdtPr>", s, re.S)
        pr = pr.group(0) if pr else ""
        if re.search(r"<w14:checkbox|<w:dropDownList|<w:comboBox|<w:date\b|<w:picture|<w:docPartObj|<w:group", pr):
            out.append({"ini": m.start(), "fin": m.end(), "especial": True, "etiqueta": "", "tipo": "casilla" if "w14:checkbox" in pr else "otro"})
            continue
        cont = re.search(r"<w:sdtContent>(.*?)</w:sdtContent>", s, re.S)
        if not cont or not RE_T.search(cont.group(1)) and "<w:r>" not in cont.group(1) and "<w:r " not in cont.group(1):
            continue
        marcador = "<w:showingPlcHdr" in pr
        texto = "".join(_unesc(t) for t in RE_T.findall(cont.group(1))).strip()
        if not marcador and texto:
            continue
        alias = re.search(r'<w:alias w:val="([^"]*)"', pr) or re.search(r'<w:tag w:val="([^"]*)"', pr)
        antes = _texto_xml(re.sub(r"<w:p(?:\s[^>]*?)?(?<!/)>", "\n<P>", x[max(0, m.start() - 4000):m.start()]).split("<P>")[-1]) if not alias else ""
        out.append({"ini": m.start(), "fin": m.end(), "especial": False, "etiqueta": _unesc(alias.group(1)) if alias else antes[-90:], "contenido": cont.group(1)})
    return out


def _rellenar_control(sdt_xml: str, valor: str) -> str:
    """Pone el valor en el primer texto del control, vacía los demás, quita el marcador de posición y el estilo gris del marcador."""
    v = _valor_xml(valor)
    inicio, fin = sdt_xml.index("<w:sdtContent>"), sdt_xml.index("</w:sdtContent>")
    puesto = []

    def cambia(_m):
        if puesto:
            return '<w:t xml:space="preserve"></w:t>'
        puesto.append(1)
        return '<w:t xml:space="preserve">' + v + "</w:t>"

    cuerpo = RE_T_ELEMENTO.sub(cambia, sdt_xml[inicio:fin])
    cuerpo = re.sub(r'<w:rStyle w:val="PlaceholderText"\s*/>', "", cuerpo)
    return re.sub(r"<w:showingPlcHdr\s*/>", "", sdt_xml[:inicio] + cuerpo + sdt_xml[fin:])


RE_FF = re.compile(r"<w:ffData>.*?</w:ffData>", re.S)


def _campos_antiguos(x: str) -> list[dict]:
    """Campos de formulario antiguos de Word («Texto1», casillas): su resultado es lo que hay entre «separate» y «end». Las listas desplegables no se tocan."""
    out = []
    for m in RE_FF.finditer(x):
        ff = m.group(0)
        casilla = "<w:checkBox" in ff
        if not casilla and "<w:textInput" not in ff:
            continue
        ayuda = re.search(r'<w:(?:statusText|helpText)[^>]*w:val="([^"]*)"', ff)
        parrafo = max(x.rfind("<w:p>", 0, m.start()), x.rfind("<w:p ", 0, m.start()))
        antes = _texto_xml(x[parrafo:m.start()]) if parrafo >= 0 else ""
        etiqueta = (_unesc(ayuda.group(1)) if ayuda and ayuda.group(1).strip() else antes)[-90:]
        if casilla:
            out.append({"ini": m.start(), "fin": m.end(), "casilla": True, "etiqueta": etiqueta, "antes": antes})
            continue
        sep = x.find('w:fldCharType="separate"', m.end())
        fin = x.find('w:fldCharType="end"', sep) if sep >= 0 else -1
        if sep < 0 or fin < 0 or 'w:fldCharType="begin"' in x[m.end():fin]:
            continue                                                  # sin resultado claro o campos anidados: no se toca
        ini_region = x.find("</w:r>", sep)
        ini_region = ini_region + 6 if ini_region >= 0 else -1
        fin_region = max(x.rfind("<w:r>", 0, fin), x.rfind("<w:r ", 0, fin))
        if ini_region < 0 or fin_region < ini_region:
            continue
        out.append({"ini": ini_region, "fin": fin_region, "casilla": False, "etiqueta": etiqueta, "antes": antes})
    return out


def _rellenar_campo_antiguo(region_xml: str, valor: str) -> str:
    """Pone el valor como resultado del campo: en el primer texto que haya (conservando su formato) y vacía los demás; si no hay ninguno, añade un trozo con el valor."""
    v = _valor_xml(valor)
    if not RE_T_ELEMENTO.search(region_xml):
        return region_xml + f'<w:r><w:t xml:space="preserve">{v}</w:t></w:r>'
    puesto = []

    def cambia(_m):
        if puesto:
            return '<w:t xml:space="preserve"></w:t>'
        puesto.append(1)
        return '<w:t xml:space="preserve">' + v + "</w:t>"

    return RE_T_ELEMENTO.sub(cambia, region_xml)


def _titulos_de_anexo(x: str) -> list[tuple[int, str]]:
    """Los títulos de anexo o modelo («ANEXO II. Modelo de proposición económica») y dónde están: cada hueco pertenece al último que tiene delante."""
    out = []
    for m in RE_P.finditer(x):
        t = re.sub(r"\s+", " ", _unesc(re.sub(r"<[^>]+>", "", re.sub(r"<w:tab\s*/>|<w:br\s*/>", " ", m.group(0))))).strip()
        if 3 <= len(t) <= 120 and RE_ANEXO.match(t):
            out.append((m.start(), t[:90]))
    return out


def _anexo_de(titulos: list[tuple[int, str]], pos: int) -> str:
    anexo = ""
    for ini, t in titulos:
        if ini <= pos:
            anexo = t
        else:
            break
    return anexo


def _campos_docx(x: str) -> list[dict]:
    """Todos los huecos del documento, en orden de aparición. Cada uno: id estable, tipo, etiqueta, la clave de dato propuesta y dónde está (para rellenarlo)."""
    campos: list[dict] = []
    titulos = _titulos_de_anexo(x)
    controles = _controles(x)
    fuera = [(c["ini"], c["fin"]) for c in controles]
    celdas = _celdas_vacias(x, fuera)
    en_celda = [(c["ini"], c["fin"]) for c in celdas]
    antiguos = _campos_antiguos(x)
    en_campo = [(c["ini"], c["fin"]) for c in antiguos if not c["casilla"]]
    n = 0

    def nuevo(tipo, orden, **kw):
        nonlocal n
        n += 1
        campos.append({"id": f"{tipo[0]}{n}", "tipo": tipo, "orden": orden, **kw})

    for c in controles:
        if c["especial"]:
            nuevo("casilla" if c["tipo"] == "casilla" else "control", c["ini"], etiqueta="", clave=None, ini=c["ini"], fin=c["fin"], fijo=True, opcional=False)
        else:
            nuevo("control", c["ini"], etiqueta=c["etiqueta"], clave=emparejar(c["etiqueta"], c["etiqueta"]), ini=c["ini"], fin=c["fin"], fijo=False, opcional=bool(RE_OPCIONAL.search(c["etiqueta"])))
    for c in antiguos:
        if c["casilla"]:
            nuevo("casilla", c["ini"], etiqueta=c["etiqueta"], clave=None, ini=c["ini"], fin=c["fin"], fijo=True, opcional=False)
        else:
            nuevo("campo", c["ini"], etiqueta=c["etiqueta"], clave=emparejar(c["etiqueta"], c["antes"]), ini=c["ini"], fin=c["fin"], fijo=False, opcional=bool(RE_OPCIONAL.search(c["etiqueta"])))
    for c in celdas:
        nuevo("celda", c["ini"], etiqueta=c["etiqueta"], clave=emparejar(c["etiqueta"], c["etiqueta"], True), ini=c["ini"], fin=c["fin"], fijo=False, opcional=bool(RE_OPCIONAL.search(c["etiqueta"])))
    for m in RE_P.finditer(x):
        if any(a <= m.start() < b for a, b in fuera) or any(a <= m.start() < b for a, b in en_celda):
            continue
        p = _Parrafo(m.group(0), m.start())
        if not p.texto.strip():
            continue
        fecha = [(f.start(), f.end()) for f in RE_FECHA.finditer(p.texto)]
        blancos = [(b.start(), b.end()) for b in RE_BLANCO.finditer(p.texto)]
        blancos += [(a, z) for a, z in p.subrayados if not any(a < y and x_ < z for x_, y in blancos)]       # espacios subrayados que no sean ya un hueco de rayas o puntos
        for ini_b, fin_b in sorted(blancos):
            if any(a <= m.start() + ini_b < z for a, z in en_campo):
                continue                                                  # lo rellena el campo de formulario, no el texto
            etiqueta, antes = p.texto[max(0, ini_b - 90):ini_b], p.texto[:ini_b]
            if any(a <= ini_b < z for a, z in fecha):
                nuevo("texto", m.start() + ini_b, etiqueta=etiqueta.strip(), clave=SIN_DATO, ini=m.start(), fin=m.end(), a=ini_b, b=fin_b, fijo=False, opcional=False)
                continue
            clave = emparejar(etiqueta, antes, despues=p.texto[fin_b:fin_b + 30])
            nuevo("texto", m.start() + ini_b, etiqueta=etiqueta.strip(), clave=clave, ini=m.start(), fin=m.end(), a=ini_b, b=fin_b, fijo=False,
                  opcional=bool(RE_OPCIONAL.search(etiqueta + " " + p.texto[fin_b:fin_b + 40])))
        for k in RE_CASILLA.finditer(p.texto):
            nuevo("casilla", m.start() + k.start(), etiqueta=p.texto[k.end():k.end() + 80].strip(), clave=None, ini=m.start(), fin=m.end(), a=k.start(), b=k.end(), fijo=True, opcional=False)
    campos.sort(key=lambda c: c["orden"])
    for i, c in enumerate(campos[:MAX_CAMPOS], 1):          # el id sigue el orden del documento, no el de detección
        c["id"] = f"{c['tipo'][0]}{i}"
        c["anexo"] = _anexo_de(titulos, c["orden"])
    if len(campos) > MAX_CAMPOS:
        raise ErrorFormulario(f"El documento tiene más de {MAX_CAMPOS} huecos: no parece una plantilla")
    return campos


def _publico(c: dict) -> dict:
    return {"id": c["id"], "tipo": c["tipo"], "etiqueta": re.sub(r"\s+", " ", c["etiqueta"]).strip()[-90:], "clave": c["clave"], "opcional": c["opcional"], "fijo": c["fijo"],
            "anexo": c.get("anexo", "")}


def detectar_docx(ruta: Path) -> dict:
    z, x = _leer_docx(ruta)
    z.close()
    campos = _campos_docx(x)
    avisos = []
    if "<w:ins " in x or "<w:del " in x:
        avisos.append("El documento tiene cambios sin aceptar (control de cambios): conviene aceptarlos antes de firmar")
    if not campos:
        avisos.append("No se han encontrado huecos que rellenar en este documento")
    return {"formato": "docx", "campos": [_publico(c) for c in campos], "avisos": avisos}


def rellenar_docx(ruta: Path, destino: Path, valores: dict[str, str]) -> dict:
    """Escribe en `destino` una copia del Word con los huecos de `valores` ({id del hueco: texto}) rellenos. El resto del documento queda byte a byte igual."""
    z, x = _leer_docx(ruta)
    campos = {c["id"]: c for c in _campos_docx(x)}
    ediciones: list[tuple[int, int, str]] = []
    hechos, omitidos = [], []
    por_parrafo: dict[int, tuple[_Parrafo, list]] = {}
    for fid, valor in valores.items():
        c = campos.get(fid)
        if c is None or c["fijo"] or valor is None or not str(valor).strip():
            omitidos.append(fid)
            continue
        if c["tipo"] == "texto":
            par = por_parrafo.setdefault(c["ini"], (_Parrafo(x[c["ini"]:c["fin"]], c["ini"]), []))
            par[1].append((c["a"], c["b"], re.sub(r"\s+", " ", _CTRL.sub("", str(valor))).strip()))
        elif c["tipo"] == "celda":
            ediciones.append((c["ini"], c["fin"], _rellenar_celda(x[c["ini"]:c["fin"]], str(valor))))
        elif c["tipo"] == "control":
            ediciones.append((c["ini"], c["fin"], _rellenar_control(x[c["ini"]:c["fin"]], str(valor))))
        elif c["tipo"] == "campo":
            ediciones.append((c["ini"], c["fin"], _rellenar_campo_antiguo(x[c["ini"]:c["fin"]], str(valor))))
        hechos.append(fid)
    for par, cambios in por_parrafo.values():
        for a, b, v in sorted(cambios, reverse=True):                 # de derecha a izquierda, para que las posiciones anteriores no se muevan
            par.sustituir(a, b, v)
        ediciones.extend(par.ediciones())
    ediciones.sort()
    for (a1, b1, _), (a2, _b2, _) in zip(ediciones, ediciones[1:]):
        if b1 > a2:
            raise ErrorFormulario("Dos huecos se solapan: no se rellena el documento para no estropearlo")
    nuevo = x
    for a, b, t in reversed(ediciones):
        nuevo = nuevo[:a] + t + nuevo[b:]
    try:
        ET.fromstring(nuevo)                                           # lo que sale tiene que seguir siendo un XML válido; si no, no se entrega
    except ET.ParseError:
        raise ErrorFormulario("El resultado no es un documento válido: no se entrega") from None
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w") as out:
        for info in z.infolist():
            datos = nuevo.encode("utf-8") if info.filename == "word/document.xml" else z.read(info)
            out.writestr(info, datos, compress_type=info.compress_type)
    z.close()
    tmp.replace(destino)
    return {"rellenados": hechos, "omitidos": omitidos}


# ---- PDF con formulario ----

def _campos_pdf(ruta: Path):
    from pypdf import PdfReader
    try:
        lector = PdfReader(str(ruta))
        if lector.is_encrypted:
            raise ErrorFormulario("El PDF está protegido con contraseña: no se puede rellenar")
        return lector, lector.get_fields() or {}
    except ErrorFormulario:
        raise
    except Exception as e:      # noqa: BLE001 — un PDF hostil o roto puede fallar de muchas maneras
        raise ErrorFormulario(f"El PDF no se puede leer ({type(e).__name__})") from None


def detectar_pdf(ruta: Path) -> dict:
    _, campos = _campos_pdf(ruta)
    out, avisos = [], []
    for i, (nombre, f) in enumerate(campos.items(), 1):
        tipo = str(f.get("/FT", ""))
        etiqueta = str(f.get("/TU") or nombre)
        solo_lectura = bool(int(f.get("/Ff", 0) or 0) & 1)
        if tipo == "/Tx":
            out.append({"id": f"p{i}", "tipo": "texto", "etiqueta": etiqueta[-90:], "clave": emparejar(etiqueta, etiqueta, True), "opcional": bool(RE_OPCIONAL.search(etiqueta)), "fijo": solo_lectura,
                        "nombre": nombre})
        elif tipo in ("/Btn", "/Ch"):
            out.append({"id": f"p{i}", "tipo": "casilla", "etiqueta": etiqueta[-90:], "clave": None, "opcional": False, "fijo": True, "nombre": nombre})
    if not campos:
        avisos.append("Este PDF no tiene campos de formulario: no se puede rellenar automáticamente. Pide la plantilla en Word o rellénala a mano")
    return {"formato": "pdf", "campos": [{k: v for k, v in c.items() if k != "nombre"} for c in out], "avisos": avisos, "_nombres": {c["id"]: c["nombre"] for c in out}}


def rellenar_pdf(ruta: Path, destino: Path, valores: dict[str, str]) -> dict:
    from pypdf import PdfWriter
    from pypdf.generic import BooleanObject, NameObject
    det = detectar_pdf(ruta)
    nombres = det["_nombres"]
    permitidos = {c["id"] for c in det["campos"] if c["tipo"] == "texto" and not c["fijo"]}
    asignar, hechos, omitidos = {}, [], []
    for fid, v in valores.items():
        if fid in permitidos and v is not None and str(v).strip():
            asignar[nombres[fid]] = re.sub(r"\s+", " ", _CTRL.sub("", str(v))).strip()
            hechos.append(fid)
        else:
            omitidos.append(fid)
    lector, _ = _campos_pdf(ruta)
    w = PdfWriter(clone_from=lector)
    for pagina in w.pages:
        w.update_page_form_field_values(pagina, asignar, auto_regenerate=False)
    w._root_object["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(True)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    with open(tmp, "wb") as f:
        w.write(f)
    tmp.replace(destino)
    return {"rellenados": hechos, "omitidos": omitidos}


# ---- Entrada común y ejecución aislada ----

def detectar(ruta: Path, formato: str) -> dict:
    if formato == "docx":
        return detectar_docx(ruta)
    if formato == "pdf":
        r = detectar_pdf(ruta)
        r.pop("_nombres", None)
        return r
    raise ErrorFormulario(f"De momento solo se rellenan plantillas en Word (.docx) y PDF con formulario; este es {formato}: hay que rellenarlo a mano")


def rellenar(ruta: Path, formato: str, destino: Path, valores: dict[str, str]) -> dict:
    if formato == "docx":
        return rellenar_docx(ruta, destino, valores)
    if formato == "pdf":
        return rellenar_pdf(ruta, destino, valores)
    raise ErrorFormulario(f"De momento solo se rellenan plantillas en Word (.docx) y PDF con formulario; este es {formato}: hay que rellenarlo a mano")


MAX_MIEMBROS = 500
MAX_MIEMBRO = 60 << 20
RATIO_MAX = 200
SIN_SOPORTE = (".ods", ".xls", ".xlsx", ".docm")
CONVERTIBLES = {".doc": b"\xd0\xcf\x11\xe0", ".odt": b"PK", ".rtf": b"{\\rtf"}      # se convierten a Word antes de rellenarlos (conversion.py)


def extraer_zip(ruta: Path, destino: Path) -> dict:
    """Abre un paquete ZIP de documentación y deja en `destino` los documentos que se pueden rellenar (Word y PDF con formulario), sin salirse de esa carpeta. Devuelve
    {"miembros": [{"miembro", "formato", "ruta", "bytes"}], "avisos": [...]}. Un ZIP es de terceros: se limita el número de ficheros, su tamaño y su razón de compresión, se descartan nombres con rutas
    raras y no se abren ZIP dentro de ZIP."""
    try:
        z = zipfile.ZipFile(ruta)
    except (zipfile.BadZipFile, OSError):
        raise ErrorFormulario("El ZIP no se puede abrir (¿está dañado?)") from None
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > MAX_MIEMBROS:
        raise ErrorFormulario(f"El ZIP tiene más de {MAX_MIEMBROS} ficheros: no parece un paquete de documentación")
    if sum(i.file_size for i in z.infolist()) > MAX_TOTAL:
        raise ErrorFormulario("El ZIP es demasiado grande al descomprimirlo")
    destino.mkdir(parents=True, exist_ok=True, mode=0o700)
    miembros, avisos = [], []
    for k, info in enumerate(infos, 1):
        nombre = info.filename
        partes = nombre.replace("\\", "/").split("/")
        if nombre.startswith(("/", "\\")) or ".." in partes or any(c in nombre for c in "\x00:"):
            avisos.append(f"«{_CTRL.sub('', nombre)[:80]}» se ha ignorado: nombre no válido")
            continue
        ext = Path(nombre).suffix.lower()
        if ext in SIN_SOPORTE:
            avisos.append(f"«{nombre[:80]}» no se rellena solo (formato {ext[1:]}): hay que rellenarlo a mano o pedirlo en Word")
            continue
        if ext not in (".docx", ".pdf") and ext not in CONVERTIBLES:
            continue
        if info.file_size > MAX_MIEMBRO or (info.compress_size > 0 and info.file_size / info.compress_size > RATIO_MAX):
            avisos.append(f"«{nombre[:80]}» se ha ignorado: demasiado grande o sospechoso")
            continue
        with z.open(info) as f:
            datos = f.read(MAX_MIEMBRO + 1)
        if len(datos) > MAX_MIEMBRO:
            avisos.append(f"«{nombre[:80]}» se ha ignorado: demasiado grande")
            continue
        if ext in CONVERTIBLES:
            if not datos.startswith(CONVERTIBLES[ext]):
                avisos.append(f"«{nombre[:80]}» se ha ignorado: su contenido no es {ext[1:]}")
                continue
            salida = destino / f"{k:03d}{ext}"
            salida.write_bytes(datos)
            miembros.append({"miembro": "/".join(partes)[:200], "formato": ext[1:], "ruta": str(salida), "bytes": len(datos)})
            continue
        formato = "pdf" if datos[:5] == b"%PDF-" else ("docx" if datos[:2] == b"PK" else None)
        if formato is None or (ext == ".docx") != (formato == "docx"):
            avisos.append(f"«{nombre[:80]}» se ha ignorado: su contenido no es {ext[1:]}")
            continue
        salida = destino / f"{k:03d}.{formato}"
        salida.write_bytes(datos)
        miembros.append({"miembro": "/".join(partes)[:200], "formato": formato, "ruta": str(salida), "bytes": len(datos)})
    return {"miembros": miembros, "avisos": avisos}


def poner_limites() -> None:
    try:
        import resource
    except ImportError:      # pragma: no cover
        return
    for limite, valor in ((resource.RLIMIT_AS, 1 << 30), (resource.RLIMIT_CPU, 60), (resource.RLIMIT_FSIZE, 128 << 20), (resource.RLIMIT_NOFILE, 64), (resource.RLIMIT_CORE, 0)):
        try:
            resource.setrlimit(limite, (valor, valor))
        except (ValueError, OSError):
            pass


def ejecutar_aislado(orden: dict, timeout: float = 90) -> dict:
    """Detecta o rellena en un PROCESO APARTE con límites de memoria y de tiempo y sin secretos en el entorno: el documento es de terceros y el lector de PDF/Word puede romperse con uno hostil."""
    from .pliegos import _entorno_hijo
    with tempfile.TemporaryDirectory(prefix="formularios-") as tmp:
        try:
            r = subprocess.run([sys.executable, "-m", "cerebro.licitaciones.formularios"], input=json.dumps(orden).encode("utf-8"), cwd=tmp, env=_entorno_hijo(), capture_output=True,
                               timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise ErrorFormulario("El documento tarda demasiado en procesarse") from None
    try:
        res = json.loads(r.stdout[:20_000_000].decode("utf-8", "replace") or "{}")
    except ValueError:
        res = {}
    if r.returncode != 0 or "error" in res:
        if res.get("error"):
            raise ErrorFormulario(res["error"])
        señal = f"señal {-r.returncode}" if r.returncode < 0 else f"código {r.returncode}"
        raise ErrorFormulario(f"No se ha podido procesar el documento (el proceso terminó con {señal})")
    return res


def main() -> int:
    poner_limites()
    try:
        orden = json.loads(sys.stdin.buffer.read(5_000_000).decode("utf-8"))
        ruta, formato = Path(orden["ruta"]), str(orden["formato"])
        if orden["accion"] == "detectar":
            res = detectar(ruta, formato)
        elif orden["accion"] == "rellenar":
            res = rellenar(ruta, formato, Path(orden["destino"]), {str(k): v for k, v in (orden.get("valores") or {}).items()})
        elif orden["accion"] == "extraer_zip":
            res = extraer_zip(ruta, Path(orden["destino"]))
        else:
            raise ErrorFormulario("acción desconocida")
    except ErrorFormulario as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    except MemoryError:
        print(json.dumps({"error": "El documento necesita demasiada memoria para procesarse"}))
        return 1
    except Exception as e:      # noqa: BLE001 — un documento hostil puede romper el lector de muchas maneras
        print(json.dumps({"error": f"No se ha podido procesar el documento ({type(e).__name__})"}))
        return 1
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
