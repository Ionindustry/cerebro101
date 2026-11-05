"""Resumen de «Hoy» por correo cada mañana de día laborable, para el equipo de licitaciones (concursos@, con copia a notificaciones@: config/buzones.yaml → avisos.copia).

Es la misma lista que la pantalla «Hoy» de Jarvis, vista como el departamento de Licitaciones (sus aprobaciones, plazos, requisitos por revisar y novedades; NO el estado del sistema, que va a soporte@), pero
sin abrir Jarvis. Solo se envía si hay algo URGENTE o por mirar (si solo hay novedades o no hay nada, no es ruido: no se envía) y UNA vez al día. La tarea corre cada hora y envía en la ventana de
`resumen_hoy` (config/licitaciones.yaml: desde las 08:30 hasta `hasta_hora`): si el equipo estaba apagado a las 08:30, sale en cuanto se enciende dentro de la ventana. Sin IA.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from . import hoy
from .ajustes import ajustes
from .herramientas import buzones as B
from .licitaciones import alertas as alertas_mod
from .licitaciones import avisos_correo as correo
from .licitaciones import resumen as resumen_lic

log = logging.getLogger("cerebro.hoy_correo")
DEFECTO = {"activo": True, "desde": "08:30", "hasta_hora": 12, "url_panel": "http://localhost:3000"}
CLAVE = "hoy_correo"
ROTULOS = {"urgente": "URGENTE", "aviso": "HAY QUE MIRARLO", "info": "PARA TU INFORMACIÓN"}


def configuracion(cfg: dict | None = None) -> dict:
    c = {**DEFECTO, **(((cfg if cfg is not None else resumen_lic.config()) or {}).get("resumen_hoy") or {})}
    try:
        h, m = str(c["desde"]).split(":")
        c["_minutos"] = min(max(int(h), 0), 23) * 60 + min(max(int(m), 0), 59)
    except ValueError:
        c["_minutos"] = 8 * 60 + 30
    c["hasta_hora"] = min(max(int(c["hasta_hora"]), 1), 24)
    c["activo"] = bool(c["activo"])
    url = str(c["url_panel"]).rstrip("/")
    c["url_panel"] = url if url.startswith(("http://", "https://")) else DEFECTO["url_panel"]
    return c


def toca(ahora: datetime, cfg: dict, zona: str) -> bool:
    """¿Estamos en la ventana de envío (día laborable, entre `desde` y `hasta_hora` hora local)? Pura."""
    local = ahora.astimezone(ZoneInfo(zona))
    minutos = local.hour * 60 + local.minute
    return local.weekday() < 5 and cfg["_minutos"] <= minutos < cfg["hasta_hora"] * 60


def redactar(lista: dict, ahora: datetime, cfg: dict, zona: str = "Europe/Madrid") -> tuple[str, str]:
    """(asunto, cuerpo) a partir de la lista de hoy.construir. Pura."""
    local = ahora.astimezone(ZoneInfo(zona))
    u = lista["urgentes"]
    hay = [i for i in lista["items"] if i["nivel"] != "info"]
    asunto = f"Licitaciones hoy: {u} {'urgente' if u == 1 else 'urgentes'}" + (f" y {len(hay) - u} por mirar" if len(hay) > u else "") if u else f"Licitaciones hoy: {len(hay)} {'cosa por mirar' if len(hay) == 1 else 'cosas por mirar'}"
    lineas = [f"Qué hacer hoy ({local:%d/%m/%Y}):", ""]
    for nivel in ("urgente", "aviso", "info"):
        grupo = [i for i in lista["items"] if i["nivel"] == nivel]
        if not grupo:
            continue
        lineas.append(f"== {ROTULOS[nivel]} ({len(grupo)}) ==")
        for i in grupo:
            lineas.append(f"• {correo._una_linea(i['titulo'], 200)}")
            if i.get("detalle"):
                lineas.append(f"  {correo._una_linea(i['detalle'], 240)}")
            if i.get("href") and str(i["href"]).startswith("/"):
                lineas.append(f"  {cfg['url_panel']}{i['href']}")
        lineas.append("")
    lineas += ["--", "Resumen automático de 101.cat (la misma lista que la pantalla «Hoy» de Jarvis). Solo se envía si hay algo urgente o por mirar, una vez al día laborable."]
    return asunto, "\n".join(lineas)


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


async def _enviado_hoy(ahora: datetime, zona: str) -> bool:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT avisado_en FROM vigilancia_avisos WHERE clave = %s", [CLAVE])
        f = await cur.fetchone()
    z = ZoneInfo(zona)
    return bool(f and f["avisado_en"].astimezone(z).date() == ahora.astimezone(z).date())


async def _anotar(ahora: datetime, detalle: str) -> None:
    async with await _conectar() as conn:
        await conn.execute("INSERT INTO vigilancia_avisos (clave, avisado_en, detalle) VALUES (%s,%s,%s) ON CONFLICT (clave) DO UPDATE SET avisado_en = EXCLUDED.avisado_en, detalle = EXCLUDED.detalle",
                           [CLAVE, ahora, detalle[:300]])


async def enviar(enviar_correo=None, ahora: datetime | None = None, cfg: dict | None = None, lista=None, ya_enviado=None, anotar=None, correo_cfg: dict | None = None) -> dict:
    """Envía, si toca, el resumen de la mañana. Devuelve {"estado": «enviado»|«fuera_de_ventana»|«desactivado»|«ya_enviado»|«nada»|«sin_destinatarios»|«sin_buzon»|«error»}. Todo se puede inyectar para probarlo."""
    ahora = ahora or datetime.now(timezone.utc)
    c = configuracion(cfg)
    if not c["activo"]:
        return {"estado": "desactivado"}
    if not toca(ahora, c, ajustes.zona_horaria):
        return {"estado": "fuera_de_ventana"}
    if await (ya_enviado or _enviado_hoy)(ahora, ajustes.zona_horaria):
        return {"estado": "ya_enviado"}
    ccfg = correo_cfg or correo.configuracion()
    try:
        destinos = []
        for d in ccfg.get("copia") or []:
            limpia = alertas_mod.limpiar_correo(d, ccfg["dominios"])
            if limpia not in destinos:
                destinos.append(limpia)
    except alertas_mod.ErrorAlerta as e:
        log.error("hoy_correo: una dirección de avisos.copia no vale: %s", e)
        return {"estado": "sin_destinatarios"}
    if not destinos:
        return {"estado": "sin_destinatarios"}
    datos = await (lista or (lambda: hoy.construir(set(), {"licitaciones"}, ahora)))()          # como el departamento de Licitaciones: sin el estado del sistema (eso va a soporte@)
    if not any(i["nivel"] != "info" for i in datos["items"]):
        return {"estado": "nada"}
    buzon = ccfg["buzon"]
    if enviar_correo is None:
        if not B.activo(buzon):
            log.warning("hoy_correo: el buzón «%s» no está disponible: no se envía el resumen", buzon)
            return {"estado": "sin_buzon"}
        from .herramientas.correo import _enviar_smtp as enviar_correo
    remitente = ((B.cargar().get("buzones") or {}).get(buzon) or {}).get("direccion")
    if not remitente:
        return {"estado": "sin_buzon"}
    asunto, cuerpo = redactar(datos, ahora, c, ajustes.zona_horaria)
    try:
        await asyncio.to_thread(enviar_correo, buzon, correo.construir_mensaje(remitente, destinos[0], asunto, cuerpo, destinos[1:]))
    except Exception as e:      # noqa: BLE001 — el servidor de correo falla de muchas maneras: no se anota y se reintenta a la hora siguiente
        log.warning("hoy_correo: no se ha podido enviar el resumen: %s: %s", type(e).__name__, e)
        return {"estado": "error"}
    await (anotar or _anotar)(ahora, asunto)
    return {"estado": "enviado", "urgentes": datos["urgentes"]}
