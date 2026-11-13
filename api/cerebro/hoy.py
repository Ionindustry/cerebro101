"""«Qué hacer hoy»: lo que necesita atención de la persona que abre Jarvis, en una sola lista ordenada por urgencia.

Junta lo que ya existe por separado: las aprobaciones pendientes (de SUS departamentos), las licitaciones en estudio con plazo cerca y sus requisitos por revisar (seguimiento del resumen diario), lo último nuevo del resumen
de licitaciones, y —para Dirección y Tecnología— el estado del sistema: antivirus, copias de seguridad y motor de licitaciones. Solo LEE y no llama a ningún modelo ni cambia nada. Cada elemento lleva el enlace a
la pantalla donde se resuelve. Cada fuente que falla se omite con un aviso, sin tumbar la lista. Lo ve cada persona según sus permisos: sin permiso, esa sección no existe.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from . import antivirus, copias, tarifas_auto
from .ajustes import ajustes
from .aprobaciones import bandeja
from .licitaciones import frescura, resumen as resumen_lic

log = logging.getLogger("cerebro.hoy")
ORDEN = {"urgente": 0, "aviso": 1, "info": 2}
HORAS_MOTOR_ATRASADO = 3


def _it(nivel: str, categoria: str, titulo: str, detalle: str = "", href: str | None = None, clave: str | None = None) -> dict:
    """`clave` solo la llevan los elementos que se pueden archivar (los vencidos): identifica el elemento entre una consulta y la siguiente."""
    return {"nivel": nivel, "categoria": categoria, "titulo": titulo, "detalle": detalle, "href": href, "clave": clave, "archivable": clave is not None}


def de_aprobaciones(filas: list[dict], ahora: datetime) -> list[dict]:
    """Un elemento con las aprobaciones pendientes (urgente si alguna lleva más de 24 h esperando). Pura."""
    if not filas:
        return []
    vieja = min((f["creado"] for f in filas if f.get("creado")), default=None)
    horas = (ahora - vieja).total_seconds() / 3600 if vieja else 0
    n = len(filas)
    resumen = "; ".join(str((f.get("datos") or {}).get("resumen") or f.get("accion") or "")[:80] for f in filas[:2] if f)
    return [_it("urgente" if horas > 24 else "aviso", "aprobaciones", f"{n} {'aprobación pendiente' if n == 1 else 'aprobaciones pendientes'}",
                (f"La más antigua espera desde hace {horas:.0f} h. " if horas >= 2 else "") + resumen, "/aprobaciones")]


def de_tarifas(filas: list[dict] | None) -> list[dict]:
    """Un elemento con las tarifas de proveedor nuevas pendientes de revisar (aviso; urgente si alguna parece sospechosa: fichero a medias o columna movida). Solo Dirección. Pura."""
    if not filas:
        return []
    n = len(filas)
    sospechosas = [f for f in filas if (f.get("cambios") or {}).get("sospechosa")]
    prov = ", ".join(sorted({str(f.get("proveedor_id")) for f in filas})[:3])
    return [_it("urgente" if sospechosas else "aviso", "precios", f"{n} {'tarifa nueva de proveedor pendiente' if n == 1 else 'tarifas nuevas de proveedores pendientes'} de revisar",
                f"{prov}." + (f" {len(sospechosas)} con cambios sospechosos: míralo antes de aplicar." if sospechosas else " Nada se aplica hasta que la firmes."), "/precios")]


def de_licitaciones(seg: dict | None) -> list[dict]:
    """Del seguimiento del resumen: plazos urgentes o vencidos (uno por licitación) y un elemento con los requisitos por revisar. Pura."""
    if not seg or seg.get("estado") != "ok":
        return []
    out, por_revisar, bloqueos, primera = [], 0, 0, None
    for i in seg.get("items") or []:
        if i.get("estado") != "en_estudio":
            continue
        href = f"/licitaciones/expedientes/{i['motor_id']}"
        titulo = str(i.get("titulo") or "(sin título)")[:100]
        if i.get("vencido"):
            out.append(_it("aviso", "licitaciones", f"Plazo vencido: {titulo}", "Sigue «en estudio» con el plazo de presentación ya pasado: preséntala o descártala", href, f"plazo-vencido:{i['motor_id']}"))
        elif i.get("urgente"):
            d = i["dias_plazo"]
            cuando = "HOY" if d == 0 else ("mañana" if d == 1 else f"en {d} días")
            out.append(_it("urgente", "licitaciones", f"Plazo {cuando}: {titulo}", str(i.get("organismo") or ""), href))
        b = (i.get("requisitos") or {}).get("borrador", 0)
        if b:
            por_revisar += b
            primera = primera or href
        bloqueos += i.get("bloqueos") or 0
    if por_revisar:
        out.append(_it("aviso", "licitaciones", f"{por_revisar} requisitos del pliego por revisar",
                       (f"{bloqueos} probablemente no se cumplen según el perfil de la empresa. " if bloqueos else "") + "Confírmalos o recházalos para que la matriz y la oferta cuenten con ellos", primera))
    return out


def de_novedades(ultimo: dict | None) -> list[dict]:
    """Lo nuevo del último resumen diario de licitaciones (las oportunidades con mejor encaje). Pura."""
    c = (ultimo or {}).get("contenido") or {}
    ops = c.get("oportunidades") or []
    if not ops:
        return []
    mejor = ops[0]
    return [_it("info", "novedades", f"{c['totales']['oportunidades']} oportunidades nuevas en el último resumen ({(ultimo or {}).get('fecha', '')})",
                f"La de mejor encaje ({mejor.get('encaje')}): {str(mejor.get('titulo') or '')[:100]}", "/licitaciones/resumen")]


def del_sistema(av: dict | None, cop: dict | None, motor: dict | None) -> list[dict]:
    """Antivirus, copias y motor de licitaciones: lo que está mal o va a estarlo. Pura."""
    out = []
    if av and av.get("estado") != "ok":
        rechaza = av.get("edad_horas") is None or av["edad_horas"] > av.get("limite_horas", 48) or av["estado"] == "no_responde"
        out.append(_it("urgente" if rechaza else "aviso", "sistema", "Antivirus: " + ("no responde" if av["estado"] == "no_responde" else "firmas viejas"), av.get("motivo", ""), "/agentes"))
    if cop:
        if cop.get("alerta"):
            out.append(_it("urgente", "sistema", "Copias de seguridad: " + (cop.get("motivo") or "llevas días sin una correcta"), "Enciende el servidor y lanza ./scripts/copia_automatica.sh", "/agentes"))
        elif cop.get("ultima") and not cop["ultima"]["ok"]:
            out.append(_it("aviso", "sistema", "La última copia de seguridad falló", str(cop["ultima"].get("mensaje") or "")[:160], "/agentes"))
    if motor:
        if motor.get("estado") == "no_responde":
            out.append(_it("urgente", "sistema", "El motor de licitaciones no responde", "Sin él no entran licitaciones nuevas: docker compose -f licitaciones/compose.yaml ps", "/licitaciones"))
        elif motor.get("edad_h") is not None and motor["edad_h"] > HORAS_MOTOR_ATRASADO:
            out.append(_it("aviso", "sistema", f"El motor lleva {motor['edad_h']:.0f} h sin ingesta correcta", "Si el equipo estuvo apagado, se recupera solo; si no, mira docker logs licitaciones-ingestor-1", "/licitaciones"))
        elif motor.get("poniendose_al_dia"):
            out.append(_it("info", "sistema", "El motor se está poniendo al día de días atrasados", "Lo reciente se publica según llega", "/licitaciones"))
    return out


async def _motor() -> dict:
    """El estado del motor SIN pedirle nada (a diferencia de frescura.comprobar, que pide una actualización)."""
    from .herramientas import licitaciones as motor
    try:
        estado = await motor._get("/ops/status", None)
    except (motor.MotorNoDisponible, ValueError):
        return {"estado": "no_responde"}
    edad, sin = frescura.edad_maxima(estado)
    return {"estado": "ok", "edad_h": None if edad is None else edad / 3600, "sin_ingesta": sin, "poniendose_al_dia": any(f.get("al_dia") is False for f in (estado.get("fuentes") or []))}


async def construir(roles: set[str], departamentos: set[str], ahora: datetime | None = None, **fuentes) -> dict:
    """La lista de «Hoy» para una persona. `fuentes` permite sustituir de dónde sale cada dato (pruebas): aprobaciones, seguimiento, ultimo_resumen, antivirus, copias, motor."""
    ahora = ahora or datetime.now(timezone.utc)
    es_direccion = "direccion" in roles
    ve_lic = es_direccion or "licitaciones" in departamentos
    ve_sistema = es_direccion or "tecnologia" in departamentos
    deps = None if es_direccion else set(departamentos)
    avisos: list[str] = []

    async def leer(nombre, defecto, *args):
        try:
            return await (fuentes.get(nombre) or defecto)(*args)
        except Exception as e:      # noqa: BLE001 — una fuente rota no tumba la lista
            log.warning("hoy: no se ha podido leer %s: %s: %s", nombre, type(e).__name__, e)
            avisos.append(f"No se ha podido leer: {nombre}")
            return None

    items = de_aprobaciones(await leer("aprobaciones", bandeja.pendientes, deps) or [], ahora)
    if es_direccion:
        items += de_tarifas(await leer("tarifas", tarifas_auto.pendientes))
    if ve_lic:
        items += de_licitaciones(await leer("seguimiento", _seguimiento, ahora))
        items += de_novedades(await leer("ultimo_resumen", resumen_lic.leer))
    if ve_sistema:
        items += del_sistema(await leer("antivirus", antivirus.estado), await leer("copias", copias.estado), await leer("motor", _motor))
    items.sort(key=lambda i: ORDEN[i["nivel"]])
    return {"generado": ahora.isoformat(), "items": items, "urgentes": sum(1 for i in items if i["nivel"] == "urgente"), "avisos": avisos,
            "secciones": {"licitaciones": ve_lic, "sistema": ve_sistema}}


async def _seguimiento(ahora: datetime) -> dict:
    return await resumen_lic.seguimiento_del_embudo(ahora, resumen_lic.config())


# ---- Archivo: lo vencido que una persona da por visto. Es por persona (lo que archivas tú no desaparece para otra) y se puede recuperar. ----

CLAVE_VALIDA = re.compile(r"^[a-z\-]{1,30}:[A-Za-z0-9\-]{1,64}$")


def sin_archivados(datos: dict, claves: set[str]) -> dict:
    """La lista de «Hoy» sin lo archivado, con los contadores recalculados. No toca la copia original (está en caché). Pura."""
    items = [i for i in datos["items"] if i.get("clave") not in claves]
    return {**datos, "items": items, "urgentes": sum(1 for i in items if i["nivel"] == "urgente"), "archivados": sum(1 for i in datos["items"] if i.get("clave") in claves)}


async def _conectar() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(ajustes.database_url, connect_timeout=3, row_factory=dict_row)


async def archivo(usuario: str) -> list[dict]:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT clave, categoria, titulo, detalle, href, archivado FROM hoy_archivados WHERE usuario = %s ORDER BY archivado DESC LIMIT 500", [usuario])
        return await cur.fetchall()


async def claves_archivadas(usuario: str) -> set[str]:
    return {f["clave"] for f in await archivo(usuario)}


async def archivar(usuario: str, item: dict) -> None:
    """Archiva un elemento de la lista (con su texto, para poder enseñarlo después). Repetirlo no duplica."""
    if not item.get("archivable") or not CLAVE_VALIDA.match(item.get("clave") or ""):
        raise ValueError("Ese elemento no se puede archivar")
    async with await _conectar() as conn:
        await conn.execute(
            """INSERT INTO hoy_archivados (usuario, clave, categoria, titulo, detalle, href) VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (usuario, clave) DO NOTHING""",
            [usuario, item["clave"], item["categoria"], str(item["titulo"])[:300], str(item.get("detalle") or "")[:500], item.get("href")])


async def desarchivar(usuario: str, clave: str) -> bool:
    async with await _conectar() as conn:
        cur = await conn.execute("DELETE FROM hoy_archivados WHERE usuario = %s AND clave = %s", [usuario, clave])
        return cur.rowcount > 0
