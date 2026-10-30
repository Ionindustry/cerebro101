"""Vigilante del motor de licitaciones: avisa por correo interno cuando la ingesta se atasca.

El motor puede dejar de traer licitaciones sin que nada falle a la vista (un error repetido en cada vuelta de la ingesta): el panel lo dice en «Estado del motor», pero
solo si alguien lo mira. Este vigilante lo mira cada 15 minutos con `/ops/status` y lo recuerda en `licitaciones_vigilante` para avisar lo justo:

  - una vez cuando empieza el problema (una fuente lleva más de `horas_sin_ingesta` sin ingesta correcta, nunca ha completado una, el motor no responde, o —en día laborable y pasada
    `hora_control_hoy`— no ha entrado NINGUNA licitación nueva ni actualizada hoy);
  - un recordatorio cada `repetir_cada_horas` mientras siga;
  - una vez cuando se arregla.

El correo es interno y automático (buzón de notificaciones, solo a direcciones de la empresa) y no lleva datos de licitaciones. Sin destinatarios configurados, solo queda en el registro.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from ..ajustes import ajustes
from ..herramientas import buzones as B
from ..herramientas import licitaciones as motor
from . import alertas as alertas_mod
from . import avisos_correo as correo
from . import resumen as resumen_mod

log = logging.getLogger("cerebro.licitaciones.vigilante")
CLAVE = "motor"
DEFECTO = {"horas_sin_ingesta": 6, "repetir_cada_horas": 24, "destinatarios": [], "hora_control_hoy": 22}


def configuracion(cfg: dict | None = None) -> dict:
    c = {**DEFECTO, **(((cfg if cfg is not None else resumen_mod.config()) or {}).get("vigilante") or {})}
    c["horas_sin_ingesta"] = min(max(float(c["horas_sin_ingesta"]), 1), 168)
    c["repetir_cada_horas"] = min(max(float(c["repetir_cada_horas"]), 1), 168)
    c["destinatarios"] = [d for d in (c.get("destinatarios") or []) if isinstance(d, str)]
    c["hora_control_hoy"] = min(max(int(c["hora_control_hoy"]), 6), 23)
    return c


# ---- Lo puro: qué está mal y qué hay que hacer ----

def sin_novedades_hoy(ahora_local: datetime, novedades_hoy: int | None, hora_control: int) -> str | None:
    """El control de «lo de hoy»: la plataforma (PLACSP) publica UNA tanda al día, hacia las 20:15, así que lo de hoy no existe hasta entonces: en día laborable, pasada la hora de control
    (por defecto las 22:00, con margen sobre esa tanda), tiene que haber entrado alguna licitación nueva o actualizada hoy. `novedades_hoy` None = no se ha podido contar (no se avisa por eso: lo dice ya «el motor no responde»). Pura."""
    if novedades_hoy is None or novedades_hoy > 0 or ahora_local.weekday() >= 5 or ahora_local.hour < hora_control:
        return None
    return (f"Hoy no ha entrado ninguna licitación nueva ni actualizada (son las {ahora_local:%H:%M} de un día laborable y la plataforma publica su tanda diaria hacia las 20:15): "
            "la ingesta no está trayendo lo de hoy.")


def problemas(estado: dict | None, horas: float, hoy: str | None = None) -> list[str]:
    """Las frases de lo que está mal en el estado del motor (la respuesta de `/ops/status`); `None` es que el motor no ha respondido. `hoy` es el resultado de `sin_novedades_hoy`.
    Sin problemas, lista vacía."""
    if estado is None:
        return ["El motor de licitaciones no responde."]
    out = []
    for f in estado.get("fuentes") or []:
        nombre = str(f.get("fuente") or "?")[:60]
        edad = f.get("antiguedad_s")
        if edad is None:
            out.append(f"La fuente {nombre} no ha completado ninguna ingesta.")
        elif edad > horas * 3600:
            out.append(f"La fuente {nombre} lleva {edad / 3600:.1f} horas sin ingesta correcta (límite: {horas:g}).")
    if hoy:
        out.append(hoy)
    if not out and estado.get("estado") == "caido":
        out.append("El motor se declara caído (mira «Estado del motor» en el panel).")
    return out


def decidir(previo: dict | None, hay_problemas: bool, ahora: datetime, repetir_h: float) -> tuple[str, str | None]:
    """(estado nuevo, qué avisar): «problema» al empezar, «recordatorio» pasado `repetir_h` del último aviso, «recuperado» al arreglarse; None si no hay nada que decir."""
    if hay_problemas:
        if previo is None or previo["estado"] != "atascado" or previo.get("avisado_en") is None:       # sin aviso hecho (o fallido): se avisa (otra vez)
            return "atascado", "problema"
        return "atascado", ("recordatorio" if ahora - previo["avisado_en"] >= timedelta(hours=repetir_h) else None)
    if previo is not None and previo["estado"] == "atascado":
        return "ok", "recuperado"
    return "ok", None


def redactar(aviso: str, lista: list[str], desde: datetime, ahora: datetime, zona: str = "Europe/Madrid") -> tuple[str, str]:
    from zoneinfo import ZoneInfo
    z = ZoneInfo(zona)
    hora = lambda d: d.astimezone(z).strftime("%d/%m/%Y %H:%M")          # noqa: E731
    if aviso == "recuperado":
        return "Licitaciones: el motor vuelve a funcionar", (f"El motor de licitaciones vuelve a traer licitaciones con normalidad ({hora(ahora)}).\n"
                                                           f"Estuvo atascado desde las {hora(desde)}.\n\nMensaje automático del Cerebro.")
    titulo = "Licitaciones: la ingesta lleva atascada" + (" (recordatorio)" if aviso == "recordatorio" else "")
    cuerpo = ["La ingesta de licitaciones no está trayendo novedades:", ""] + [f"  - {p}" for p in lista] + [
        "", f"Desde: {hora(desde)}   ·   Ahora: {hora(ahora)}", "",
        "Qué mirar: en el servidor, `docker logs licitaciones-ingestor-1 2>&1 | grep '\"level\":\"ERROR\"' | tail -3`.",
        "Mientras siga así, los resúmenes y las alertas no verán licitaciones nuevas.", "", "Mensaje automático del Cerebro."]
    return titulo, "\n".join(cuerpo)


# ---- Estado guardado y envío ----

def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


async def _leer() -> dict | None:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT estado, desde, avisado_en, detalle FROM licitaciones_vigilante WHERE clave = %s", [CLAVE])
        return await cur.fetchone()


async def _guardar(estado: str, previo: dict | None, ahora: datetime, avisado: bool, detalle: str) -> None:
    igual = previo is not None and previo["estado"] == estado
    desde = previo["desde"] if igual else ahora
    ultimo = ahora if avisado else (previo["avisado_en"] if igual else None)
    async with await _conectar() as conn:
        await conn.execute(
            """INSERT INTO licitaciones_vigilante (clave, estado, desde, avisado_en, detalle) VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (clave) DO UPDATE SET estado = EXCLUDED.estado, desde = EXCLUDED.desde, avisado_en = EXCLUDED.avisado_en, detalle = EXCLUDED.detalle""",
            [CLAVE, estado, desde, ultimo, detalle[:500]])


def _enviar_a(destinatarios: list[str], asunto: str, cuerpo: str, enviar) -> tuple[int, int]:
    """(enviados, fallidos). Las direcciones se validan otra vez aquí: solo de la empresa."""
    cfg = correo.configuracion()
    buzon = cfg["buzon"]
    remitente = ((B.cargar().get("buzones") or {}).get(buzon) or {}).get("direccion")
    if enviar is None:
        if not B.activo(buzon) or not remitente:
            log.warning("vigilante: el buzón «%s» no está disponible: no se envía el correo", buzon)
            return 0, len(destinatarios)
        from ..herramientas.correo import _enviar_smtp as enviar
    ok = mal = 0
    for d in destinatarios:
        try:
            para = alertas_mod.limpiar_correo(d, cfg["dominios"])
            enviar(buzon, correo.construir_mensaje(remitente, para, asunto, cuerpo))
            ok += 1
        except Exception as e:      # noqa: BLE001 — el servidor de correo falla de muchas maneras: se anota y se reintenta en el siguiente ciclo
            log.warning("vigilante: no se pudo avisar a %s: %s: %s", d, type(e).__name__, e)
            mal += 1
    return ok, mal


async def vigilar(consulta=None, enviar=None, ahora: datetime | None = None, cfg: dict | None = None) -> dict:
    """Una pasada: mira el motor, decide y avisa. Devuelve {estado, aviso, problemas, enviados, fallidos}. Si el aviso no se pudo enviar a nadie, no se da por avisado (se reintenta
    en la siguiente pasada); sin destinatarios configurados se da por avisado (solo registro)."""
    ahora = ahora or datetime.now(timezone.utc)
    c = configuracion(cfg)
    consulta = consulta or motor._get
    try:
        estado = await consulta("/ops/status", None)
    except (motor.MotorNoDisponible, ValueError):
        estado = None
    hoy = None
    if estado is not None:
        from zoneinfo import ZoneInfo
        local = ahora.astimezone(ZoneInfo(ajustes.zona_horaria))
        try:
            r = await consulta("/tenders", {"actualizada_desde": local.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(), "limit": 1})
            novedades = int((r.get("total") or {}).get("valor", 0))
        except (motor.MotorNoDisponible, ValueError, TypeError, AttributeError):
            novedades = None
        hoy = sin_novedades_hoy(local, novedades, c["hora_control_hoy"])
    lista = problemas(estado, c["horas_sin_ingesta"], hoy)
    previo = await _leer()
    nuevo, aviso = decidir(previo, bool(lista), ahora, c["repetir_cada_horas"])
    res = {"estado": nuevo, "aviso": aviso, "problemas": lista, "enviados": 0, "fallidos": 0}
    avisado = False
    if aviso:
        log.warning("vigilante: %s — %s", aviso, "; ".join(lista) or "el motor vuelve a la normalidad")
        desde = previo["desde"] if previo is not None and previo["estado"] == "atascado" else ahora
        if c["destinatarios"]:
            asunto, cuerpo = redactar(aviso, lista or (previo or {}).get("detalle", "").split("\n"), desde, ahora, ajustes.zona_horaria)
            res["enviados"], res["fallidos"] = await asyncio.to_thread(_enviar_a, c["destinatarios"], asunto, cuerpo, enviar)
            avisado = res["enviados"] > 0
        else:
            avisado = True
    if aviso == "recuperado" and not avisado:
        return res                      # el aviso de recuperación no salió: se deja «atascado» para reintentarlo en la siguiente pasada
    await _guardar(nuevo, previo, ahora, avisado, "\n".join(lista))
    return res
