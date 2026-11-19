"""El registro central de fuentes (funding_sources) y la ejecución de los conectores.

El catálogo (config/subvenciones.yaml) da de alta las fuentes y actualiza sus datos descriptivos; lo que lleva la base (si está habilitada, su estado, su marca de sincronización)
no se pisa al reiniciar. Una fuente solo se sincroniza sola si está habilitada Y activa Y tiene conector; y no se puede activar sin una ejecución correcta previa.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..ajustes import ajustes
from . import sincronizar as S
from .almacen import AlmacenPG
from .conectores import cargar

log = logging.getLogger("cerebro.subvenciones.registro")
ESTADOS = ("ACTIVE", "DISABLED", "PENDING_ACCESS", "PENDING_VERIFICATION", "ERROR", "MAINTENANCE")
PARAMS_POR_DEFECTO = {"paginas_maximas_por_ejecucion": 40, "tamano_pagina": 50, "pausa_entre_peticiones_s": 0.5, "timeout_s": 30, "reintentos": 3,
                      "dias_proximo_cierre": 15, "dias_novedad": 7}


class ErrorFuentes(ValueError):
    """Lo que no se puede hacer con una fuente; el mensaje es para la persona."""


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


def catalogo() -> tuple[dict, list[dict]]:
    """(parámetros de sincronización, fuentes) del YAML. Sin fichero legible: parámetros por defecto y sin fuentes."""
    try:
        datos = yaml.safe_load((ajustes.dir_config / "subvenciones.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        log.warning("config/subvenciones.yaml no se puede leer")
        return dict(PARAMS_POR_DEFECTO), []
    params = {**PARAMS_POR_DEFECTO, **{k: v for k, v in (datos.get("sincronizacion") or {}).items() if k in PARAMS_POR_DEFECTO}}
    return params, [f for f in (datos.get("fuentes") or []) if isinstance(f, dict) and f.get("code")]


async def alta_catalogo() -> int:
    """Da de alta las fuentes del catálogo que no existan y actualiza los datos descriptivos de las que sí (no toca estado, habilitación ni marca de sincronización)."""
    _p, fuentes = catalogo()
    n = 0
    async with await _conectar() as c:
        for f in fuentes:
            await c.execute(
                """INSERT INTO funding_sources (source_code, source_name, country, geographic_scope, official_url, api_base_url, access_type, authentication_type, license,
                                                source_priority, connector, synchronization_frequency, integration_status, notes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (source_code) DO UPDATE SET source_name = EXCLUDED.source_name, country = EXCLUDED.country, geographic_scope = EXCLUDED.geographic_scope,
                     official_url = EXCLUDED.official_url, api_base_url = EXCLUDED.api_base_url, access_type = EXCLUDED.access_type, authentication_type = EXCLUDED.authentication_type,
                     license = EXCLUDED.license, source_priority = EXCLUDED.source_priority, connector = EXCLUDED.connector, notes = EXCLUDED.notes""",
                [f["code"], f.get("name") or f["code"], f.get("country") or "ES", f.get("scope") or "", f.get("url") or "", f.get("api") or "", f.get("access") or "PENDING_VERIFICATION",
                 f.get("auth") or "NONE", f.get("license") or "", f.get("priority") or "media", f.get("connector"), int(f.get("frequency_h") or 24), f.get("status") or "PENDING_VERIFICATION",
                 f.get("notes") or ""])
            n += 1
    return n


async def listar() -> list[dict]:
    """Las fuentes con su estado y la última ejecución (administración de conectores)."""
    async with await _conectar() as c:
        cur = await c.execute(
            """SELECT s.id::text AS id, s.source_code, s.source_name, s.country, s.geographic_scope, s.official_url, s.access_type, s.source_priority, s.connector,
                      s.is_enabled, s.integration_status, s.synchronization_frequency, s.last_sync_at, s.last_success_at, s.next_sync_at, s.last_error, s.notes,
                      r.status AS run_status, r.fetched, r.inserted, r.updated, r.unchanged, r.invalid, r.duration_ms, r.trigger AS run_trigger,
                      (SELECT count(*) FROM funding_source_records x WHERE x.source_id = s.id) AS records
               FROM funding_sources s
               LEFT JOIN LATERAL (SELECT * FROM funding_sync_runs WHERE source_id = s.id ORDER BY started_at DESC LIMIT 1) r ON true
               ORDER BY s.source_code""")
        filas = await cur.fetchall()
    for f in filas:
        f["has_connector"] = cargar(f["connector"]) is not None if f["connector"] else False
        for k in ("last_sync_at", "last_success_at", "next_sync_at"):
            f[k] = f[k].isoformat() if f[k] else None
    return filas


async def _fuente(codigo: str) -> dict:
    async with await _conectar() as c:
        cur = await c.execute("SELECT *, id::text AS id FROM funding_sources WHERE source_code = %s", [str(codigo).strip().upper()])
        f = await cur.fetchone()
    if not f:
        raise ErrorFuentes(f"No existe la fuente «{codigo}»")
    return f


async def cambiar(codigo: str, habilitada: bool | None = None, estado: str | None = None, ajustes_conector: dict | None = None) -> dict:
    """Habilitar/pausar una fuente, cambiar su estado o sus parámetros. No se puede activar sin conector ni sin una ejecución correcta previa: nada se da por conectado sin comprobarlo."""
    f = await _fuente(codigo)
    if estado is not None and estado not in ESTADOS:
        raise ErrorFuentes(f"Estado no válido (uno de {', '.join(ESTADOS)})")
    activar = bool(habilitada) or estado == "ACTIVE"
    if activar:
        if not f["connector"] or cargar(f["connector"]) is None:
            raise ErrorFuentes("Esta fuente todavía no tiene conector: no se puede activar (queda pendiente de verificación)")
        if not f["last_success_at"]:
            raise ErrorFuentes("Antes de activarla hay que lanzar una sincronización manual correcta y comprobar los datos reales")
    sets, args = [], []
    if habilitada is not None:
        sets.append("is_enabled = %s")
        args.append(bool(habilitada))
        if habilitada and estado is None:
            sets.append("integration_status = 'ACTIVE'")
        if habilitada is False and estado is None and f["integration_status"] == "ACTIVE":
            sets.append("integration_status = 'DISABLED'")
    if estado is not None:
        sets.append("integration_status = %s")
        args.append(estado)
    if ajustes_conector is not None:
        sets.append("settings = %s")
        args.append(Jsonb(ajustes_conector))
    if sets:
        async with await _conectar() as c:
            await c.execute(f"UPDATE funding_sources SET {', '.join(sets)}, updated_at = now() WHERE id = %s", [*args, f["id"]])
    return await _fuente(codigo)


async def sincronizar_una(codigo: str, disparo: str = "manual", cliente=None, almacen=None) -> dict:
    """Una sincronización de una fuente (manual o programada). Las manuales se permiten aunque la fuente no esté activa: es la forma de verificarla con datos reales."""
    f = await _fuente(codigo)
    clase = cargar(f["connector"]) if f["connector"] else None
    if clase is None:
        raise ErrorFuentes("Esta fuente no tiene conector todavía: queda pendiente de verificación (no se inventan endpoints)")
    if f["integration_status"] in ("PENDING_ACCESS", "MAINTENANCE") and disparo != "manual":
        raise ErrorFuentes("La fuente no está disponible para sincronizar")
    params, _ = catalogo()
    almacen = almacen or AlmacenPG()
    r = await S.sincronizar_fuente(f, clase(f, params, cliente), almacen, params, disparo=disparo)
    await almacen.refrescar_estados(datetime.now(timezone.utc).date(), int(params["dias_proximo_cierre"]))
    return {"fuente": f["source_code"], **r}


async def sincronizar_vencidas(ahora: datetime | None = None) -> list[dict]:
    """Lo que ejecuta el calendario: cada fuente habilitada, activa y con conector cuya próxima sincronización ha llegado, aislada de las demás."""
    ahora = ahora or datetime.now(timezone.utc)
    async with await _conectar() as c:
        cur = await c.execute("SELECT source_code FROM funding_sources WHERE is_enabled AND integration_status = 'ACTIVE' AND connector IS NOT NULL AND (next_sync_at IS NULL OR next_sync_at <= %s) ORDER BY CASE source_priority WHEN 'critica' THEN 0 WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, source_code", [ahora])
        codigos = [f["source_code"] for f in await cur.fetchall()]
    salida = []
    for codigo in codigos:
        try:
            salida.append(await sincronizar_una(codigo, "schedule"))
        except Exception as e:      # noqa: BLE001 — una fuente rota no para a las demás
            log.exception("sincronización de %s", codigo)
            salida.append({"fuente": codigo, "estado": "error", "error": f"{type(e).__name__}: {e}"[:300]})
    return salida
