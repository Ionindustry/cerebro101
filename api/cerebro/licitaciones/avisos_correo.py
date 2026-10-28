"""Avisos de alertas por correo (canal «correo» de las alertas, config/buzones.yaml → `avisos`).

El consumidor de eventos solo deja el aviso en la base (idempotente); este módulo envía después los que quedan pendientes (`correo_enviado IS NULL`), uno o varios
por correo según la alerta, desde una tarea periódica. Así un fallo del servidor de correo no pierde ni duplica avisos: se reintenta hasta `max_intentos` y
un aviso demasiado viejo ya no se envía.

Es correo INTERNO y automático: sale del buzón de notificaciones y solo a direcciones de la empresa (`dominios`), por eso no pasa por la bandeja de aprobaciones
(que es para lo que sale de la empresa). La dirección se valida al crear la alerta y otra vez aquí, justo antes de enviar. El texto lleva datos de terceros (títulos de
licitaciones), siempre como texto plano.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from ..ajustes import ajustes
from ..herramientas import buzones as B
from . import alertas as alertas_mod

log = logging.getLogger("cerebro.licitaciones.avisos_correo")

DEFECTO = {"buzon": "notificaciones", "dominios": [], "max_por_correo": 20, "max_intentos": 5, "max_antiguedad_horas": 48}
ETIQUETAS = {"licitacion.nueva": "Nueva", "licitacion.modificada": "Modificada", "licitacion.adjudicada": "Adjudicada", "licitacion.formalizada": "Formalizada",
             "licitacion.anulada": "Anulada", "competencia.adjudicada": "Competencia"}


def configuracion() -> dict:
    return {**DEFECTO, **(B.cargar().get("avisos") or {})}


def _una_linea(t, n: int = 200) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(t or ""))).strip()[:n]


def _importe(v) -> str:
    try:
        return f"{float(v):,.0f} €".replace(",", ".") if v is not None else ""
    except (TypeError, ValueError):
        return ""


def redactar(alerta: dict, avisos: list[dict], zona: str = "Europe/Madrid") -> tuple[str, str]:
    """(asunto, cuerpo) del correo de una alerta con sus avisos pendientes. Texto plano; pura (se prueba sin servidor)."""
    tz = ZoneInfo(zona)
    nombre = _una_linea(alerta["nombre"], 120)
    n = len(avisos)
    asunto = f"Alerta «{nombre}»: {n} aviso" + ("" if n == 1 else "s") + (f" · {_una_linea(avisos[0]['titulo'], 80)}" if n == 1 else "")
    lineas = [f"La alerta «{nombre}» ha encontrado " + (f"{n} licitación" if n == 1 else f"{n} licitaciones") + ":", ""]
    for a in avisos:
        lineas.append(f"• [{ETIQUETAS.get(a['tipo'], _una_linea(a['tipo']))}] {_una_linea(a['titulo'])}")
        detalle = [_una_linea(a.get("organismo"), 120), _importe(a.get("importe")),
                   f"encaje {float(a['encaje']):.0f}" if a.get("encaje") is not None else "",
                   f"plazo {a['fecha_limite'].astimezone(tz):%d/%m/%Y %H:%M}" if a.get("fecha_limite") else ""]
        detalle = " · ".join(d for d in detalle if d)
        if detalle:
            lineas.append(f"  {detalle}")
        for g in ((a.get("detalle") or {}).get("ganadores") or [])[:5]:
            lineas.append("  Ganó: " + " · ".join(x for x in (_una_linea(g.get("nombre"), 120), g.get("nif") or "", f"{_importe(g['importe'])} sin IVA" if g.get("importe") else "",
                                                           f"lote {_una_linea(g['lote'], 20)}" if g.get("lote") not in (None, "", "1") else "") if x))
        if a.get("enlace"):
            lineas.append(f"  {_una_linea(a['enlace'], 300)}")
        lineas.append("")
    lineas += ["--", "Aviso automático de las alertas de licitaciones de 101.cat. Para dejar de recibirlo, cambia el canal de la alerta o bórrala en el panel (Licitaciones → Alertas).",
               "Los datos vienen de las plataformas de contratación; compruébalos en el anuncio original antes de decidir."]
    return asunto, "\n".join(lineas)


def construir_mensaje(remitente: str, para: str, asunto: str, cuerpo: str) -> EmailMessage:
    m = EmailMessage()
    m["From"] = remitente
    m["To"] = para
    m["Subject"] = asunto
    m["Message-ID"] = make_msgid(domain=remitente.split("@")[-1])
    m["Auto-Submitted"] = "auto-generated"            # que ningún buzón conteste en bucle a un aviso automático
    m.set_content(cuerpo)
    return m


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


async def pendientes(cfg: dict, ahora: datetime) -> list[tuple[dict, list[dict]]]:
    """[(alerta, avisos)] con los avisos por enviar: de alertas activas con canal «correo», aún con intentos y no demasiado viejos. Los más antiguos primero."""
    desde = ahora - timedelta(hours=int(cfg["max_antiguedad_horas"]))
    async with await _conectar() as conn:
        cur = await conn.execute(
            """SELECT a.id AS a_id, a.nombre, a.correo_destino, v.id, v.tipo, v.titulo, v.organismo, v.encaje, v.importe, v.fecha_limite, v.enlace, v.creado, v.detalle
               FROM licitaciones_avisos v JOIN licitaciones_alertas a ON a.id = v.alerta_id
               WHERE a.canal = 'correo' AND a.activa AND v.correo_enviado IS NULL AND v.correo_intentos < %s AND v.creado >= %s
               ORDER BY a.id, v.creado, v.id""", [int(cfg["max_intentos"]), desde])
        filas = await cur.fetchall()
    grupos: dict[int, tuple[dict, list[dict]]] = {}
    for f in filas:
        alerta, avisos = grupos.setdefault(f["a_id"], ({"id": f["a_id"], "nombre": f["nombre"], "correo_destino": f["correo_destino"]}, []))
        avisos.append(f)
    return list(grupos.values())


async def _marcar(ids: list[int], enviado: bool, error: str | None, ahora: datetime) -> None:
    async with await _conectar() as conn:
        if enviado:
            await conn.execute("UPDATE licitaciones_avisos SET correo_enviado = %s, correo_error = NULL WHERE id = ANY(%s)", [ahora, ids])
        else:
            await conn.execute("UPDATE licitaciones_avisos SET correo_intentos = correo_intentos + 1, correo_error = %s WHERE id = ANY(%s)", [str(error)[:300], ids])


async def enviar_pendientes(enviar=None, ahora: datetime | None = None) -> dict:
    """Envía los avisos pendientes de las alertas con canal «correo». `enviar(buzon, mensaje)` es síncrona (por defecto, SMTP del buzón de notificaciones).
    Devuelve {"correos", "avisos", "fallidos", "omitidos"}. Un fallo de una alerta no impide enviar las demás."""
    ahora = ahora or datetime.now(timezone.utc)
    cfg = configuracion()
    resultado = {"correos": 0, "avisos": 0, "fallidos": 0, "omitidos": 0}
    grupos = await pendientes(cfg, ahora)
    if not grupos:
        return resultado
    buzon = cfg["buzon"]
    if enviar is None:
        if not B.activo(buzon):
            log.warning("avisos por correo: el buzón «%s» no está configurado (falta su contraseña): hay avisos sin enviar", buzon)
            resultado["omitidos"] = sum(len(a) for _, a in grupos)
            return resultado
        from ..herramientas.correo import _enviar_smtp as enviar
    remitente = ((B.cargar().get("buzones") or {}).get(buzon) or {}).get("direccion")
    if not remitente:
        log.error("avisos por correo: el buzón «%s» no está en config/buzones.yaml", buzon)
        resultado["omitidos"] = sum(len(a) for _, a in grupos)
        return resultado
    por_correo = max(1, int(cfg["max_por_correo"]))
    for alerta, avisos in grupos:
        try:
            destino = alertas_mod.limpiar_correo(alerta["correo_destino"], cfg["dominios"])        # otra vez, justo antes de enviar
        except alertas_mod.ErrorAlerta as e:
            log.error("avisos por correo: la alerta %s tiene un destino que ya no vale: %s", alerta["id"], e)
            await _marcar([a["id"] for a in avisos], False, str(e), ahora)
            resultado["fallidos"] += len(avisos)
            continue
        for i in range(0, len(avisos), por_correo):
            lote = avisos[i:i + por_correo]
            asunto, cuerpo = redactar(alerta, lote, ajustes.zona_horaria)
            ids = [a["id"] for a in lote]
            try:
                await asyncio.to_thread(enviar, buzon, construir_mensaje(remitente, destino, asunto, cuerpo))
            except Exception as e:      # noqa: BLE001 — el servidor de correo falla de muchas maneras: se anota y se reintenta
                log.warning("avisos por correo: no se ha podido enviar a la alerta %s: %s: %s", alerta["id"], type(e).__name__, e)
                await _marcar(ids, False, f"{type(e).__name__}: {e}", ahora)
                resultado["fallidos"] += len(ids)
                break                   # si falla uno, el resto de esa alerta espera al próximo ciclo (mantiene el orden)
            await _marcar(ids, True, None, ahora)
            resultado["correos"] += 1
            resultado["avisos"] += len(ids)
    return resultado
