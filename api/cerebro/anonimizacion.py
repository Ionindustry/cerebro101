"""Anonimización local de lo que sale hacia servicios externos (Jev en la nube). ISO 27001 / RGPD.

Capas, de más a menos fiable:
  1. Entidades conocidas (clientes, proveedores y empleados de ERPNext + config/anonimizacion.yaml).
  2. Datos con formato: DNI/NIE, CIF, IBAN, tarjetas, Seguridad Social, correos, teléfonos, matrículas,
     códigos postales, IP, URL, direcciones, fecha de nacimiento.
  3. Nombres libres: un detector enchufable (heurístico por defecto; spaCy opcional).
Después se verifica el resultado y, ante la duda, `apto=False`: el llamador NO debe enviar el texto.

Cada dato se sustituye por una etiqueta coherente dentro del texto ([PERSONA_1], [IBAN_1]…). Jev solo devuelve
elecciones, puntuaciones o sí/no, así que no hace falta deshacer la sustitución y la tabla de equivalencias
no se conserva. Seudonimizar no es anonimizar (ver docs/SEGURIDAD.md): esto reduce el riesgo, no sustituye al
contrato de encargado de tratamiento con el proveedor.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable

import yaml

Span = tuple[int, int, str, str]      # inicio, fin, tipo, clave (para repetir la misma etiqueta)
Detector = Callable[[str], list[Span]]


# --------------------------------------------------------------------------- normalización
def _base(c: str) -> str:
    """Una letra por letra, sin tildes y en minúscula: mantiene las posiciones del texto original."""
    d = "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
    return (d[:1] or c).lower()


def normalizar(texto: str) -> str:
    return "".join(_base(c) for c in texto)


def _palabras(texto: str) -> str:
    return re.sub(r"\s+", " ", normalizar(texto)).strip()


# --------------------------------------------------------------------------- validaciones
_LETRAS_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"


def dni_valido(s: str) -> bool:
    s = re.sub(r"[\s-]", "", s).upper()
    if re.fullmatch(r"\d{8}[A-Z]", s):
        return _LETRAS_DNI[int(s[:8]) % 23] == s[8]
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", s):
        return _LETRAS_DNI[int(str("XYZ".index(s[0])) + s[1:8]) % 23] == s[8]
    return False


def iban_valido(s: str) -> bool:
    s = re.sub(r"\s", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    mover = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in mover)) % 97 == 1


def luhn_valido(s: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", s)]
    if not 13 <= len(d) <= 19:
        return False
    suma = 0
    for i, n in enumerate(reversed(d)):
        if i % 2:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        suma += n
    return suma % 10 == 0


def cif_valido(s: str) -> bool:
    s = re.sub(r"[\s-]", "", s).upper()
    m = re.fullmatch(r"([ABCDEFGHJNPQRSUVW])(\d{7})([0-9A-J])", s)
    if not m:
        return False
    letra, num, control = m.groups()
    suma = sum(int(c) for c in num[1::2])
    for c in num[0::2]:
        d = int(c) * 2
        suma += d // 10 + d % 10
    digito = (10 - suma % 10) % 10
    return control in (str(digito), "JABCDEFGHI"[digito]) if letra in "PQRSNW" or control.isalpha() else control == str(digito)


# --------------------------------------------------------------------------- datos con formato
_MAYUS = r"[A-ZÁÉÍÓÚÀÈÒÜÇÑ][a-záéíóúàèòüçñ'·-]{1,}"
_PREFIJOS_VIA_MAYUS = r"C/|Pol\.?\s+Ind\.?|Calle|Carrer|Avda\.?|Avenida|Avinguda|Plaza|Pla[cç]a|Paseo|Passeig|Camino|Cam[ií]|Ronda|Carretera|Ctra\.?"
_PREFIJOS_VIA = (r"pol\.?\s+ind\.?|c/|calle|carrer|av\.?|avda\.?|avd\.?|avenida|avinguda|plaza|pla[cç]a|pza\.?|paseo|passeig|camino|cam[ií]|ronda|"
                 r"traves[ií]a|travessera|carretera|ctra\.?|pol[ií]gono|pol[ií]gon|urbanizaci[oó]n?|urbanitzaci[oó]")

_PATRONES: list[tuple[str, re.Pattern, Callable[[str], bool] | None]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), None),
    ("URL", re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.I), None),
    ("URL", re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.(?:cat|com|es|org|net|eu|io|info|biz|gal|eus)(?:/[^\s<>\"']*)?(?![\w@])", re.I), None),
    ("IBAN", re.compile(r"\b[A-Za-z]{2}\d{2}(?:[ ]?[A-Za-z0-9]{4}){2,7}(?:[ ]?[A-Za-z0-9]{1,4})?\b"), iban_valido),
    ("TARJETA", re.compile(r"\b(?:\d[ -]?){13,19}\b"), luhn_valido),
    ("NIE", re.compile(r"\b[XYZxyz][ -]?\d{7}[ -]?[A-Za-z]\b"), None),
    ("DNI", re.compile(r"\b(?:\d{8}|\d{2}\.\d{3}\.\d{3})[ -]?[A-Za-z]\b"), None),
    ("CIF", re.compile(r"\b[ABCDEFGHJNPQRSUVW][ -]?\d{7}[ -]?[0-9A-J]\b"), cif_valido),
    ("SEG_SOCIAL", re.compile(r"\b\d{2}[/ -]\d{8}[/ -]\d{2}\b"), None),
    ("TELEFONO", re.compile(r"(?<![\w.])(?:(?:\(?\+?34\)?|0034)[ .-]?)?[6789]\d(?:[ .-]?\d){7}(?![\w])"), None),
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), None),
    ("MATRICULA", re.compile(r"\b\d{4}[ -]?[BCDFGHJKLMNPRSTVWXYZ]{3}\b"), None),
    ("MATRICULA", re.compile(r"\b[A-Z]{1,2}[ -]\d{4}[ -][A-Z]{1,2}\b"), None),
    ("FECHA_NACIMIENTO", re.compile(r"(?i)(?:nacid[oa]|naixement|nascut|nascuda|fecha de nacimiento|data de naixement|f\. nac\.?|dob)\D{0,20}"
                                    r"(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+(?:de|d')\s*[a-zàéíóúç]+\s+(?:de|del)\s+\d{4})"), None),
    ("CODIGO_POSTAL", re.compile(r"(?i)(?:\bC\.?P\.?|c[oó]digo postal|codi postal)\s*:?\s*(?:0[1-9]|[1-4]\d|5[0-2])\d{3}\b"), None),
    ("CODIGO_POSTAL", re.compile(r"\b(?:0[1-9]|[1-4]\d|5[0-2])\d{3}(?=\s+[A-ZÁÉÍÓÚÀÈÒÇ][a-záéíóúàèòçñ]{2,})"), None),
    ("DIRECCION", re.compile(rf"(?i)\b(?:{_PREFIJOS_VIA})\s*(?:[^\s,;:().]+,?\s+){{0,6}}?(?:n[ºo°.]?\s*)?\d{{1,4}}[A-Za-z]?\b"), None),
    ("DIRECCION", re.compile(rf"\b(?i:{_PREFIJOS_VIA_MAYUS})\s+(?:(?:de|del|la|las|los|els|les|dels|d')\s*)?{_MAYUS}(?:\s+(?:(?:de|del|la|i)\s+)?{_MAYUS}){{0,3}}"), None),
]
_FORMAS_SIN_VALIDAR = {"DNI", "NIE"}      # un DNI con la letra mal escrita sigue siendo un dato personal


def _fin_iban(candidato: str) -> int:
    """Longitud del prefijo más largo de `candidato` que es un IBAN válido (0 si ninguno)."""
    mejor, compacto = 0, ""
    for i, c in enumerate(candidato):
        if c != " ":
            compacto += c
            if len(compacto) >= 15 and iban_valido(compacto):
                mejor = i + 1
    return mejor


def detectar_con_formato(texto: str) -> list[Span]:
    spans: list[Span] = []
    for tipo, patron, valida in _PATRONES:
        for m in patron.finditer(texto):
            frag = m.group(0).strip()
            if not frag:
                continue
            if tipo == "IBAN":                       # el IBAN es el prefijo más largo del candidato que valida
                fin = _fin_iban(m.group(0))
                if fin:
                    spans.append((m.start(), m.start() + fin, "IBAN", re.sub(r"\s", "", normalizar(m.group(0)[:fin]))))
                continue
            if valida and tipo not in _FORMAS_SIN_VALIDAR and not valida(frag):
                continue
            if tipo == "TELEFONO" and len(re.sub(r"\D", "", frag)) < 9:
                continue
            spans.append((m.start(), m.start() + len(m.group(0).rstrip()), tipo, re.sub(r"[\s.-]", "", normalizar(frag))))
    return spans


# --------------------------------------------------------------------------- entidades conocidas
@dataclass
class Entidades:
    personas: list[str] = field(default_factory=list)
    organizaciones: list[str] = field(default_factory=list)
    conservar: list[str] = field(default_factory=list)
    disponible: bool = True            # False: se esperaba la lista del ERP y no se ha podido leer
    origen: str = "config"

    def vacia(self) -> bool:
        return not (self.personas or self.organizaciones)


_GENERICAS = {"comunidad", "comunitat", "hoteles", "hotel", "hotels", "instalaciones", "instal·lacions", "servicios", "serveis",
              "grupo", "grup", "sociedad", "societat", "cooperativa", "asociacion", "associacio", "fundacion", "fundacio",
              "ayuntamiento", "ajuntament", "de", "del", "la", "el", "los", "las", "els", "les", "i", "y", "d", "l", "restaurante",
              "restaurant", "empresa", "construcciones", "construccions", "electricidad", "electricitat", "talleres", "tallers"}
_FORMA_JURIDICA = re.compile(r"\s+(?:s\.?\s?l\.?\s?u?|s\.?\s?a\.?\s?u?|s\.?\s?c\.?\s?c\.?\s?l|s\.?\s?c\.?\s?p|c\.?\s?b|s\.?\s?l\.?\s?l|srl|ltd|inc|gmbh)\.?$")


def _terminos(valores: Iterable[str], partes: bool) -> list[tuple[str, str]]:
    """(texto normalizado, clave canónica). Para personas, también el nombre y los apellidos sueltos (≥ 4 letras)."""
    salida: dict[str, str] = {}
    for v in valores:
        v = _palabras(v or "")
        if len(v) < 3:
            continue
        salida[v] = v
        sin_forma = _FORMA_JURIDICA.sub("", v)
        if not partes and sin_forma != v and len(sin_forma) >= 4:
            salida.setdefault(sin_forma, v)            # «Comunitat Vilanova» además de «Comunitat Vilanova SL»
        if not partes:                                 # y sin palabras genéricas: «Vilanova», «Costa Brava»
            distintivas = [t for t in sin_forma.split() if t not in _GENERICAS]
            nucleo = " ".join(distintivas)
            if distintivas and nucleo != sin_forma and len(nucleo) >= 5:
                salida.setdefault(nucleo, v)
        if partes:
            for t in v.split():
                if len(t) >= 4 and t not in ("de", "del", "la", "los", "las", "van", "von"):
                    salida.setdefault(t, v)
    return sorted(salida.items(), key=lambda kv: -len(kv[0]))


def detectar_entidades(texto: str, ent: Entidades) -> list[Span]:
    norm = normalizar(texto)
    conservar = [_palabras(c) for c in ent.conservar]
    spans: list[Span] = []
    for tipo, lista, partes in (("PERSONA", ent.personas, True), ("ORGANIZACION", ent.organizaciones, False)):
        for termino, clave in _terminos(lista, partes):
            if termino in conservar or clave in conservar:
                continue
            for m in re.finditer(rf"(?<![a-z0-9]){re.escape(termino)}(?![a-z0-9])", norm):
                spans.append((m.start(), m.end(), tipo, clave))
    return spans


# --------------------------------------------------------------------------- nombres libres
_NOMBRE = rf"(?:{_MAYUS}|[A-ZÁÉÍÓÚÀÈÒÇÑ]ª\.?|[A-ZÁÉÍÓÚÀÈÒÇÑ]\.)"       # palabra con mayúscula o inicial («Mª», «J.»)
_TRATAMIENTO = re.compile(rf"\b(?:Sr\.?|Sra\.?|Srta\.?|Sres\.?|Don|Do[ñn]a|D[ñn]a\.?|Dr\.?|Dra\.?|Senyor|Senyora|"
                          rf"Se[ñn]or|Se[ñn]ora|Na|En)[ \t]+({_NOMBRE}(?:[ \t]+(?:de[ \t]+(?:la[ \t]+|los[ \t]+|las[ \t]+)?|del[ \t]+|i[ \t]+)?{_NOMBRE}){{0,3}})")
_INICIAL = re.compile(rf"\b[A-ZÁÉÍÓÚÀÈÒÇÑ]\.[ \t]*{_MAYUS}(?:[ \t]+{_MAYUS}){{0,2}}")
_PRESENTACION = re.compile(rf"(?i:me llamo|mi nombre es|soy|em dic|el meu nom [ée]s|sóc|soc)[ \t]+({_MAYUS}(?:[ \t]+{_MAYUS}){{0,3}})")
_ARTICULOS = re.compile(r"^(?:(?:El|La|Los|Las|Un|Una|Sr|Sra|Srta|Dr|Dra|Don|Do[ñn]a|Estimado|Estimada|Hola|Bon|Bona)\.?[ \t]+)+")
_SECUENCIA = re.compile(rf"\b{_MAYUS}(?:[ \t]+(?:(?:de|del|i)[ \t]+)?(?:d'|l')?{_MAYUS}){{1,3}}\b")


_TODO_MAYUS = re.compile(r"\b[A-ZÁÉÍÓÚÀÈÒÇÑ]{3,}(?:[ \t]+(?:(?:DE|DEL|I)[ \t]+)?[A-ZÁÉÍÓÚÀÈÒÇÑ]{3,}){1,3}\b")
_SIGLAS = {"CCTV", "PoE", "POE", "SIP", "VPN", "LED", "DVR", "NVR", "ONU", "GPON", "VLAN", "WIFI", "USB", "HDMI", "SMS", "ICT",
           "ENS", "ISO", "RGPD", "CNMC", "ERP", "CRM", "IVA", "IRPF", "NIF", "CIF", "DNI", "NIE", "IBAN", "SMS", "GSM", "LTE",
           "FTTH", "PDF", "URL", "API", "HTTP", "HTTPS", "DNS", "NAS", "UPS", "RJ", "CAT", "UTP", "FTP", "SFTP", "TCP", "UDP",
           "ADSL", "VOIP", "CPD", "SAI", "PCI", "ZIP", "SOS", "DECT", "CCTV"}


def detector_heuristico(no_son_nombres: Iterable[str] = ()) -> Detector:
    """Sin dependencias: tratamientos (Sr., Dña.), presentaciones («me llamo…») y secuencias de 2-4 palabras con
    mayúscula que no sean términos del negocio. Falla por exceso (sustituye de más), no por defecto."""
    excluidos = {_palabras(x) for x in no_son_nombres}

    def detectar(texto: str) -> list[Span]:
        spans: list[Span] = []
        for patron in (_TRATAMIENTO, _PRESENTACION):
            for m in patron.finditer(texto):
                spans.append((m.start(1), m.end(1), "PERSONA", _palabras(m.group(1))))
        for m in _TODO_MAYUS.finditer(texto):          # «JOAN MARTÍ SOLER»; las siglas técnicas no cuentan
            if not any(t in _SIGLAS for t in m.group(0).split()):
                spans.append((m.start(), m.end(), "PERSONA", _palabras(m.group(0))))
        for m in _INICIAL.finditer(texto):
            spans.append((m.start(), m.end(), "PERSONA", _palabras(m.group(0))))
        for m in _SECUENCIA.finditer(texto):
            frag, inicio = m.group(0), m.start()
            m2 = _ARTICULOS.match(frag)                    # «El Sr», «La Sra»… no son nombres
            if m2:
                frag, inicio = frag[m2.end():], inicio + m2.end()
                if len(frag.split()) < 2:
                    continue
            ini = texto.rfind("\n", 0, inicio) + 1
            primera_de_frase = not texto[ini:inicio].strip() or texto[max(0, inicio - 2):inicio].strip() in (".", "?", "!", ":")
            clave = _palabras(frag)
            if clave in excluidos:
                continue
            palabras = frag.split()
            # una sola palabra inicial de frase con mayúscula no cuenta; la secuencia entera sí
            if primera_de_frase and len(palabras) < 2:
                continue
            spans.append((inicio, inicio + len(frag), "PERSONA", clave))
        return spans

    return detectar


def detector_spacy(modelo: str = "es_core_news_md") -> Detector | None:
    """Detector de entidades con spaCy (personas, organizaciones y lugares), si está instalado con su modelo."""
    try:
        import spacy
        nlp = spacy.load(modelo)
    except Exception:  # noqa: BLE001 - sin spaCy o sin modelo: se usa el heurístico
        return None
    tipos = {"PER": "PERSONA", "PERSON": "PERSONA", "ORG": "ORGANIZACION", "LOC": "LUGAR", "GPE": "LUGAR"}

    def detectar(texto: str) -> list[Span]:
        return [(e.start_char, e.end_char, tipos[e.label_], _palabras(e.text)) for e in nlp(texto).ents if e.label_ in tipos]

    return detectar


# --------------------------------------------------------------------------- configuración
@lru_cache(maxsize=4)
def configuracion(dir_config: str) -> dict:
    ruta = Path(dir_config) / "anonimizacion.yaml"
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
    datos = datos or {}
    datos.setdefault("max_caracteres", 4000)
    datos.setdefault("conservar", [])
    datos.setdefault("categorias_especiales", {})
    datos.setdefault("no_son_nombres", [])
    return datos


# --------------------------------------------------------------------------- resultado
@dataclass
class Resultado:
    texto: str
    apto: bool
    motivos: list[str] = field(default_factory=list)
    sustituciones: dict[str, int] = field(default_factory=dict)
    huella: str = ""
    entidades_erp: bool = False        # se aplicó la lista de clientes/proveedores/empleados

    def resumen(self) -> dict:
        """Datos para la auditoría: nunca el texto original."""
        return {"apto": self.apto, "motivos": self.motivos, "sustituciones": self.sustituciones,
                "huella": self.huella, "entidades_erp": self.entidades_erp}


def _resolver(spans: list[Span]) -> list[Span]:
    """Quita solapamientos: gana el más largo; a igualdad, el que empieza antes."""
    elegidos: list[Span] = []
    for s in sorted(spans, key=lambda s: (-(s[1] - s[0]), s[0])):
        if all(s[1] <= e[0] or s[0] >= e[1] for e in elegidos):
            elegidos.append(s)
    return sorted(elegidos)


def _recortar(texto: str, span: Span, ocupados: list[Span]) -> list[Span]:
    """Quita de `span` lo que ya cubren otras sustituciones y descarta los restos sin nombre propio."""
    ini, fin, tipo, _ = span
    trozos, cursor = [], ini
    for o_ini, o_fin, *_ in sorted(ocupados):
        if o_fin <= cursor or o_ini >= fin:
            continue
        if o_ini > cursor:
            trozos.append((cursor, o_ini))
        cursor = max(cursor, o_fin)
    if cursor < fin:
        trozos.append((cursor, fin))
    salida = []
    for a, b in trozos:
        frag = texto[a:b]
        m = re.search(r"[A-ZÁÉÍÓÚÀÈÒÜÇÑ]\w*(?:.*[A-ZÁÉÍÓÚÀÈÒÜÇÑ]\w*)?", frag, re.S)   # de la primera a la última palabra con mayúscula
        if m:
            salida.append((a + m.start(), a + m.end(), tipo, _palabras(m.group(0))))
    return salida


def _categorias_especiales(texto: str, cfg: dict) -> list[str]:
    norm = _palabras(texto)
    halladas = []
    for categoria, terminos in (cfg.get("categorias_especiales") or {}).items():
        if any(re.search(rf"(?<![a-z0-9]){re.escape(_palabras(t.rstrip('*')))}" + ("[a-z0-9]*" if t.endswith("*") else "") +
                         r"(?![a-z0-9])", norm) for t in terminos):
            halladas.append(categoria)
    return halladas


def anonimizar(texto: str, entidades: Entidades | None = None, detector: Detector | None = None,
               cfg: dict | None = None) -> Resultado:
    """Sustituye los datos personales y comprueba el resultado. Si `apto` es False, no enviar a la nube."""
    cfg = cfg if cfg is not None else configuracion("")
    entidades = entidades or Entidades()
    detector = detector or detector_heuristico(cfg.get("no_son_nombres", []))
    conservar = [_palabras(c) for c in [*cfg.get("conservar", []), *entidades.conservar]]
    motivos: list[str] = []
    if not entidades.disponible:
        motivos.append("no se pudo leer la lista de clientes, proveedores y empleados del ERP")
    if len(texto) > cfg.get("max_caracteres", 4000):
        motivos.append(f"texto demasiado largo (más de {cfg.get('max_caracteres', 4000)} caracteres): enviad solo lo necesario")
    motivos += [f"categoría especial de datos: {c}" for c in _categorias_especiales(texto, cfg)]

    fiables = [s for s in detectar_entidades(texto, entidades) + detectar_con_formato(texto)
               if _palabras(texto[s[0]:s[1]]) not in conservar]
    elegidos = _resolver(fiables)
    # El detector de nombres libres es menos fiable: aporta solo los trozos que no solapan con lo anterior
    for s in detector(texto):
        for sub in _recortar(texto, s, elegidos):
            if _palabras(texto[sub[0]:sub[1]]) not in conservar:
                elegidos = _resolver(elegidos + [sub])

    etiquetas: dict[tuple[str, str], str] = {}
    contador: dict[str, int] = {}
    partes, cursor, cuenta = [], 0, {}
    for ini, fin, tipo, clave in elegidos:
        if (tipo, clave) not in etiquetas:
            contador[tipo] = contador.get(tipo, 0) + 1
            etiquetas[(tipo, clave)] = f"[{tipo}_{contador[tipo]}]"
        partes.append(texto[cursor:ini])
        partes.append(etiquetas[(tipo, clave)])
        cuenta[tipo] = cuenta.get(tipo, 0) + 1
        cursor = fin
    partes.append(texto[cursor:])
    limpio = "".join(partes)

    # Verificación: lo que queda no debe contener nada reconocible (las etiquetas, entre corchetes, no cuentan)
    restos = detectar_con_formato(limpio) + detectar_entidades(limpio, entidades)
    restos = [r for r in restos if _palabras(limpio[r[0]:r[1]]) not in conservar]
    if restos:
        motivos.append("tras sustituir quedan datos reconocibles: " + ", ".join(sorted({r[2] for r in restos})))
    return Resultado(texto=limpio, apto=not motivos, motivos=motivos, sustituciones=cuenta,
                     huella=hashlib.sha256(limpio.encode("utf-8")).hexdigest(),
                     entidades_erp=entidades.origen == "erpnext" and entidades.disponible)
