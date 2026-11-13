"""Fichas técnicas de producto: carga segura y búsqueda de enlaces.

Tres vías, la misma tubería: (1) los enlaces que traen las listas CSV de los proveedores, (2) una dirección que alguien da, siempre de un dominio autorizado en
config/fichas.yaml, (3) un PDF subido a mano. Cada PDF pasa por las mismas defensas que los pliegos (lista de dominios, anti-SSRF, tamaño máximo, formato real,
antivirus, lectura en un proceso aparte) y su texto se indexa en la base de conocimiento (departamento «licitaciones»), de donde la comparativa saca la evidencia.
Una ficha ya cargada (mismo contenido) no se repite. Nada de lo descargado se ejecuta ni se obedece: es texto de terceros.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import yaml
from psycopg.rows import dict_row

from ..ajustes import ajustes
from ..herramientas import conocimiento
from . import fabricantes, pliegos

log = logging.getLogger("cerebro.fichas")
RAIZ = Path(__import__("os").environ.get("FICHAS_DIR", "/datos/licitaciones/fichas"))
DEFECTO = {"hosts": [], "max_mb": 30, "max_diarias": 200, "max_por_carga": 100}
ESTADOS_BUENOS = ("indexada", "sin_texto")
DEPARTAMENTO = "licitaciones"
TROZO = 1500
MAX_TEXTO = 400_000


class ErrorFicha(ValueError):
    pass


def configuracion() -> dict:
    try:
        c = yaml.safe_load((Path(ajustes.dir_config) / "fichas.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        c = {}
    cfg = {**DEFECTO, **c}
    cfg["max_mb"] = min(max(int(cfg["max_mb"]), 1), 100)
    cfg["max_diarias"] = max(int(cfg["max_diarias"]), 0)
    cfg["max_por_carga"] = min(max(int(cfg["max_por_carga"]), 1), 1000)
    cfg["hosts"] = [str(h).lower().strip(".") for h in (cfg["hosts"] or []) if h]
    return cfg


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


def dominio(url: str) -> str:
    return (urlparse(url or "").hostname or "").lower().strip(".")


def _limpio(t, n: int = 120) -> str:
    return " ".join(str(t or "").split())[:n]


# ---------------------------------------------------------------- candidatas (puro)
def candidatas(lineas: list[dict], hosts: list[str]) -> dict:
    """De las líneas de una lista de proveedor, los enlaces a fichas: {permitidas: [...], fuera: {dominio: n}, sin_enlace: n}. Un enlace repetido se cuenta una vez."""
    vistas, permitidas, fuera, sin = set(), [], {}, 0
    for l in lineas or []:
        enlaces = l.get("enlaces") or {}
        if not enlaces:
            sin += 1
            continue
        for url in enlaces.values():
            if url in vistas:
                continue
            vistas.add(url)
            if pliegos.host_permitido(url, hosts):
                permitidas.append({"url": url, "marca": _limpio(l.get("marca"), 60), "referencia": _limpio(l.get("ref") or l.get("codigo"), 60)})
            else:
                d = dominio(url) or "(dirección no válida)"
                fuera[d] = fuera.get(d, 0) + 1
    return {"permitidas": permitidas, "fuera": dict(sorted(fuera.items(), key=lambda x: -x[1])), "sin_enlace": sin}


def texto_de(res: dict) -> str:
    return "\n\n".join(p["texto"] for p in res.get("paginas", []) if (p.get("texto") or "").strip())[:MAX_TEXTO]


def sugerencias_de(fuera: dict, maximo: int = 30) -> list[dict]:
    """Los dominios sin autorizar con lo que dice el directorio de fabricantes. «www.2n.com» y «2n.com» son el mismo dominio a efectos de autorizar (autorizar 2n.com cubre sus subdominios). Pura."""
    juntos: dict[str, int] = {}
    for host, n in fuera.items():
        d = fabricantes.dominio_de(host) or host
        juntos[d] = juntos.get(d, 0) + n
    return [fabricantes.sugerencia(d, n) for d, n in sorted(juntos.items(), key=lambda x: -x[1])[:maximo]]


# ---------------------------------------------------------------- una ficha
async def _descargas_hoy() -> int:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM fichas_tecnicas WHERE origen <> 'manual' AND creado >= date_trunc('day', now())")
        return (await cur.fetchone())["n"]


async def _existente(sha: str) -> dict | None:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT * FROM fichas_tecnicas WHERE sha256 = %s", [sha])
        return await cur.fetchone()


async def _registrar(sha, marca, ref, nombre, origen, url, formato, tam, estado, motivo, paginas, trozos, por) -> dict:
    async with await _conectar() as conn:
        cur = await conn.execute(
            "INSERT INTO fichas_tecnicas (sha256, marca, referencia, nombre, origen, url, formato, bytes, estado, motivo, paginas, trozos, por) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (sha256) DO UPDATE SET estado = EXCLUDED.estado, motivo = EXCLUDED.motivo, "
            "paginas = EXCLUDED.paginas, trozos = EXCLUDED.trozos RETURNING *", [sha, marca, ref, nombre, origen, url, formato, tam, estado, motivo, paginas, trozos, por])
        return await cur.fetchone()


def _publica(f: dict) -> dict:
    return {k: f[k] for k in ("id", "marca", "referencia", "nombre", "origen", "formato", "bytes", "estado", "motivo", "paginas", "trozos", "creado") if k in f}


async def incorporar(datos: bytes, nombre: str, marca: str = "", referencia: str = "", origen: str = "manual", url: str = "", por: str = "",
                     analizar=None, extraer=None, indexar=None) -> dict:
    """Pasa unos bytes por antivirus y lectura y, si son un PDF limpio con texto, los indexa. Devuelve el registro (también si falla: queda dicho por qué)."""
    marca, referencia, nombre = _limpio(marca, 60), _limpio(referencia, 60), _limpio(nombre, 200) or "ficha.pdf"
    sha = hashlib.sha256(datos).hexdigest()
    previa = await _existente(sha)
    if previa and previa["estado"] in ESTADOS_BUENOS:
        return {**_publica(previa), "repetida": True}
    if pliegos.formato_real(datos) != "pdf":
        return _publica(await _registrar(sha, marca, referencia, nombre, origen, url, "otro", len(datos), "no_analizable", "No es un PDF: solo se cargan fichas en PDF", None, 0, por))
    v = await (analizar or pliegos.analizar_con_clamd)(datos)
    if v.estado == "infectado":
        return _publica(await _registrar(sha, marca, referencia, nombre, origen, url, "pdf", len(datos), "infectada", v.motivo, None, 0, por))
    if v.estado not in ("limpio", "con_macros"):
        return _publica(await _registrar(sha, marca, referencia, nombre, origen, url, "pdf", len(datos), "no_analizable", v.motivo, None, 0, por))
    RAIZ.mkdir(parents=True, exist_ok=True)
    ruta = RAIZ / f"{sha}.pdf"
    ruta.write_bytes(datos)
    try:
        res = await asyncio.to_thread(extraer or pliegos._lanzar_extractor, ruta, "pdf", 130)
    except pliegos.ErrorPliego as e:
        return _publica(await _registrar(sha, marca, referencia, nombre, origen, url, "pdf", len(datos), "error", str(e)[:300], None, 0, por))
    texto, paginas = texto_de(res), len(res.get("paginas", []))
    if len(texto.strip()) < 80:
        return _publica(await _registrar(sha, marca, referencia, nombre, origen, url, "pdf", len(datos), "sin_texto",
                                         "El PDF no tiene texto legible (¿es un escaneo?): no se puede usar como evidencia", paginas, 0, por))
    titulo = _limpio(f"Ficha técnica {marca} {referencia} {nombre}", 200)
    encabezado = f"[Ficha técnica de fabricante · marca: {marca or 'sin indicar'} · referencia: {referencia or 'sin indicar'}]\n"
    try:
        n = await (indexar or conocimiento.indexar)(titulo, encabezado + texto, url or f"ficha:{sha[:12]}", DEPARTAMENTO, "baja", TROZO)
    except Exception as e:                                                      # el servicio de embeddings puede estar caído: se deja dicho y se puede repetir
        log.warning("fichas: no se ha podido indexar: %s: %s", type(e).__name__, e)
        return _publica(await _registrar(sha, marca, referencia, nombre, origen, url, "pdf", len(datos), "error", f"No se ha podido indexar el texto ({type(e).__name__}): reintenta", paginas, 0, por))
    return _publica(await _registrar(sha, marca, referencia, nombre, origen, url, "pdf", len(datos), "indexada", "", paginas, n, por))


async def desde_url(url: str, marca: str = "", referencia: str = "", origen: str = "web", por: str = "", cfg: dict | None = None, descargar=None, **kw) -> dict:
    """Descarga una ficha de un dominio autorizado y la incorpora. Un dominio no autorizado es un error claro (dice cuál habría que autorizar)."""
    cfg = cfg or configuracion()
    if not pliegos.host_permitido(url, cfg["hosts"]):
        raise ErrorFicha(f"El dominio «{dominio(url) or url[:60]}» no está autorizado en config/fichas.yaml: no se descarga")
    if cfg["max_diarias"] and await _descargas_hoy() >= cfg["max_diarias"]:
        raise ErrorFicha(f"Se ha alcanzado el máximo de {cfg['max_diarias']} descargas de fichas por día")
    try:
        datos = await (descargar or pliegos.descargar_seguro)(url, cfg["hosts"], cfg["max_mb"] << 20)
    except (pliegos.ErrorPliego, pliegos.SinPermisoDescarga) as e:
        raise ErrorFicha(str(e)) from None
    nombre = Path(urlparse(url).path).name or "ficha.pdf"
    return await incorporar(datos, nombre, marca, referencia, origen, url, por, **kw)


async def subir(datos: bytes, nombre: str, marca: str, referencia: str, por: str, cfg: dict | None = None, **kw) -> dict:
    cfg = cfg or configuracion()
    if len(datos) > cfg["max_mb"] << 20:
        raise ErrorFicha(f"La ficha pesa {pliegos._mb(len(datos))}: el máximo es {pliegos._mb(cfg['max_mb'] << 20)}")
    return await incorporar(datos, nombre, marca, referencia, "manual", "", por, **kw)


# ---------------------------------------------------------------- una lista entera
async def _lineas(importacion: int) -> list[dict]:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT lineas FROM importaciones_precios WHERE id = %s", [importacion])
        f = await cur.fetchone()
    if not f:
        raise ErrorFicha("No existe esa importación")
    return f["lineas"] or []


async def revisar_lista(importacion: int, cfg: dict | None = None, lineas: list[dict] | None = None) -> dict:
    """Qué se descargaría de una lista, sin descargar nada: cuántas fichas, de qué dominios autorizados y cuáles quedan fuera (para que se decida si se autorizan)."""
    cfg = cfg or configuracion()
    c = candidatas(lineas if lineas is not None else await _lineas(importacion), cfg["hosts"])
    return {"fichas": len(c["permitidas"]), "dominios_fuera": c["fuera"], "lineas_sin_enlace": c["sin_enlace"], "dominios_autorizados": cfg["hosts"],
            "sugerencias": sugerencias_de(c["fuera"])}


async def cargar_lista(importacion: int, por: str, cfg: dict | None = None, lineas: list[dict] | None = None, descargar=None, **kw) -> dict:
    """Descarga e indexa las fichas de los enlaces autorizados de una lista (hasta `max_por_carga`). Informe: qué se ha cargado, qué ya estaba y qué ha fallado, con el motivo."""
    cfg = cfg or configuracion()
    c = candidatas(lineas if lineas is not None else await _lineas(importacion), cfg["hosts"])
    inf = {"cargadas": 0, "repetidas": 0, "sin_texto": 0, "fallidas": [], "dominios_fuera": c["fuera"], "lineas_sin_enlace": c["sin_enlace"],
           "pendientes": max(len(c["permitidas"]) - cfg["max_por_carga"], 0)}
    for cand in c["permitidas"][:cfg["max_por_carga"]]:
        try:
            r = await desde_url(cand["url"], cand["marca"], cand["referencia"], "csv", por, cfg, descargar, **kw)
        except ErrorFicha as e:
            inf["fallidas"].append({"url": cand["url"][:200], "motivo": str(e)[:200]})
            if "máximo de" in str(e):
                break
            continue
        if r.get("repetida"):
            inf["repetidas"] += 1
        elif r["estado"] == "indexada":
            inf["cargadas"] += 1
        elif r["estado"] == "sin_texto":
            inf["sin_texto"] += 1
        else:
            inf["fallidas"].append({"url": cand["url"][:200], "motivo": r["motivo"][:200]})
    inf["fallidas"] = inf["fallidas"][:30]
    inf["sugerencias"] = sugerencias_de(c["fuera"])
    return inf


async def listar(limite: int = 200) -> dict:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT * FROM fichas_tecnicas ORDER BY creado DESC LIMIT %s", [min(max(int(limite), 1), 500)])
        filas = [_publica(f) for f in await cur.fetchall()]
        cur = await conn.execute("SELECT estado, count(*) AS n FROM fichas_tecnicas GROUP BY estado")
        por_estado = {f["estado"]: f["n"] for f in await cur.fetchall()}
    return {"fichas": filas, "por_estado": por_estado}


# ---------------------------------------------------------------- listas disponibles y cargas en segundo plano
async def listas() -> list[dict]:
    """Las listas de proveedor importadas, con cuántas líneas traen enlace a ficha: para elegir de cuál cargar."""
    async with await _conectar() as conn:
        cur = await conn.execute(
            "SELECT id, proveedor->>'nombre' AS proveedor, lista, estado, creado, jsonb_array_length(lineas) AS lineas, "
            "(SELECT count(*) FROM jsonb_array_elements(lineas) l WHERE l ? 'enlaces' AND l->'enlaces' <> '{}'::jsonb) AS con_enlace "
            "FROM importaciones_precios WHERE estado <> 'descartada' ORDER BY id DESC LIMIT 50")
        return await cur.fetchall()


async def iniciar_carga(importacion: int, por: str) -> int:
    await _lineas(importacion)                                                  # existe
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT id FROM fichas_cargas WHERE importacion = %s AND estado = 'en_curso' AND creado > now() - interval '2 hours'", [importacion])
        if await cur.fetchone():
            raise ErrorFicha("Ya hay una carga en curso de esa lista")
        cur = await conn.execute("INSERT INTO fichas_cargas (importacion, por) VALUES (%s, %s) RETURNING id", [importacion, por])
        return (await cur.fetchone())["id"]


async def ejecutar_carga(carga_id: int, **kw) -> dict:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT importacion, por FROM fichas_cargas WHERE id = %s", [carga_id])
        c = await cur.fetchone()
    if not c:
        return {"estado": "error"}
    try:
        informe = await cargar_lista(c["importacion"], c["por"], **kw)
        estado = "terminada"
    except Exception as e:      # noqa: BLE001 — la carga no puede quedarse «en curso» para siempre
        log.warning("fichas: carga %s: %s: %s", carga_id, type(e).__name__, e)
        informe, estado = {"error": f"No se ha podido terminar la carga ({type(e).__name__})"}, "error"
    async with await _conectar() as conn:
        await conn.execute("UPDATE fichas_cargas SET estado = %s, informe = %s::jsonb, terminada = now() WHERE id = %s", [estado, __import__("json").dumps(informe), carga_id])
    return {"estado": estado}


async def cargas(limite: int = 10) -> list[dict]:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT id, importacion, estado, informe, por, creado, terminada FROM fichas_cargas ORDER BY id DESC LIMIT %s", [min(max(int(limite), 1), 50)])
        return await cur.fetchall()
