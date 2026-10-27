"""Internet para Jarvis: buscar en la web (SearXNG propio) y leer una página pública.

Normas que aplica el código (no solo las instrucciones):
  - Lo que se busca sale del servidor hacia buscadores públicos: una consulta con nombres de clientes, proveedores o empleados, DNI, IBAN,
    correos, teléfonos… NO se hace (misma detección que la anonimización hacia Jev). Solo agentes de sensibilidad baja usan esta herramienta.
  - Leer una página: solo http/https, puertos 80 y 443, y solo direcciones públicas. Se rechaza todo lo que resuelva a una IP privada, de
    bucle o de enlace local (los servicios internos —ERPNext, la base de datos, Ollama…— nunca se alcanzan desde aquí). La conexión se hace
    a la IP ya comprobada (no se vuelve a resolver el nombre), y cada redirección se comprueba igual.
  - Límites de tiempo y de tamaño; solo texto (HTML o texto plano); se respeta robots.txt.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import unicodedata
import urllib.robotparser
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from .. import anonimizacion as anon
from ..ajustes import ajustes
from ..entidades import cargar_entidades
from .base import Herramienta, registrar

AGENTE_HTTP = "Cerebro101-Jarvis/0.1 (+https://101.cat)"
MAX_BYTES = 1_500_000          # lo máximo que se descarga de una página
MAX_REDIRECCIONES = 3
TIMEOUT = 15
MAX_RESULTADOS = 8
PERIODOS = {"dia": "day", "semana": "week", "mes": "month", "año": "year", "ano": "year"}
# Cómo lo escriben los modelos: «último año», «past week», «24 horas», «7 días»…
_SINONIMOS = (("day", ("dia", "hoy", "24h", "24 horas", "diario", "day", "today")),
              ("week", ("semana", "7 dias", "7d", "semanal", "week")),
              ("month", ("mes", "30 dias", "30d", "mensual", "month")),
              ("year", ("ano", "anio", "12 meses", "365 dias", "anual", "year")))


def periodo_de(valor: str) -> str | None:
    """Traduce el periodo que escribe el modelo al de SearXNG (day, week, month, year), o None si no se reconoce."""
    t = unicodedata.normalize("NFKD", (valor or "").lower()).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    palabras = f" {' '.join(t.split())} "
    for destino, claves in _SINONIMOS:
        if any(f" {c} " in palabras or (c.endswith("h") and c in palabras.replace(" ", "")) for c in claves):
            return destino
    return None


# --------------------------------------------------------------------------- consulta sin datos personales
async def _comprobar_consulta(consulta: str) -> None:
    if not consulta.strip():
        raise ValueError("La consulta está vacía")
    if len(consulta) > 300:
        raise ValueError("La consulta es demasiado larga (máximo 300 caracteres): resúmela")
    cfg = anon.configuracion(str(ajustes.dir_config))
    ent = await cargar_entidades(cfg)
    if not ent.disponible:
        raise PermissionError("No se puede comprobar si la consulta lleva nombres de clientes o empleados (el ERP no responde): no se busca fuera")
    conservar = [anon._palabras(c) for c in [*cfg.get("conservar", []), *ent.conservar]]
    hallazgos = [s for s in anon.detectar_entidades(consulta, ent) + anon.detectar_con_formato(consulta)
                 if anon._palabras(consulta[s[0]:s[1]]) not in conservar]
    if hallazgos:
        tipos = ", ".join(sorted({h[2] for h in hallazgos}))
        raise PermissionError(f"La consulta lleva datos que no pueden salir de la empresa ({tipos}): reformúlala sin ellos")


# --------------------------------------------------------------------------- buscar
async def buscar(consulta: str, tipo: str = "general", periodo: str = "", max_resultados: int = 5) -> dict:
    """Busca en internet con SearXNG. `tipo`: general o noticias. `periodo`: dia, semana, mes o año (opcional)."""
    await _comprobar_consulta(consulta)
    if tipo not in ("general", "noticias"):
        raise ValueError("tipo debe ser «general» o «noticias»")
    params = {"q": consulta, "format": "json", "language": "es", "safesearch": 1, "categories": "news" if tipo == "noticias" else "general"}
    if periodo:
        rango = periodo_de(periodo)
        if rango is None:
            raise ValueError("periodo debe ser dia, semana, mes o año")
        params["time_range"] = rango
    try:
        async with httpx.AsyncClient(base_url=ajustes.searxng_url, timeout=TIMEOUT, headers={"User-Agent": AGENTE_HTTP}) as c:
            r = await c.get("/search", params=params)
        r.raise_for_status()
        datos = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise RuntimeError(f"El buscador no responde ({type(e).__name__}). Inténtalo más tarde o contesta con lo que sabes, avisando de que no has podido consultar internet") from e
    limite = max(1, min(int(max_resultados), MAX_RESULTADOS))
    resultados = [{"titulo": (x.get("title") or "")[:200], "url": x.get("url"), "resumen": (x.get("content") or "")[:400],
                   "fecha": x.get("publishedDate"), "fuente": x.get("engine")}
                  for x in datos.get("results", []) if x.get("url")][:limite]
    return {"consulta": consulta, "resultados": resultados,
            "respuestas": [a if isinstance(a, str) else a.get("answer", "") for a in datos.get("answers", [])][:2],
            "aviso": None if resultados else "Sin resultados"}


# --------------------------------------------------------------------------- leer una página pública
def _es_publica(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def _resolver(host: str, puerto: int) -> list[str]:
    return [i[4][0] for i in socket.getaddrinfo(host, puerto, type=socket.SOCK_STREAM)]


async def _validar_destino(url: str) -> tuple[str, str, int, list[str]]:
    """Devuelve (esquema, host, puerto, IPs públicas) o lanza PermissionError/ValueError."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError("Solo se leen direcciones http o https")
    if not p.hostname or p.username or p.password:
        raise ValueError("Dirección no válida (sin usuario ni contraseña en la URL)")
    puerto = p.port or (443 if p.scheme == "https" else 80)
    if puerto not in (80, 443):
        raise PermissionError("Solo se leen páginas en los puertos web normales (80 y 443)")
    try:
        ips = await asyncio.to_thread(_resolver, p.hostname, puerto)
    except OSError as e:
        raise ValueError(f"No se encuentra la dirección {p.hostname}") from e
    if not ips or not all(_es_publica(i) for i in ips):
        raise PermissionError("Esa dirección no es una página pública de internet: no se lee")
    return p.scheme, p.hostname, puerto, ips


async def _descargar(url: str, transporte=None, max_bytes: int = MAX_BYTES) -> tuple[str, bytes, str]:
    """Una descarga segura. Devuelve (url final, contenido, content-type). Cada redirección se valida de nuevo."""
    for _ in range(MAX_REDIRECCIONES + 1):
        esquema, host, puerto, ips = await _validar_destino(url)
        p = urlparse(url)
        ip = ips[0]
        ip_url = f"[{ip}]" if ":" in ip else ip
        anclada = f"{esquema}://{ip_url}:{puerto}{p.path or '/'}" + (f"?{p.query}" if p.query else "")
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, transport=transporte) as c:
            async with c.stream("GET", anclada, headers={"Host": host, "User-Agent": AGENTE_HTTP, "Accept": "text/html,text/plain;q=0.9"},
                                extensions={"sni_hostname": host}) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                tipo = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if r.status_code != 200:
                    raise RuntimeError(f"La página responde con error {r.status_code}")
                if tipo not in ("text/html", "text/plain", "application/xhtml+xml"):
                    raise ValueError(f"Solo se leen páginas de texto, no «{tipo or 'desconocido'}»")
                trozos, total = [], 0
                async for t in r.aiter_bytes():
                    total += len(t)
                    trozos.append(t)
                    if total >= max_bytes:
                        break
                return url, b"".join(trozos)[:max_bytes], tipo
    raise RuntimeError("Demasiadas redirecciones")


class _Texto(HTMLParser):
    SALTAR = {"script", "style", "noscript", "svg", "head", "template", "iframe", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self.titulo = ""
        self._saltar = 0
        self._en_titulo = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SALTAR:
            self._saltar += 1
        elif tag == "title":
            self._en_titulo = True
        elif tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"):
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SALTAR and self._saltar:
            self._saltar -= 1
        elif tag == "title":
            self._en_titulo = False

    def handle_data(self, data):
        if self._en_titulo:
            self.titulo += data
        elif not self._saltar:
            self.partes.append(data)


def texto_de_html(contenido: str) -> tuple[str, str]:
    p = _Texto()
    p.feed(contenido)
    texto = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.partes))
    texto = re.sub(r"\n\s*\n+", "\n\n", texto).strip()
    return p.titulo.strip(), texto


async def _robots_permite(url: str, transporte=None) -> bool:
    p = urlparse(url)
    try:
        _, contenido, _ = await _descargar(f"{p.scheme}://{p.netloc}/robots.txt", transporte, max_bytes=200_000)
    except (RuntimeError, ValueError):
        return True            # sin robots.txt (o ilegible): no hay restricción declarada
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(contenido.decode("utf-8", "replace").splitlines())
    return rp.can_fetch(AGENTE_HTTP, url)


async def leer(url: str, max_caracteres: int = 6000) -> dict:
    """Lee el texto de una página pública (no ejecuta nada de la página, solo extrae el texto)."""
    if not await _robots_permite(url):
        raise PermissionError("El sitio no permite que lo lea un programa (robots.txt)")
    final, contenido, tipo = await _descargar(url)
    bruto = contenido.decode("utf-8", "replace")
    titulo, texto = texto_de_html(bruto) if tipo != "text/plain" else ("", bruto.strip())
    limite = max(500, min(int(max_caracteres), 20_000))
    return {"url": final, "titulo": titulo[:200], "texto": texto[:limite], "recortado": len(texto) > limite}


registrar(Herramienta(
    nombre="web",
    descripcion="Internet: busca en la web y en noticias y lee el texto de páginas públicas. Para dudas generales y de actualidad; nunca con datos de clientes ni de personas.",
    operaciones={"buscar": buscar, "leer": leer},
    ayuda={"buscar": "busca en internet (tipo «general» o «noticias»; periodo dia, semana, mes o año) y devuelve títulos, enlaces y resúmenes; sin nombres de clientes ni datos personales",
           "leer": "lee el texto de una página web pública (por ejemplo, un resultado de la búsqueda) para contrastar o ampliar"},
    ejemplos={"buscar": {"consulta": "novedades normativa RGPD videovigilancia 2026", "tipo": "noticias", "periodo": "mes"},
              "leer": {"url": "https://www.aepd.es/"}},
))
