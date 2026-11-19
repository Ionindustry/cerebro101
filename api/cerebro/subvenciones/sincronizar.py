"""La tubería de una fuente: traer páginas → validar → normalizar → deduplicar → guardar → historial → métricas. Idempotente y aislada.

  · ejecutar dos veces con los mismos datos no crea duplicados ni historial nuevo (se compara la huella de lo que da la fuente y la de lo normalizado);
  · una oportunidad que ya existe se ACTUALIZA (con su historial de cambios): una actualización nunca crea una convocatoria nueva;
  · si una segunda fuente habla de una oportunidad que otra ya conoce, solo rellena lo que faltaba (no pisa lo que ya se sabía) y queda registrada la procedencia;
  · la marca de sincronización se guarda página a página (punto de reanudación): si se corta, la siguiente ejecución sigue desde ahí;
  · un registro inválido se cuenta y se sigue; un fallo de la fuente acaba ESA ejecución en error sin tocar las demás fuentes.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone

from . import deduplicar as D
from . import normalizar as N
from .conectores.base import ErrorConector, ErrorRegistro

log = logging.getLogger("cerebro.subvenciones.sincronizar")
ESTADOS_ACTIVA = ("ACTIVE",)


def _sin_privados(opp: dict) -> dict:
    return {k: v for k, v in opp.items() if not k.startswith("_")}


async def _resolver(almacen, codigo: str, opp: dict, externo: str) -> str | None:
    """Pasos 2 a 4 de la resolución (el paso 1, el mismo registro de la misma fuente, se hace antes): referencias, identificador propio y huella."""
    for ref in D.referencias_canonicas(opp.get("_refs")):
        clave, _, valor = ref.partition(":")
        i = await almacen.buscar_por_canonico(ref) or await almacen.buscar_por_referencia(clave, valor)
        if i:
            return i
    return await almacen.buscar_por_canonico(D.id_canonico(codigo, opp, externo))


async def guardar_registro(almacen, fuente: dict, opp: dict, crudo: dict, ahora: datetime) -> str:
    """Guarda UN registro normalizado: devuelve «nuevo», «actualizado» o «sin_cambios»."""
    fid, codigo = str(fuente["id"]), fuente["source_code"]
    externo = opp["_external_id"]
    opp = {**opp, "_raw": crudo}
    h_fuente = N.huella(crudo)
    h_norm = N.huella_normalizada(opp)
    reg = await almacen.buscar_registro(fid, externo)
    opp_id = reg["opportunity_id"] if reg else await _resolver(almacen, codigo, opp, externo)
    if opp_id is None:
        await almacen.crear(D.id_canonico(codigo, opp, externo), opp, fid, h_fuente, h_norm, ahora)
        return "nuevo"
    if reg and reg["source_hash"] == h_fuente:
        await almacen.tocar(opp_id, fid, externo, ahora, opp["status"])
        return "sin_cambios"
    actual = await almacen.obtener(opp_id)
    conocida_por = await almacen.fuentes_de(opp_id)
    rellenar_solo = bool(conocida_por) and fid not in conocida_por      # otra fuente: solo rellena lo que faltaba
    diferencias = N.cambios(actual, opp)
    if rellenar_solo:
        diferencias = [c for c in diferencias if c["old"] in (None, [], "")]
    await almacen.actualizar(opp_id, opp, diferencias, fid, h_fuente, h_norm, ahora, rellenar_solo)
    return "actualizado" if diferencias else "sin_cambios"


async def sincronizar_fuente(fuente: dict, conector, almacen, params: dict, hoy: date | None = None, disparo: str = "schedule") -> dict:
    """Ejecuta una fuente de principio a fin y deja la ejecución anotada. Nunca lanza: devuelve {estado, fetched, inserted, updated, unchanged, invalid, error}."""
    ahora = datetime.now(timezone.utc)
    hoy = hoy or ahora.date()
    fid = str(fuente["id"])
    cursor = dict(fuente.get("sync_cursor") or {})
    stats = {"fetched": 0, "inserted": 0, "updated": 0, "unchanged": 0, "invalid": 0}
    ejec = await almacen.abrir_ejecucion(fid, disparo, cursor)
    inicio, error, estado_final, ultimo_cursor = time.monotonic(), None, "ok", cursor
    try:
        async for pagina in conector.paginas(cursor, hoy):
            for crudo in pagina.registros:
                stats["fetched"] += 1
                try:
                    opp = conector.normalizar(crudo, hoy)
                    resultado = await guardar_registro(almacen, fuente, opp, crudo, datetime.now(timezone.utc))
                except ErrorRegistro as e:
                    stats["invalid"] += 1
                    log.info("%s: registro no válido (%s)", fuente["source_code"], e)
                    continue
                stats[{"nuevo": "inserted", "actualizado": "updated", "sin_cambios": "unchanged"}[resultado]] += 1
            await almacen.guardar_cursor(fid, pagina.cursor)        # punto de reanudación: solo cuando la página entera está guardada
            ultimo_cursor = pagina.cursor
        if stats["invalid"] and stats["invalid"] >= max(stats["fetched"] // 2, 1):
            estado_final, error = "partial", f"{stats['invalid']} de {stats['fetched']} registros no eran válidos: revisa el formato de la fuente"
    except ErrorConector as e:
        estado_final, error = "error", str(e)[:500]
    except Exception as e:      # noqa: BLE001 — una fuente que falla de forma inesperada no puede parar las demás
        log.exception("%s: fallo inesperado", fuente["source_code"])
        estado_final, error = "error", f"{type(e).__name__}: {str(e)[:300]}"
    ms = int((time.monotonic() - inicio) * 1000)
    try:
        await almacen.cerrar_ejecucion(ejec, fid, estado_final, stats, error, ultimo_cursor, ms, datetime.now(timezone.utc), int(fuente.get("synchronization_frequency") or 24))
    except Exception:       # noqa: BLE001
        log.exception("%s: no se pudo anotar el resultado de la ejecución", fuente["source_code"])
    return {"estado": estado_final, **stats, "error": error, "duracion_ms": ms}
