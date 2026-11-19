"""Almacenes de oportunidades: PostgreSQL (el real) y en memoria (las pruebas y los ensayos). Misma interfaz.

El núcleo (sincronizar.py) solo habla con esta interfaz, así que se puede probar sin base de datos y cambiar el almacenamiento sin tocar la lógica.
"""
from __future__ import annotations

import copy
import uuid
from datetime import date, datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..ajustes import ajustes
from .normalizar import CAMPOS_SEGUIDOS, estado as estado_ciclo

COLUMNAS = ("title", "description", "program_name", "issuing_organization", "official_url", "application_url", "country", "region", "province", "municipality", "geographic_scope",
            "eligible_beneficiaries", "company_sizes", "economic_activities", "sector", "keywords", "funding_objectives", "funding_type", "total_budget", "minimum_amount",
            "maximum_amount", "funding_percentage", "currency", "cofinancing_required", "publication_date", "opening_date", "deadline", "last_official_update",
            "legal_basis_url", "eligibility_requirements", "exclusions", "eligible_expenses", "status", "confidence_score")
LISTAS = {"eligible_beneficiaries", "company_sizes", "economic_activities", "sector", "keywords"}


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


def _fila(opp: dict) -> dict:
    """Lo que se guarda de una oportunidad normalizada (solo columnas reales; _confidence → confidence_score)."""
    f = {c: opp.get(c) for c in COLUMNAS if c != "confidence_score"}
    f["confidence_score"] = opp.get("_confidence")
    for c in LISTAS:
        f[c] = list(opp.get(c) or [])
    f["currency"] = opp.get("currency") or "EUR"
    f["status"] = opp.get("status") or "UNKNOWN"
    return f


class AlmacenPG:
    """funding_* en PostgreSQL. Cada operación de escritura va en su transacción; un registro con error no deja nada a medias."""

    async def buscar_registro(self, fuente_id: str, externo: str) -> dict | None:
        async with await _conectar() as c:
            cur = await c.execute("SELECT opportunity_id::text AS opportunity_id, source_hash FROM funding_source_records WHERE source_id = %s AND external_id = %s", [fuente_id, externo])
            return await cur.fetchone()

    async def buscar_por_canonico(self, cid: str) -> str | None:
        async with await _conectar() as c:
            cur = await c.execute("SELECT id::text AS id FROM funding_opportunities WHERE canonical_id = %s", [cid])
            f = await cur.fetchone()
            return f["id"] if f else None

    async def buscar_por_referencia(self, clave: str, valor: str) -> str | None:
        async with await _conectar() as c:
            cur = await c.execute("SELECT opportunity_id::text AS id FROM funding_source_records WHERE refs ->> %s = %s LIMIT 1", [clave, valor])
            f = await cur.fetchone()
            return f["id"] if f else None

    async def obtener(self, opp_id: str) -> dict:
        async with await _conectar() as c:
            cur = await c.execute("SELECT * FROM funding_opportunities WHERE id = %s", [opp_id])
            return await cur.fetchone()

    async def fuentes_de(self, opp_id: str) -> set[str]:
        async with await _conectar() as c:
            cur = await c.execute("SELECT DISTINCT source_id::text AS s FROM funding_source_records WHERE opportunity_id = %s", [opp_id])
            return {f["s"] for f in await cur.fetchall()}

    async def _guardar_registro(self, c, opp_id: str, fuente_id: str, opp: dict, huella_fuente: str, ahora: datetime) -> None:
        await c.execute(
            """INSERT INTO funding_source_records (opportunity_id, source_id, external_id, source_url, raw, source_hash, refs, first_seen, last_seen)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (source_id, external_id) DO UPDATE SET opportunity_id = EXCLUDED.opportunity_id, source_url = EXCLUDED.source_url, raw = EXCLUDED.raw,
                 source_hash = EXCLUDED.source_hash, refs = EXCLUDED.refs, last_seen = EXCLUDED.last_seen""",
            [opp_id, fuente_id, opp["_external_id"], opp.get("_source_url"), Jsonb(opp.get("_raw")), huella_fuente, Jsonb(opp.get("_refs") or {}), ahora, ahora])
        for d in opp.get("_documents") or []:
            if d.get("url"):
                await c.execute("INSERT INTO funding_documents (opportunity_id, source_id, title, url, doc_type, detected_at) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (opportunity_id, url) DO NOTHING",
                                [opp_id, fuente_id, d.get("title"), d["url"], d.get("doc_type"), ahora])

    async def crear(self, canonico: str, opp: dict, fuente_id: str, huella_fuente: str, huella_norm: str, ahora: datetime) -> str:
        f = _fila(opp)
        cols = list(f)
        async with await _conectar() as c:
            async with c.transaction():
                cur = await c.execute(
                    f"INSERT INTO funding_opportunities (canonical_id, {', '.join(cols)}, source_hash, normalized_hash, detected_at, last_checked_at) "
                    f"VALUES (%s, {', '.join(['%s'] * len(cols))}, %s, %s, %s, %s) RETURNING id::text AS id",
                    [canonico, *[f[k] for k in cols], huella_fuente, huella_norm, ahora, ahora])
                opp_id = (await cur.fetchone())["id"]
                await self._guardar_registro(c, opp_id, fuente_id, opp, huella_fuente, ahora)
        return opp_id

    async def actualizar(self, opp_id: str, opp: dict, cambios: list[dict], fuente_id: str, huella_fuente: str, huella_norm: str, ahora: datetime, rellenar_solo: bool) -> None:
        """Aplica los cambios (con su historial). En modo `rellenar_solo` (otra fuente distinta de la que ya la conoce) solo se rellenan campos que estaban vacíos."""
        f = _fila(opp)
        async with await _conectar() as c:
            async with c.transaction():
                for ch in cambios:
                    campo = ch["field"]
                    if campo not in f:
                        continue
                    await c.execute("INSERT INTO funding_opportunity_changes (opportunity_id, source_id, changed_at, field, old_value, new_value) VALUES (%s,%s,%s,%s,%s,%s)",
                                    [opp_id, fuente_id, ahora, campo, Jsonb(ch["old"], dumps=_dumps), Jsonb(ch["new"], dumps=_dumps)])
                    await c.execute(f"UPDATE funding_opportunities SET {campo} = %s WHERE id = %s", [f[campo], opp_id])
                if rellenar_solo:       # otra fuente: rellena huecos y deja constancia, pero NO pisa el estado ni las huellas de la fuente que la conoce
                    await c.execute("UPDATE funding_opportunities SET last_checked_at = %s, updated_at = %s, ingestion_version = ingestion_version + %s WHERE id = %s",
                                    [ahora, ahora, 1 if cambios else 0, opp_id])
                else:
                    await c.execute("UPDATE funding_opportunities SET status = %s, source_hash = %s, normalized_hash = %s, last_checked_at = %s, updated_at = %s, "
                                    "ingestion_version = ingestion_version + %s WHERE id = %s",
                                    [f["status"], huella_fuente, huella_norm, ahora, ahora, 1 if cambios else 0, opp_id])
                await self._guardar_registro(c, opp_id, fuente_id, opp, huella_fuente, ahora)

    async def tocar(self, opp_id: str, fuente_id: str, externo: str, ahora: datetime, estado: str | None = None) -> None:
        async with await _conectar() as c:
            async with c.transaction():
                await c.execute("UPDATE funding_source_records SET last_seen = %s WHERE source_id = %s AND external_id = %s", [ahora, fuente_id, externo])
                if estado:
                    await c.execute("UPDATE funding_opportunities SET last_checked_at = %s, status = %s WHERE id = %s", [ahora, estado, opp_id])

    # ---- Ejecuciones y marca de sincronización ----
    async def abrir_ejecucion(self, fuente_id: str, disparo: str, cursor: dict) -> int:
        async with await _conectar() as c:
            cur = await c.execute("INSERT INTO funding_sync_runs (source_id, trigger, cursor_before) VALUES (%s,%s,%s) RETURNING id", [fuente_id, disparo, Jsonb(cursor or {})])
            return (await cur.fetchone())["id"]

    async def guardar_cursor(self, fuente_id: str, cursor: dict) -> None:
        async with await _conectar() as c:
            await c.execute("UPDATE funding_sources SET sync_cursor = %s, updated_at = now() WHERE id = %s", [Jsonb(cursor), fuente_id])

    async def cerrar_ejecucion(self, ejec_id: int, fuente_id: str, estado: str, stats: dict, error: str | None, cursor: dict, duracion_ms: int, ahora: datetime, frecuencia_h: int) -> None:
        async with await _conectar() as c:
            async with c.transaction():
                await c.execute("UPDATE funding_sync_runs SET finished_at = %s, status = %s, fetched = %s, inserted = %s, updated = %s, unchanged = %s, invalid = %s, "
                                "duration_ms = %s, error_detail = %s, cursor_after = %s WHERE id = %s",
                                [ahora, estado, stats["fetched"], stats["inserted"], stats["updated"], stats["unchanged"], stats["invalid"], duracion_ms, error, Jsonb(cursor), ejec_id])
                if estado in ("ok", "partial"):
                    await c.execute("UPDATE funding_sources SET last_sync_at = %s, last_success_at = %s, next_sync_at = %s + make_interval(hours => %s), last_error = %s, updated_at = now() WHERE id = %s",
                                    [ahora, ahora, ahora, frecuencia_h, None if estado == "ok" else error, fuente_id])
                else:
                    await c.execute("UPDATE funding_sources SET last_sync_at = %s, next_sync_at = %s + make_interval(hours => %s), last_error = %s, updated_at = now() WHERE id = %s",
                                    [ahora, ahora, frecuencia_h, error, fuente_id])

    async def refrescar_estados(self, hoy: date, dias_cierre: int) -> int:
        """Recalcula el estado del ciclo de vida de TODAS las oportunidades con el calendario de hoy (una oportunidad abierta ayer puede cerrar hoy sin que la fuente diga nada)."""
        async with await _conectar() as c:
            cur = await c.execute(
                """UPDATE funding_opportunities SET status = CASE
                     WHEN status = 'CANCELLED' THEN 'CANCELLED'
                     WHEN deadline IS NOT NULL AND deadline < %s THEN 'CLOSED'
                     WHEN opening_date IS NOT NULL AND opening_date > %s THEN 'OPENING_SOON'
                     WHEN deadline IS NOT NULL AND deadline <= %s + %s THEN 'CLOSING_SOON'
                     WHEN deadline IS NOT NULL THEN 'OPEN'
                     ELSE status END, updated_at = now()
                   WHERE status IS DISTINCT FROM CASE
                     WHEN status = 'CANCELLED' THEN 'CANCELLED'
                     WHEN deadline IS NOT NULL AND deadline < %s THEN 'CLOSED'
                     WHEN opening_date IS NOT NULL AND opening_date > %s THEN 'OPENING_SOON'
                     WHEN deadline IS NOT NULL AND deadline <= %s + %s THEN 'CLOSING_SOON'
                     WHEN deadline IS NOT NULL THEN 'OPEN'
                     ELSE status END""", [hoy, hoy, hoy, dias_cierre, hoy, hoy, hoy, dias_cierre])
            return cur.rowcount


def _dumps(v) -> str:
    import json
    return json.dumps(v, default=str, ensure_ascii=False)


class AlmacenMemoria:
    """Lo mismo en memoria: para probar la tubería sin base de datos."""

    def __init__(self):
        self.oportunidades: dict[str, dict] = {}
        self.registros: dict[tuple[str, str], dict] = {}
        self.cambios: list[dict] = []
        self.ejecuciones: list[dict] = []
        self.cursores: dict[str, dict] = {}

    async def buscar_registro(self, fuente_id, externo):
        r = self.registros.get((fuente_id, externo))
        return {"opportunity_id": r["opportunity_id"], "source_hash": r["source_hash"]} if r else None

    async def buscar_por_canonico(self, cid):
        return next((i for i, o in self.oportunidades.items() if o["canonical_id"] == cid), None)

    async def buscar_por_referencia(self, clave, valor):
        return next((r["opportunity_id"] for r in self.registros.values() if str((r["refs"] or {}).get(clave)) == valor), None)

    async def obtener(self, opp_id):
        return copy.deepcopy(self.oportunidades[opp_id])

    async def fuentes_de(self, opp_id):
        return {s for (s, _e), r in self.registros.items() if r["opportunity_id"] == opp_id}

    def _registro(self, opp_id, fuente_id, opp, huella_fuente, ahora):
        k = (fuente_id, opp["_external_id"])
        self.registros[k] = {**self.registros.get(k, {"first_seen": ahora}), "opportunity_id": opp_id, "source_hash": huella_fuente, "refs": opp.get("_refs") or {}, "raw": opp.get("_raw"), "last_seen": ahora}

    async def crear(self, canonico, opp, fuente_id, huella_fuente, huella_norm, ahora):
        opp_id = str(uuid.uuid4())
        self.oportunidades[opp_id] = {"id": opp_id, "canonical_id": canonico, **_fila(opp), "normalized_hash": huella_norm, "detected_at": ahora, "ingestion_version": 1}
        self._registro(opp_id, fuente_id, opp, huella_fuente, ahora)
        return opp_id

    async def actualizar(self, opp_id, opp, cambios, fuente_id, huella_fuente, huella_norm, ahora, rellenar_solo):
        f = _fila(opp)
        for ch in cambios:
            if ch["field"] in f:
                self.cambios.append({"opportunity_id": opp_id, "source_id": fuente_id, "changed_at": ahora, **ch})
                self.oportunidades[opp_id][ch["field"]] = f[ch["field"]]
        o = self.oportunidades[opp_id]
        if not rellenar_solo:
            o["status"] = f["status"]
            o["normalized_hash"] = huella_norm
        o["ingestion_version"] += 1 if cambios else 0
        self._registro(opp_id, fuente_id, opp, huella_fuente, ahora)

    async def tocar(self, opp_id, fuente_id, externo, ahora, estado=None):
        self.registros[(fuente_id, externo)]["last_seen"] = ahora
        if estado:
            self.oportunidades[opp_id]["status"] = estado

    async def abrir_ejecucion(self, fuente_id, disparo, cursor):
        self.ejecuciones.append({"source_id": fuente_id, "trigger": disparo, "status": "running"})
        return len(self.ejecuciones) - 1

    async def guardar_cursor(self, fuente_id, cursor):
        self.cursores[fuente_id] = cursor

    async def cerrar_ejecucion(self, ejec_id, fuente_id, estado, stats, error, cursor, duracion_ms, ahora, frecuencia_h):
        self.ejecuciones[ejec_id].update({"status": estado, **stats, "error": error, "cursor_after": cursor})

    async def refrescar_estados(self, hoy, dias_cierre):
        n = 0
        for o in self.oportunidades.values():
            nuevo = o["status"] if o["status"] == "CANCELLED" else estado_ciclo(o.get("opening_date"), o.get("deadline"), hoy, dias_cierre=dias_cierre) if (o.get("opening_date") or o.get("deadline")) else o["status"]
            if nuevo != o["status"]:
                o["status"] = nuevo
                n += 1
        return n
