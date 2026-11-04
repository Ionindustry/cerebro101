"""Aviso por correo de los PLAZOS URGENTES de las licitaciones en estudio.

Cada hora (tarea de Celery «avisar_plazos») se miran las licitaciones EN ESTUDIO que tienen un plazo de presentación próximo. Cuando faltan los días de un umbral (config/licitaciones.yaml →
plazos.avisar_dias: 3, 1 y 0) se envía UN correo a concursos@ (con copia a notificaciones@: las direcciones de config/buzones.yaml → avisos.copia) con todas las que han llegado a ese umbral, y se
anota en `licitaciones_plazos_avisados` para no repetirlo (aunque la tarea corra cada hora o el equipo estuviera apagado). Solo se envía entre `desde_hora` y `hasta_hora` (hora local). Sin copia
configurada o sin buzón, no se envía nada y no se anota: se intentará de nuevo. Los datos salen de la base de datos (resumen.seguimiento_del_embudo), no del motor. No usa el modelo de IA.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from ..ajustes import ajustes
from ..herramientas import buzones as B
from . import alertas as alertas_mod
from . import avisos_correo as correo
from . import resumen as resumen_mod

log = logging.getLogger("cerebro.licitaciones.plazos")
DEFECTO = {"avisar_dias": [3, 1, 0], "desde_hora": 7, "hasta_hora": 21}


def configuracion(cfg: dict | None = None) -> dict:
    c = {**DEFECTO, **(((cfg if cfg is not None else resumen_mod.config()) or {}).get("plazos") or {})}
    dias = sorted({int(d) for d in (c.get("avisar_dias") or []) if isinstance(d, (int, float)) and not isinstance(d, bool) and 0 <= int(d) <= 30}, reverse=True)
    c["avisar_dias"] = dias or DEFECTO["avisar_dias"]
    c["desde_hora"] = min(max(int(c["desde_hora"]), 0), 23)
    c["hasta_hora"] = min(max(int(c["hasta_hora"]), 1), 24)
    return c


def umbral(dias: int, umbrales: list[int]) -> int | None:
    """El umbral que corresponde a los días que quedan: el menor umbral que sea ≥ días (con [3, 1, 0]: 3 días→3, 2→3, 1→1, 0→0). None si falta más del mayor umbral o el plazo ya pasó."""
    if dias < 0:
        return None
    candidatos = [u for u in umbrales if u >= dias]
    return min(candidatos) if candidatos else None


def en_horario(ahora: datetime, cfg: dict, zona: str) -> bool:
    return cfg["desde_hora"] <= ahora.astimezone(ZoneInfo(zona)).hour < cfg["hasta_hora"]


def redactar(items: list[dict], ahora: datetime, zona: str = "Europe/Madrid") -> tuple[str, str]:
    """(asunto, cuerpo) con las licitaciones que han llegado a su umbral. Pura. `items` son líneas de resumen.seguimiento_del_embudo."""
    tz = ZoneInfo(zona)
    n = len(items)
    asunto = f"Licitaciones: {n} {'plazo próximo' if n == 1 else 'plazos próximos'} para presentar"
    lineas = ["Estas licitaciones en estudio están cerca de su plazo de presentación:", ""]
    for i in sorted(items, key=lambda x: (x["dias_plazo"], x["id"])):
        cuando = "HOY" if i["dias_plazo"] == 0 else ("mañana" if i["dias_plazo"] == 1 else f"en {i['dias_plazo']} días")
        lineas.append(f"• {correo._una_linea(i.get('titulo'), 160)}")
        det = [correo._una_linea(i.get("organismo"), 100) if i.get("organismo") else "", f"plazo {cuando}"]
        if i.get("fecha_limite"):
            det[-1] += f" ({datetime.fromisoformat(i['fecha_limite']).astimezone(tz):%d/%m/%Y %H:%M})"
        b = (i.get("requisitos") or {}).get("borrador", 0)
        if b:
            det.append(f"{b} requisitos del pliego por revisar")
        if i.get("bloqueos"):
            det.append(f"{i['bloqueos']} requisitos que probablemente no se cumplen según el perfil de la empresa")
        lineas.append("  " + " · ".join(d for d in det if d))
        lineas.append(f"  /licitaciones/expedientes/{i['motor_id']}")
        lineas.append("")
    lineas += ["--", f"Aviso automático de 101.cat ({ahora.astimezone(tz):%d/%m/%Y %H:%M}). Cada licitación se avisa una vez por umbral (3 días, 1 día y el mismo día).",
               "Los datos son los del embudo del Cerebro; comprueba el plazo en el anuncio original antes de decidir."]
    return asunto, "\n".join(lineas)


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


async def _ya_avisados() -> set[tuple[int, int]]:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT licitacion_id, umbral FROM licitaciones_plazos_avisados")
        return {(f["licitacion_id"], f["umbral"]) for f in await cur.fetchall()}


async def _anotar(pares: list[tuple[int, int]]) -> None:
    async with await _conectar() as conn:
        for lid, u in pares:
            await conn.execute("INSERT INTO licitaciones_plazos_avisados (licitacion_id, umbral) VALUES (%s,%s) ON CONFLICT DO NOTHING", [lid, u])


async def avisar(enviar=None, ahora: datetime | None = None, cfg: dict | None = None, seguimiento=None, avisados=None, anotar=None, correo_cfg: dict | None = None) -> dict:
    """Envía, si toca, el correo de plazos próximos. Devuelve {"estado", "avisadas"}: estado = «enviado», «nada» (no hay licitaciones en umbral nuevo), «fuera_de_horario», «sin_destinatarios»,
    «sin_buzon» o «error». Todo se puede inyectar para probarlo."""
    ahora = ahora or datetime.now(timezone.utc)
    c = configuracion(cfg)
    if not en_horario(ahora, c, ajustes.zona_horaria):
        return {"estado": "fuera_de_horario", "avisadas": 0}
    ccfg = correo_cfg or correo.configuracion()
    try:
        destinos = []
        for d in ccfg.get("copia") or []:
            limpia = alertas_mod.limpiar_correo(d, ccfg["dominios"])
            if limpia not in destinos:
                destinos.append(limpia)
    except alertas_mod.ErrorAlerta as e:
        log.error("plazos: una dirección de avisos.copia no vale: %s", e)
        return {"estado": "sin_destinatarios", "avisadas": 0}
    if not destinos:
        return {"estado": "sin_destinatarios", "avisadas": 0}
    seg = await (seguimiento or resumen_mod.seguimiento_del_embudo)(ahora, {"resumen": {"seguimiento_max": 500}})
    if seg["estado"] != "ok":
        return {"estado": "error", "avisadas": 0}
    ya = await (avisados or _ya_avisados)()
    por_avisar, pares = [], []
    for i in seg["items"]:
        if i["estado"] != "en_estudio" or i["dias_plazo"] is None:
            continue
        u = umbral(i["dias_plazo"], c["avisar_dias"])
        if u is not None and (i["id"], u) not in ya:
            por_avisar.append(i)
            pares.append((i["id"], u))
    if not por_avisar:
        return {"estado": "nada", "avisadas": 0}
    buzon = ccfg["buzon"]
    if enviar is None:
        if not B.activo(buzon):
            log.warning("plazos: el buzón «%s» no está disponible: no se envía el aviso de plazos", buzon)
            return {"estado": "sin_buzon", "avisadas": 0}
        from ..herramientas.correo import _enviar_smtp as enviar
    remitente = ((B.cargar().get("buzones") or {}).get(buzon) or {}).get("direccion")
    if not remitente:
        return {"estado": "sin_buzon", "avisadas": 0}
    asunto, cuerpo = redactar(por_avisar, ahora, ajustes.zona_horaria)
    try:
        await asyncio.to_thread(enviar, buzon, correo.construir_mensaje(remitente, destinos[0], asunto, cuerpo, destinos[1:]))
    except Exception as e:      # noqa: BLE001 — el servidor de correo falla de muchas maneras: no se anota y se reintenta en la próxima hora
        log.warning("plazos: no se ha podido enviar el aviso de plazos: %s: %s", type(e).__name__, e)
        return {"estado": "error", "avisadas": 0}
    await (anotar or _anotar)(pares)
    return {"estado": "enviado", "avisadas": len(pares)}
