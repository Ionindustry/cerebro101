"""Actualización periódica de tarifas de proveedor, por carpeta de archivos o por servicio web (dirección https).

Qué hace cada día (y a demanda): para cada proveedor de `config/tarifas_auto.yaml` busca un fichero NUEVO (otro contenido que los ya vistos). Si lo hay, lo pasa por la MISMA tubería que una tarifa subida
a mano (cuarentena, antivirus, lectura aislada con límites, coste en euros con cambio y logística: `subidas` y `listas_precios.proponer_tarifa`) y deja UNA propuesta de importación con el resumen de
cambios frente a la última aplicada de ese proveedor (nuevos, retirados, suben, bajan, los mayores cambios).

Reglas:
  · NADA se aplica solo: ni costes ni precios de venta. Dirección revisa la propuesta y firma en la pantalla «Precios».
  · Una tarifa «sospechosa» (por ejemplo, desaparece más de un tercio de los artículos o la mayoría cambia de precio más de un 40 %: lo típico de una columna movida o un fichero a medias) se marca con un
    aviso fuerte para que se mire antes de aplicar.
  · Por servicio web: solo https, solo dominios de la lista del proveedor (cada redirección se revalida), anti-SSRF con la misma comprobación que los pliegos, tamaño máximo. La clave, si la hay, va en
    `secretos/tarifas.env` (nunca en la configuración ni en el repositorio) y no se escribe en ningún registro.
  · Un fallo de un proveedor no frena a los demás: queda anotado (última comprobación y error) y se ve en la pantalla.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse, urljoin

import httpx
import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import listas_precios as LP
from . import subidas
from .ajustes import ajustes
from .herramientas import web
from .licitaciones import pliegos

log = logging.getLogger("cerebro.tarifas_auto")
USUARIO = "sistema:tarifas"
DEPARTAMENTO = "operaciones"
RE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
EXTENSIONES = (".xlsx", ".csv")
ORIGENES = ("carpeta", "url")
FORMATOS = ("csv", "xlsx", "json")
COLUMNAS_JSON = ("referencia", "descripcion", "coste", "marca", "familia", "stock", "ean", "estado", "pvp")
RUTA_SECRETOS = "/run/secretos/tarifas.env"
ANTIGUEDAD_MIN_S = 60                         # un fichero que se está copiando todavía no se toca
UMBRAL_RETIRADOS = Decimal("0.33")
UMBRAL_VARIACION = Decimal("40")
MAX_REDIRECCIONES = 3
TIPOS_WEB = {"text/csv", "text/plain", "application/csv", "application/json", "application/octet-stream", "application/vnd.ms-excel",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "binary/octet-stream"}
_SECRETOS: dict = {"mtime": None, "valores": {}}


class ErrorTarifaAuto(ValueError):
    """Lo que la configuración o el origen no admiten; el mensaje es para la persona."""


# ---------------------------------------------------------------- configuración
def _configuracion(dir_config: str) -> dict:
    try:
        c = yaml.safe_load((Path(dir_config) / "tarifas_auto.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        c = {}
    return {"carpeta_base": str(c.get("carpeta_base") or "/datos/tarifas"), "max_mb": min(max(int(c.get("max_mb") or 50), 1), 200), "proveedores": list(c.get("proveedores") or [])}


def configuracion() -> dict:
    return _configuracion(str(ajustes.dir_config))


def validar_proveedor(p) -> dict:
    """Un proveedor de la configuración, normalizado, o un error que dice qué falta. Pura."""
    if not isinstance(p, dict):
        raise ErrorTarifaAuto("Cada proveedor debe ser un bloque con id, proveedor, canal y origen")
    pid = str(p.get("id") or "")
    if not RE_ID.match(pid):
        raise ErrorTarifaAuto(f"El id «{pid[:30]}» no vale: minúsculas, números y guiones (de 2 a 40)")
    prov = p.get("proveedor")
    if not isinstance(prov, dict) or not str(prov.get("nombre") or "").strip():
        raise ErrorTarifaAuto(f"«{pid}»: falta proveedor.nombre")
    if p.get("canal") not in LP.CANALES:
        raise ErrorTarifaAuto(f"«{pid}»: canal debe ser fabricante o distribuidor")
    origen = p.get("origen")
    if origen not in ORIGENES:
        raise ErrorTarifaAuto(f"«{pid}»: origen debe ser carpeta o url")
    out = {"id": pid, "proveedor": prov, "canal": p["canal"], "moneda": (str(p["moneda"]).upper() if p.get("moneda") else None), "origen": origen}
    if origen == "url":
        url = str(p.get("url") or "")
        hosts = [str(h).lower().strip(".") for h in (p.get("hosts") or []) if h]
        if not hosts or not pliegos.host_permitido(url, hosts):
            raise ErrorTarifaAuto(f"«{pid}»: la url debe ser https y de uno de los dominios de `hosts`")
        formato = p.get("formato")
        if formato not in FORMATOS:
            raise ErrorTarifaAuto(f"«{pid}»: formato debe ser csv, xlsx o json")
        out.update(url=url, hosts=hosts, formato=formato, cabecera=str(p.get("cabecera") or "Authorization"), cabecera_formato=str(p.get("cabecera_formato") or "Bearer {clave}"),
                   clave_secreto=str(p.get("clave_secreto") or ""))
        if formato == "json":
            j = p.get("json") or {}
            cols = j.get("columnas") if isinstance(j, dict) else None
            if not isinstance(cols, dict) or not {"referencia", "coste"} <= set(cols) or any(k not in COLUMNAS_JSON for k in cols):
                raise ErrorTarifaAuto(f"«{pid}»: json.columnas debe indicar al menos referencia y coste (columnas posibles: {', '.join(COLUMNAS_JSON)})")
            out["json"] = {"lista": str(j.get("lista") or ""), "columnas": {k: str(v) for k, v in cols.items()}}
    return out


def proveedores_validos(cfg: dict | None = None) -> tuple[list[dict], list[str]]:
    """Los proveedores bien configurados y los errores de los que no (para enseñarlos, no para romper). Pura sobre `cfg`."""
    cfg = cfg or configuracion()
    ok, errores, vistos = [], [], set()
    for p in cfg["proveedores"]:
        try:
            v = validar_proveedor(p)
            if v["id"] in vistos:
                raise ErrorTarifaAuto(f"El id «{v['id']}» está repetido")
            vistos.add(v["id"])
            ok.append(v)
        except ErrorTarifaAuto as e:
            errores.append(str(e))
    return ok, errores


def secreto(nombre: str) -> str:
    """La clave de un servicio web: de `secretos/tarifas.env` (se relee si cambia). Nunca de la configuración."""
    if not nombre:
        return ""
    ruta = Path(RUTA_SECRETOS)
    try:
        mtime = ruta.stat().st_mtime_ns
    except OSError:
        return ""
    if _SECRETOS["mtime"] != (str(ruta), mtime):
        valores = {}
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                valores[k.strip()] = v.strip().strip("'\"")
        _SECRETOS.update(mtime=(str(ruta), mtime), valores=valores)
    return _SECRETOS["valores"].get(nombre, "")


# ---------------------------------------------------------------- de JSON a CSV (puro)
def _por_ruta(datos, ruta: str):
    for parte in [p for p in ruta.split(".") if p]:
        if not isinstance(datos, dict) or parte not in datos:
            raise ErrorTarifaAuto(f"El JSON no tiene «{ruta}»")
        datos = datos[parte]
    return datos


def json_a_csv(contenido: bytes, j: dict) -> bytes:
    """Una lista de objetos JSON a un CSV con las columnas que entiende el lector de tarifas (referencia, coste…). Lo que falta en un objeto queda vacío. Pura."""
    try:
        datos = json.loads(contenido.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ErrorTarifaAuto("La respuesta del servicio no es un JSON válido") from None
    lista = _por_ruta(datos, j.get("lista", ""))
    if not isinstance(lista, list) or not lista:
        raise ErrorTarifaAuto("El JSON no trae una lista de productos")
    cols = j["columnas"]
    sal = io.StringIO()
    w = csv.writer(sal, delimiter=";")
    w.writerow(list(cols))
    for o in lista[:200_000]:
        if isinstance(o, dict):
            w.writerow([("" if o.get(origen) is None else str(o.get(origen)).replace("\n", " ")) for origen in cols.values()])
    return sal.getvalue().encode("utf-8")


# ---------------------------------------------------------------- cambios frente a la última tarifa (puro)
def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return None


def comparar(anteriores: list[dict] | None, nuevas: list[dict]) -> dict:
    """Qué cambia entre la última tarifa aplicada y la nueva (por código de artículo, sobre el coste en euros o, si falta, el de tarifa). Incluye si parece sospechosa. Pura."""
    def coste(l):
        return _dec(l.get("coste_eur")) if l.get("coste_eur") is not None else _dec(l.get("precio"))
    ant = {l["codigo"]: coste(l) for l in (anteriores or []) if l.get("codigo")}
    nue = {l["codigo"]: coste(l) for l in nuevas if l.get("codigo")}
    nuevos = [c for c in nue if c not in ant]
    retirados = [c for c in ant if c not in nue]
    suben, bajan, iguales, variaciones = [], [], 0, []
    for c, nuevo in nue.items():
        viejo = ant.get(c)
        if c not in ant or viejo is None or nuevo is None or viejo == 0:
            continue
        pct = (nuevo - viejo) / viejo * 100
        if abs(pct) < Decimal("0.005"):
            iguales += 1
            continue
        (suben if pct > 0 else bajan).append((c, pct))
        variaciones.append(abs(pct))
    comunes = len(suben) + len(bajan) + iguales
    mayores = sorted(suben + bajan, key=lambda x: abs(x[1]), reverse=True)[:10]
    avisos = []
    if ant and Decimal(len(retirados)) / Decimal(len(ant)) > UMBRAL_RETIRADOS:
        avisos.append(f"Desaparecen {len(retirados)} de {len(ant)} artículos ({Decimal(len(retirados)) / Decimal(len(ant)) * 100:.0f} %): ¿es un fichero a medias o de otra lista?")
    if comunes and Decimal(len([v for v in variaciones if v > UMBRAL_VARIACION])) / Decimal(comunes) > Decimal("0.5"):
        avisos.append(f"La mayoría de los precios cambia más de un {UMBRAL_VARIACION:.0f} %: ¿se ha movido una columna o ha cambiado la moneda?")
    return {"primera": not ant, "articulos": len(nue), "nuevos": len(nuevos), "retirados": len(retirados), "suben": len(suben), "bajan": len(bajan), "iguales": iguales,
            "variacion_media_pct": str((sum(variaciones) / len(variaciones)).quantize(Decimal("0.1"))) if variaciones else "0.0",
            "mayores": [{"codigo": c, "variacion_pct": str(p.quantize(Decimal("0.1")))} for c, p in mayores], "sospechosa": bool(avisos), "avisos": avisos}


# ---------------------------------------------------------------- descarga por servicio web
async def descargar(p: dict, max_bytes: int, transporte=None, resolver=None) -> tuple[str, bytes]:
    """Baja el fichero de la dirección del proveedor: https, solo sus dominios (cada redirección se revalida), anti-SSRF con la comprobación de «web», tamaño máximo. Devuelve (nombre, bytes)."""
    url = p["url"]
    cab = {"User-Agent": web.AGENTE_HTTP, "Accept": "text/csv,application/json,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.1"}
    if p.get("clave_secreto"):
        clave = secreto(p["clave_secreto"])
        if not clave:
            raise ErrorTarifaAuto(f"Falta la clave «{p['clave_secreto']}» en secretos/tarifas.env")
        cab[p["cabecera"]] = p["cabecera_formato"].replace("{clave}", clave)
    for _ in range(MAX_REDIRECCIONES + 1):
        if not pliegos.host_permitido(url, p["hosts"]):
            raise ErrorTarifaAuto("La dirección no es de un dominio permitido del proveedor")
        try:
            esquema, host, puerto, ips = await (resolver or web._validar_destino)(url)
        except (ValueError, PermissionError) as e:
            raise ErrorTarifaAuto(str(e)) from None
        u = urlparse(url)
        ip = ips[0]
        anclada = f"{esquema}://{f'[{ip}]' if ':' in ip else ip}:{puerto}{u.path or '/'}" + (f"?{u.query}" if u.query else "")
        async with httpx.AsyncClient(timeout=120, follow_redirects=False, transport=transporte) as c:
            async with c.stream("GET", anclada, headers={**cab, "Host": host}, extensions={"sni_hostname": host}) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    if urlparse(url).hostname != u.hostname:
                        cab.pop(p["cabecera"], None)                                                          # la clave no viaja a otro dominio
                    continue
                if r.status_code != 200:
                    raise ErrorTarifaAuto(f"El servicio responde con error {r.status_code}")
                tipo = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if tipo and tipo not in TIPOS_WEB:
                    raise ErrorTarifaAuto(f"El servicio ofrece «{tipo}», que no es una tarifa")
                trozos, total = [], 0
                async for t in r.aiter_bytes():
                    total += len(t)
                    if total > max_bytes:
                        raise ErrorTarifaAuto(f"La tarifa pasa de {max_bytes // 1_000_000} MB: no se descarga")
                    trozos.append(t)
                datos = b"".join(trozos)
                break
    else:
        raise ErrorTarifaAuto("Demasiadas redirecciones")
    if p["formato"] == "json":
        datos = json_a_csv(datos, p["json"])
        return f"{p['id']}-{datetime.now(timezone.utc):%Y%m%d}.csv", datos
    return f"{p['id']}-{datetime.now(timezone.utc):%Y%m%d}.{p['formato']}", datos


# ---------------------------------------------------------------- de una carpeta
def ficheros_de_carpeta(base: str, pid: str, ahora: float | None = None) -> list[tuple[str, bytes]]:
    """Los ficheros .xlsx/.csv de la subcarpeta del proveedor que ya no se están copiando, del más nuevo al más viejo. Lee como mucho 100 MB en total."""
    carpeta = Path(base) / pid
    if not carpeta.is_dir():
        return []
    ahora = ahora if ahora is not None else time.time()
    cand = []
    for f in carpeta.iterdir():
        try:
            if f.is_file() and not f.is_symlink() and f.suffix.lower() in EXTENSIONES and ahora - f.stat().st_mtime >= ANTIGUEDAD_MIN_S:
                cand.append((f.stat().st_mtime, f))
        except OSError:
            continue
    out, total = [], 0
    for _m, f in sorted(cand, key=lambda x: -x[0])[:20]:
        try:
            if f.stat().st_size + total > 100_000_000:
                break
            datos = f.read_bytes()
        except OSError:
            continue
        total += len(datos)
        out.append((f.name, datos))
    return out


# ---------------------------------------------------------------- base de datos
def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


async def _vista(sha: str, pid: str) -> bool:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT 1 FROM tarifas_actualizaciones WHERE proveedor_id = %s AND sha256 = %s", [pid, sha])
        return bool(await cur.fetchone())


async def _ultima_aplicada(nombre_proveedor: str, canal: str) -> list[dict] | None:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT lineas FROM importaciones_precios WHERE estado = 'aplicada' AND proveedor->>'nombre' = %s AND resumen->>'canal' = %s ORDER BY id DESC LIMIT 1", [nombre_proveedor, canal])
        f = await cur.fetchone()
    return f["lineas"] if f else None


async def _guardar(p: dict, nombre: str, sha: str, importacion: int | None, estado: str, motivo: str, cambios: dict) -> int:
    async with await _conectar() as conn:
        cur = await conn.execute("INSERT INTO tarifas_actualizaciones (proveedor_id, origen, nombre, sha256, importacion, estado, motivo, cambios) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                                 "ON CONFLICT (proveedor_id, sha256) DO NOTHING RETURNING id", [p["id"], p["origen"], nombre[:200], sha, importacion, estado, motivo[:300], Jsonb(cambios)])
        f = await cur.fetchone()
    return f["id"] if f else 0


async def _vigilancia(pid: str, ok: bool, error: str = "", novedades: int = 0) -> None:
    async with await _conectar() as conn:
        await conn.execute(
            "INSERT INTO tarifas_vigilancia (proveedor_id, ultimo_intento, ultimo_ok, error, novedades) VALUES (%s, now(), CASE WHEN %s THEN now() END, %s, %s) "
            "ON CONFLICT (proveedor_id) DO UPDATE SET ultimo_intento = now(), ultimo_ok = CASE WHEN %s THEN now() ELSE tarifas_vigilancia.ultimo_ok END, error = %s, novedades = %s",
            [pid, ok, error[:300], novedades, ok, error[:300], novedades])


# ---------------------------------------------------------------- la tarea
async def procesar_fichero(p: dict, nombre: str, datos: bytes, subir=None, proponer=None) -> dict | None:
    """Un fichero de un proveedor: si es nuevo, lo prepara como propuesta de importación (cuarentena, antivirus, lectura) y anota los cambios. None si ya se había visto."""
    sha = hashlib.sha256(datos).hexdigest()
    if await _vista(sha, p["id"]):
        return None
    ficha = await (subir or subidas.subir)(USUARIO, nombre, datos)
    if ficha["estado"] not in ("limpio", "con_macros"):
        await _guardar(p, nombre, sha, None, "rechazada", ficha.get("motivo") or f"El fichero no es seguro ({ficha['estado']})", {})
        return {"proveedor": p["id"], "fichero": nombre, "estado": "rechazada", "motivo": ficha.get("motivo") or ficha["estado"]}
    try:
        r = await (proponer or LP.proponer_tarifa)(ficha["id"], p["proveedor"], p["canal"], USUARIO, DEPARTAMENTO, p.get("moneda"))
    except (LP.ErrorImportacion, LP.NoExiste) as e:
        await _guardar(p, nombre, sha, None, "error", str(e), {})
        return {"proveedor": p["id"], "fichero": nombre, "estado": "error", "motivo": str(e)[:200]}
    lineas = (await LP._cargar(r["importacion"]))["lineas"]
    cambios = comparar(await _ultima_aplicada(p["proveedor"]["nombre"], p["canal"]), lineas)
    aid = await _guardar(p, nombre, sha, r["importacion"], "pendiente", "", cambios)
    return {"proveedor": p["id"], "fichero": nombre, "estado": "pendiente", "actualizacion": aid, "importacion": r["importacion"], "cambios": cambios}


async def ejecutar(cfg: dict | None = None, descargar_=None, subir=None, proponer=None, ahora: float | None = None) -> dict:
    """Mira cada proveedor configurado. Devuelve el informe: novedades, ficheros rechazados o con error y proveedores que han fallado. Un fallo de uno no frena a los demás."""
    cfg = cfg or configuracion()
    provs, errores_cfg = proveedores_validos(cfg)
    inf = {"proveedores": len(provs), "novedades": [], "fallos": [], "configuracion": errores_cfg}
    for p in provs:
        try:
            if p["origen"] == "carpeta":
                ficheros = ficheros_de_carpeta(cfg["carpeta_base"], p["id"], ahora)
            else:
                nombre, datos = await (descargar_ or descargar)(p, cfg["max_mb"] * 1_000_000)
                ficheros = [(nombre, datos)]
            nuevas = 0
            for nombre, datos in ficheros:
                r = await procesar_fichero(p, nombre, datos, subir, proponer)
                if r:
                    inf["novedades"].append(r)
                    nuevas += 1
            await _vigilancia(p["id"], True, "", nuevas)
        except ErrorTarifaAuto as e:
            inf["fallos"].append({"proveedor": p["id"], "motivo": str(e)[:200]})
            await _vigilancia(p["id"], False, str(e))
        except Exception as e:      # noqa: BLE001 — un proveedor roto no frena a los demás
            log.warning("tarifas: %s: %s: %s", p["id"], type(e).__name__, e)
            inf["fallos"].append({"proveedor": p["id"], "motivo": f"fallo interno ({type(e).__name__})"})
            await _vigilancia(p["id"], False, f"fallo interno ({type(e).__name__})")
    return inf


# ---------------------------------------------------------------- lo que ve Dirección
async def listar(limite: int = 30, cfg: dict | None = None) -> dict:
    cfg = cfg or configuracion()
    provs, errores = proveedores_validos(cfg)
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT id, proveedor_id, origen, nombre, importacion, estado, motivo, cambios, creado, decidido_por, decidido FROM tarifas_actualizaciones ORDER BY id DESC LIMIT %s", [min(max(int(limite), 1), 100)])
        filas = await cur.fetchall()
        cur = await conn.execute("SELECT proveedor_id, ultimo_intento, ultimo_ok, error, novedades FROM tarifas_vigilancia")
        vig = {f["proveedor_id"]: f for f in await cur.fetchall()}
    iso = lambda t: t.isoformat() if t else None      # noqa: E731
    return {"proveedores": [{"id": p["id"], "nombre": p["proveedor"]["nombre"], "origen": p["origen"], "canal": p["canal"],
                             "ultimo_intento": iso((vig.get(p["id"]) or {}).get("ultimo_intento")), "ultimo_ok": iso((vig.get(p["id"]) or {}).get("ultimo_ok")), "error": (vig.get(p["id"]) or {}).get("error", "")}
                            for p in provs], "errores_configuracion": errores,
            "actualizaciones": [{**{k: f[k] for k in ("id", "proveedor_id", "origen", "nombre", "importacion", "estado", "motivo", "cambios", "decidido_por")}, "creado": iso(f["creado"]), "decidido": iso(f["decidido"])} for f in filas]}


async def pendientes() -> list[dict]:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT id, proveedor_id, nombre, cambios, creado FROM tarifas_actualizaciones WHERE estado = 'pendiente' ORDER BY id")
        return await cur.fetchall()


async def _cargar(aid: int) -> dict:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT * FROM tarifas_actualizaciones WHERE id = %s", [aid])
        f = await cur.fetchone()
    if not f:
        raise LP.NoExiste("No existe esa actualización de tarifa")
    return f


async def vista(aid: int) -> dict:
    """La vista previa de aplicar una actualización: lo de la importación (proveedor, líneas, rangos) más el resumen de cambios."""
    a = await _cargar(aid)
    if a["estado"] != "pendiente" or not a["importacion"]:
        raise ErrorTarifaAuto(f"Esta actualización está «{a['estado']}»: no hay nada que aplicar")
    v = await LP.vista_aplicar(a["importacion"], DEPARTAMENTO)
    return {"actualizacion": aid, "cambios": a["cambios"], "vista": v}


async def _decidir(aid: int, estado: str, por: str) -> None:
    async with await _conectar() as conn:
        await conn.execute("UPDATE tarifas_actualizaciones SET estado = %s, decidido_por = %s, decidido = now() WHERE id = %s", [estado, por, aid])


async def aplicar(aid: int, por: str) -> dict:
    """Aplica en el ERP los costes de la propuesta (alta del proveedor y artículos si faltan). Solo tras la firma de Dirección: lo exige la ruta."""
    a = await _cargar(aid)
    if a["estado"] != "pendiente" or not a["importacion"]:
        raise ErrorTarifaAuto(f"Esta actualización está «{a['estado']}»: no se puede aplicar")
    r = await LP.aplicar(a["importacion"], DEPARTAMENTO)
    await _decidir(aid, "aplicada", por)
    return r


async def descartar(aid: int, por: str) -> dict:
    a = await _cargar(aid)
    if a["estado"] != "pendiente":
        raise ErrorTarifaAuto(f"Esta actualización está «{a['estado']}»: no se puede descartar")
    if a["importacion"]:
        try:
            await LP.descartar(a["importacion"])
        except (LP.ErrorImportacion, LP.NoExiste):
            pass
    await _decidir(aid, "descartada", por)
    return {"actualizacion": aid, "estado": "descartada"}
