"""Pliegos y demás documentos de una licitación: descarga segura por id y antivirus (docs/SEGURIDAD.md §3.10, SEC-140…145).

Lo que se garantiza (en el código, no en las instrucciones al modelo):
  - **Por id, nunca por URL.** Quien pide (una persona o un agente) dice la licitación y el número del documento; la dirección sale de la ficha del motor. Aun así se
    revalida: solo https, solo plataformas de contratación de la lista (`contratacion.hosts_documentos`), solo direcciones públicas (mismos controles anti-SSRF que la
    herramienta «web»), con cada redirección comprobada y sin salir de la lista.
  - **Tipo según el contenido real**, no según lo que diga el servidor: PDF, DOCX, XLSX, ODT/ODS o ZIP. Un HTML, un SVG o un ejecutable se rechazan.
  - **Cuarentena → ClamAV → limpio, y falla cerrado.** Lo descargado va a `cuarentena/`; solo pasa a `limpio/` si `clamd` lo analiza y está limpio. Sin `clamd`, con firmas de
    más de 48 h, demasiado grande para analizarlo o cifrado, queda «no analizable» y no se ofrece. Con macros de Office queda «con_macros»: solo se podrá extraer el texto.
  - **Tamaño y cuota**: 100 MB por documento y un máximo de descargas al día. Bajo demanda: nada se baja sin que alguien lo pida.
  - **Nadie recibe el binario**: ni los agentes ni el panel; esta capa solo devuelve metadatos (estado, tamaño, huella SHA-256).
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import re
import struct
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import psycopg
import yaml
from psycopg.rows import dict_row

from ..ajustes import ajustes
from ..herramientas import licitaciones as motor
from ..herramientas import web

log = logging.getLogger("cerebro.licitaciones.pliegos")

ESTADOS = ("cuarentena", "limpio", "con_macros", "infectado", "no_analizable", "error")
RAIZ = Path(os.environ.get("PLIEGOS_DIR", "/datos/licitaciones/pliegos"))
DEFECTO = {"max_mb": 100, "max_diarios": 40, "hosts": ["contrataciondelestado.es", "contrataciondelsectorpublico.gob.es", "contractaciopublica.cat"],
           "timeout_s": 120, "firmas_max_horas": 48}
TIPOS_HTTP = {"application/pdf", "application/octet-stream", "application/zip", "application/x-zip-compressed", "binary/octet-stream",
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              "application/vnd.oasis.opendocument.text", "application/vnd.oasis.opendocument.spreadsheet"}
RE_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ErrorPliego(ValueError):
    """Algo que el documento o la petición no admiten; el mensaje es para quien lo pidió."""


class SinPermisoDescarga(PermissionError):
    pass


def _mb(n: int) -> str:
    return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + " MB"


def configuracion() -> dict:
    try:
        c = (yaml.safe_load((Path(ajustes.dir_config) / "integraciones.yaml").read_text(encoding="utf-8")) or {}).get("contratacion", {}).get("pliegos") or {}
    except OSError:
        c = {}
    cfg = {**DEFECTO, **c}
    cfg["max_mb"] = min(max(int(cfg["max_mb"]), 1), 500)
    cfg["hosts"] = [str(h).lower().strip(".") for h in cfg["hosts"] if h]
    return cfg


# ---- Qué se puede pedir (puro) ----

def host_permitido(url: str, hosts: list[str]) -> bool:
    """https y un host de la lista (o un subdominio suyo). Nada de usuario ni contraseña en la dirección, ni puertos raros."""
    p = urlparse(url or "")
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        return False
    h = p.hostname.lower().strip(".")
    return any(h == x or h.endswith("." + x) for x in hosts)


def documentos_de(ficha: dict) -> list[dict]:
    """Los documentos de la ficha del motor, numerados desde 1: lo que se enseña a quien elige. La dirección no se enseña (se pide por número)."""
    return [{"n": i, "nombre": " ".join(str(d.get("nombre") or f"Documento {i}").split())[:200], "clase": d.get("tipo"), "_url": d.get("url_origen")}
            for i, d in enumerate(ficha.get("documentos") or [], start=1)]


def formato_real(datos: bytes) -> str | None:
    """pdf, docx, xlsx, odt, ods o zip según el CONTENIDO; None si es otra cosa (HTML, SVG, ejecutables…)."""
    if datos[:5] == b"%PDF-":
        return "pdf"
    if datos[:4] != b"PK\x03\x04":
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(datos))
        nombres = z.namelist()
        if "mimetype" in nombres:
            t = z.read("mimetype")[:100]
            if t == b"application/vnd.oasis.opendocument.text":
                return "odt"
            if t == b"application/vnd.oasis.opendocument.spreadsheet":
                return "ods"
        if "[Content_Types].xml" in nombres:
            if any(n.startswith("word/") for n in nombres):
                return "docx"
            if any(n.startswith("xl/") for n in nombres):
                return "xlsx"
    except (zipfile.BadZipFile, KeyError, RuntimeError):
        return None
    return "zip"


# ---- Descarga segura ----

async def descargar_seguro(url: str, hosts: list[str], max_bytes: int, timeout: float = 120, transporte=None) -> bytes:
    """GET de un documento con los controles anti-SSRF de «web» y la lista de plataformas; cada redirección se revalida. Pasarse del tamaño es un error (no se trunca)."""
    for _ in range(web.MAX_REDIRECCIONES + 1):
        if not host_permitido(url, hosts):
            raise SinPermisoDescarga("Ese documento no está en una plataforma de contratación de la lista: no se descarga")
        try:
            esquema, host, puerto, ips = await web._validar_destino(url)
        except (ValueError, PermissionError) as e:
            raise SinPermisoDescarga(str(e)) from None
        p = urlparse(url)
        ip = ips[0]
        anclada = f"{esquema}://{f'[{ip}]' if ':' in ip else ip}:{puerto}{p.path or '/'}" + (f"?{p.query}" if p.query else "")
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, transport=transporte) as c:
            async with c.stream("GET", anclada, headers={"Host": host, "User-Agent": web.AGENTE_HTTP, "Accept": "application/pdf,application/octet-stream,*/*;q=0.1"},
                                extensions={"sni_hostname": host}) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code != 200:
                    raise ErrorPliego(f"La plataforma responde con error {r.status_code}")
                tipo = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if tipo and tipo not in TIPOS_HTTP:
                    raise ErrorPliego(f"La plataforma ofrece «{tipo}», que no es un documento de los admitidos")
                declarado = r.headers.get("content-length", "")
                if declarado.isdigit() and int(declarado) > max_bytes:
                    raise ErrorPliego(f"El documento pesa {_mb(int(declarado))}: el máximo es {_mb(max_bytes)}")
                trozos, total = [], 0
                async for t in r.aiter_bytes():
                    total += len(t)
                    if total > max_bytes:
                        raise ErrorPliego(f"El documento pasa de {_mb(max_bytes)}: no se descarga")
                    trozos.append(t)
                return b"".join(trozos)
    raise ErrorPliego("Demasiadas redirecciones al pedir el documento")


# ---- Antivirus (clamd, protocolo INSTREAM) ----

class Veredicto:
    """El resultado de analizar un documento: estado final y motivo (para la persona)."""
    def __init__(self, estado: str, motivo: str = ""):
        self.estado, self.motivo = estado, motivo

    def __repr__(self):
        return f"Veredicto({self.estado!r}, {self.motivo!r})"


def interpretar_respuesta(resp: str) -> Veredicto:
    """«stream: OK» / «stream: <firma> FOUND» / «… ERROR». Las firmas «Heuristics.Encrypted.*» son documentos cifrados y las de macros de Office, un caso aparte."""
    r = resp.strip("\x00 \n")
    if r.endswith("OK"):
        return Veredicto("limpio")
    if r.endswith("FOUND"):
        firma = r.split(":", 1)[-1].replace("FOUND", "").strip()
        if firma.startswith("Heuristics.Encrypted"):
            return Veredicto("no_analizable", "El documento está cifrado o protegido con contraseña: no se puede analizar")
        if "OLE2.ContainsMacros" in firma or firma.startswith("Heuristics.OLE2"):
            return Veredicto("con_macros", "El documento lleva macros: solo se leerá su texto")
        return Veredicto("infectado", f"El antivirus lo marca como dañino ({firma})")
    return Veredicto("no_analizable", "El antivirus no ha podido analizarlo" + (f": {r[:120]}" if r else ""))


async def _orden(host: str, puerto: int, orden: bytes, datos: bytes | None = None, timeout: float = 120) -> str:
    leer, escribir = await asyncio.wait_for(asyncio.open_connection(host, puerto), timeout=10)
    try:
        escribir.write(orden)
        if datos is not None:
            for i in range(0, len(datos), 1 << 20):
                trozo = datos[i:i + (1 << 20)]
                escribir.write(struct.pack(">I", len(trozo)) + trozo)
            escribir.write(struct.pack(">I", 0))
        await escribir.drain()
        return (await asyncio.wait_for(leer.readuntil(b"\0"), timeout=timeout)).decode("utf-8", "replace")
    finally:
        escribir.close()


def _firmas_recientes(version: str, ahora: datetime, max_horas: int) -> bool:
    """«ClamAV 1.4.1/27456/Tue Oct 28 08:31:08 2026»: la fecha de las firmas. Sin fecha legible se considera vieja (falla cerrado)."""
    try:
        t = datetime.strptime(version.strip("\x00 \n").rsplit("/", 1)[-1], "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return ahora - t <= timedelta(hours=max_horas)


async def analizar_con_clamd(datos: bytes, host: str | None = None, puerto: int | None = None, ahora: datetime | None = None, cfg: dict | None = None) -> Veredicto:
    """Pasa los bytes por clamd. Cualquier cosa rara (sin servicio, firmas viejas, tamaño, error) es «no analizable»: el documento no se ofrece."""
    host = host or os.environ.get("CLAMD_HOST", "clamav")
    puerto = puerto or int(os.environ.get("CLAMD_PORT", "3310"))
    cfg = cfg or configuracion()
    try:
        version = await _orden(host, puerto, b"zVERSION\0", timeout=20)
        if not _firmas_recientes(version, ahora or datetime.now(timezone.utc), cfg["firmas_max_horas"]):
            return Veredicto("no_analizable", f"Las firmas del antivirus tienen más de {cfg['firmas_max_horas']} horas: no se fía del análisis")
        return interpretar_respuesta(await _orden(host, puerto, b"zINSTREAM\0", datos, timeout=cfg["timeout_s"]))
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as e:
        log.warning("antivirus no disponible: %s: %s", type(e).__name__, e)
        return Veredicto("no_analizable", "El antivirus no está disponible ahora: el documento queda en cuarentena")


# ---- Base de datos y carpetas ----

def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


def carpeta(motor_id: str, estado: str) -> Path:
    return RAIZ / motor_id / ("limpio" if estado in ("limpio", "con_macros") else "cuarentena")


def _guardar_fichero(motor_id: str, estado: str, sha: str, formato: str, datos: bytes) -> Path:
    destino = carpeta(motor_id, estado)
    destino.mkdir(parents=True, exist_ok=True, mode=0o700)
    ruta = destino / f"{sha}.{formato}"
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_bytes(datos)
    os.chmod(tmp, 0o600)
    tmp.replace(ruta)
    return ruta


def _ficha_publica(f: dict) -> dict:
    """Lo que se devuelve: metadatos, nunca la ruta ni el contenido."""
    return {"id": f["id"], "licitacion": str(f["motor_id"]), "n": f["n"], "nombre": f["nombre"], "formato": f["formato"], "bytes": f["bytes"], "sha256": f["sha256"],
            "estado": f["estado"], "motivo": f["motivo"], "disponible": f["estado"] in ("limpio", "con_macros")}


async def listar(motor_id: str) -> list[dict]:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT id, motor_id, n, nombre, formato, bytes, sha256, estado, motivo FROM pliegos_documentos WHERE motor_id = %s ORDER BY n, id", [motor_id])
        return [_ficha_publica(f) for f in await cur.fetchall()]


async def _descargas_hoy() -> int:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM pliegos_documentos WHERE creado >= date_trunc('day', now())")
        return (await cur.fetchone())["n"]


def _id_valido(motor_id) -> str:
    t = str(motor_id or "").strip().lower()
    if not RE_UUID.match(t):
        raise ErrorPliego("licitacion debe ser el identificador (UUID) que devuelve «buscar»")
    return t


async def documentos(motor_id: str, consulta=None) -> dict:
    """Los documentos de la licitación (por número) y lo que ya se ha bajado de cada uno."""
    motor_id = _id_valido(motor_id)
    ficha = await (consulta or motor._get)(f"/tenders/{motor_id}")
    bajados = {d["n"]: d for d in await listar(motor_id)}
    return {"licitacion": motor_id, "documentos": [{**{k: v for k, v in d.items() if k != "_url"}, "descarga": bajados.get(d["n"])} for d in documentos_de(ficha)]}


async def obtener(motor_id: str, n: int, consulta=None, descargar=None, analizar=None, cfg: dict | None = None) -> dict:
    """Baja el documento nº `n` de la licitación, lo deja en cuarentena y lo pasa por el antivirus. Idempotente: el mismo contenido no se guarda dos veces."""
    motor_id = _id_valido(motor_id)
    cfg = cfg or configuracion()
    ficha = await (consulta or motor._get)(f"/tenders/{motor_id}")
    docs = documentos_de(ficha)
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= len(docs):
        raise ErrorPliego(f"n debe ser un número entre 1 y {len(docs)}" if docs else "Esa licitación no tiene documentos publicados")
    doc = docs[n - 1]
    if not host_permitido(doc["_url"] or "", cfg["hosts"]):
        raise SinPermisoDescarga("Ese documento no está en una plataforma de contratación de la lista: no se descarga")
    if await _descargas_hoy() >= cfg["max_diarios"]:
        raise ErrorPliego(f"Se ha llegado al máximo de {cfg['max_diarios']} descargas de documentos al día: sigue mañana")
    datos = await (descargar or descargar_seguro)(doc["_url"], cfg["hosts"], cfg["max_mb"] * 1_000_000, cfg["timeout_s"])
    if not datos:
        raise ErrorPliego("El documento está vacío")
    formato = formato_real(datos)
    if formato is None:
        raise ErrorPliego("El documento no es un PDF, Word, Excel, OpenDocument ni ZIP (según su contenido): no se guarda")
    sha = hashlib.sha256(datos).hexdigest()
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT id, motor_id, n, nombre, formato, bytes, sha256, estado, motivo FROM pliegos_documentos WHERE motor_id = %s AND sha256 = %s", [motor_id, sha])
        previo = await cur.fetchone()
        if previo and previo["estado"] in ("limpio", "con_macros", "infectado"):          # lo ya decidido no se repite; lo demás (cuarentena, no analizable) se vuelve a analizar
            return _ficha_publica(previo)
        _guardar_fichero(motor_id, "cuarentena", sha, formato, datos)
        cur = await conn.execute(
            """INSERT INTO pliegos_documentos (motor_id, n, nombre, formato, bytes, sha256, estado) VALUES (%s,%s,%s,%s,%s,%s,'cuarentena')
               ON CONFLICT (motor_id, sha256) DO UPDATE SET n = EXCLUDED.n RETURNING id""", [motor_id, n, doc["nombre"], formato, len(datos), sha])
        did = (await cur.fetchone())["id"]
    v = await (analizar or analizar_con_clamd)(datos)
    return await _cerrar(did, motor_id, sha, formato, datos, v)


async def _cerrar(did: int, motor_id: str, sha: str, formato: str, datos: bytes, v: Veredicto) -> dict:
    """Aplica el veredicto: limpio/con macros pasan a `limpio/`, un infectado se borra (queda su huella y la firma en la base) y lo demás sigue en cuarentena."""
    en_cuarentena = carpeta(motor_id, "cuarentena") / f"{sha}.{formato}"
    if v.estado in ("limpio", "con_macros"):
        _guardar_fichero(motor_id, v.estado, sha, formato, datos)
        en_cuarentena.unlink(missing_ok=True)
    elif v.estado == "infectado":
        en_cuarentena.unlink(missing_ok=True)
        log.error("documento infectado descartado: licitación %s, sha256 %s: %s", motor_id, sha, v.motivo)
    async with await _conectar() as conn:
        cur = await conn.execute(
            """UPDATE pliegos_documentos SET estado = %s, motivo = %s, analizado = now() WHERE id = %s
               RETURNING id, motor_id, n, nombre, formato, bytes, sha256, estado, motivo""", [v.estado, v.motivo, did])
        return _ficha_publica(await cur.fetchone())
