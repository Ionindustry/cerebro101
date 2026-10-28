"""Embudo propio de licitaciones: las que 101.cat estudia, presenta, gana o pierde (docs/PROYECTO_LICITACIONES.md §8, ADR 0007 §3-4).

Vive en la tabla `licitaciones` del Cerebro (db/esquema.sql), no en el motor: el motor dice qué se ha publicado; el embudo, qué hace 101.cat con ello.
Estados: detectada → en_estudio → presentada → ganada | perdida; «descartada» es el no ir (se puede reabrir). Presentarse y firmar siguen siendo
decisiones humanas: aquí solo se anota lo que la gente decide, nunca lo decide la IA.

Lo que calcula (resumen) lo calcula esta función pura (`calcular_resumen`), no un modelo: foto por estado, lo ocurrido en el periodo, tasa de éxito,
motivos de pérdida y mediana de horas hasta decidir ir o no ir.
"""
from __future__ import annotations

import logging
import statistics
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..ajustes import ajustes
from ..herramientas import licitaciones as motor
from . import encaje as encaje_mod
from . import resumen as resumen_mod

log = logging.getLogger("cerebro.licitaciones.embudo")

ESTADOS = ("detectada", "en_estudio", "presentada", "ganada", "perdida", "descartada")

# Qué estados admite cada uno. Ganada y perdida son finales (una corrección se hace a mano en la base, no desde el panel); descartada se puede reabrir.
TRANSICIONES = {
    "detectada": {"en_estudio", "descartada"},
    "en_estudio": {"presentada", "descartada"},
    "presentada": {"ganada", "perdida"},
    "descartada": {"en_estudio"},
    "ganada": set(),
    "perdida": set(),
}

# Lista cerrada de motivos de pérdida. POR VALIDAR con Licitaciones: sin una lista cerrada no se pueden contar.
MOTIVOS_PERDIDA = {
    "precio": "Precio (oferta más cara)",
    "puntuacion_tecnica": "Puntuación técnica",
    "solvencia": "Solvencia o clasificación",
    "documentacion": "Documentación o exclusión formal",
    "plazo": "Plazo de entrega o ejecución",
    "otro": "Otro motivo",
}

MIN_DECIDIDAS = 5       # con menos licitaciones decididas, la tasa de éxito no significa nada: se devuelve sin valor
TOP_MOTIVOS = 5


class ErrorEmbudo(ValueError):
    """Una petición que el embudo no admite; el mensaje es para quien la hace."""


class NoExiste(LookupError):
    pass


class Conflicto(ErrorEmbudo):
    """La petición choca con lo que ya hay (por ejemplo, ya hay un informe en curso); el mensaje es para quien la hace."""


def validar_cambio(actual: str, nuevo: str, motivo: str | None) -> str | None:
    """Comprueba el paso de `actual` a `nuevo` y devuelve el motivo que hay que guardar (solo las perdidas lo llevan)."""
    if nuevo not in ESTADOS:
        raise ErrorEmbudo(f"Estado desconocido: {nuevo!r}")
    if nuevo not in TRANSICIONES.get(actual, set()):
        raise ErrorEmbudo(f"No se puede pasar de «{actual}» a «{nuevo}»")
    if nuevo == "perdida":
        if motivo not in MOTIVOS_PERDIDA:
            raise ErrorEmbudo("Para marcarla como perdida hay que indicar el motivo: " + ", ".join(MOTIVOS_PERDIDA))
        return motivo
    if motivo:
        raise ErrorEmbudo("Solo una licitación perdida lleva motivo de pérdida")
    return None


def fechas_del_cambio(actual: str, nuevo: str, ahora: datetime) -> dict:
    """Las fechas que se anotan al cambiar de estado (solo las que no estaban ya)."""
    f: dict = {}
    if actual == "detectada" and nuevo in ("en_estudio", "descartada"):
        f["decidida_en"] = ahora
    if nuevo == "presentada":
        f["presentada_en"] = ahora
    if nuevo in ("ganada", "perdida"):
        f["resuelta_en"] = ahora
    return f


def desde_periodo(ahora: datetime, zona: str, dias: int) -> datetime:
    """Inicio del periodo: las 00:00 (hora local) de hace `dias - 1` días. Con dias=1 es «hoy desde las 00:00»."""
    z = ZoneInfo(zona)
    hoy = ahora.astimezone(z).date()
    return datetime.combine(hoy - timedelta(days=dias - 1), datetime.min.time(), tzinfo=z).astimezone(timezone.utc)


def _en(f: datetime | None, desde: datetime, hasta: datetime) -> bool:
    return f is not None and desde <= f <= hasta


def calcular_resumen(filas: list[dict], dias: int, ahora: datetime, zona: str) -> dict:
    """El bloque «Embudo propio» del dashboard. `filas` son las filas de la tabla (estado, creado, decidida_en, presentada_en, resuelta_en,
    motivo_perdida). Pura: no toca la base de datos ni el reloj."""
    if not 1 <= dias <= 365:
        raise ErrorEmbudo("dias debe estar entre 1 y 365")
    desde, hasta = desde_periodo(ahora, zona, dias), ahora
    por_estado = {e: 0 for e in ESTADOS}
    for f in filas:
        if f["estado"] in por_estado:
            por_estado[f["estado"]] += 1
    ganadas = [f for f in filas if f["estado"] == "ganada" and _en(f.get("resuelta_en"), desde, hasta)]
    perdidas = [f for f in filas if f["estado"] == "perdida" and _en(f.get("resuelta_en"), desde, hasta)]
    decididas = len(ganadas) + len(perdidas)
    horas = [(f["decidida_en"] - f["creado"]).total_seconds() / 3600 for f in filas if _en(f.get("decidida_en"), desde, hasta) and f.get("creado")]
    motivos = Counter(f["motivo_perdida"] for f in perdidas if f.get("motivo_perdida"))
    return {
        "dias": dias, "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        "por_estado": por_estado,
        "en_periodo": {
            "detectadas": sum(1 for f in filas if _en(f.get("creado"), desde, hasta)),
            "presentadas": sum(1 for f in filas if _en(f.get("presentada_en"), desde, hasta)),
            "ganadas": len(ganadas), "perdidas": len(perdidas),
            "descartadas": sum(1 for f in filas if f["estado"] == "descartada" and _en(f.get("decidida_en"), desde, hasta)),
        },
        "tasa_exito": {"valor": round(len(ganadas) / decididas, 3) if decididas >= MIN_DECIDIDAS else None, "ganadas": len(ganadas), "decididas": decididas,
                       "minimo": MIN_DECIDIDAS},
        "motivos_perdida": [{"motivo": m, "etiqueta": MOTIVOS_PERDIDA.get(m, m), "total": n} for m, n in sorted(motivos.items(), key=lambda x: (-x[1], x[0]))[:TOP_MOTIVOS]],
        "horas_hasta_decision_p50": round(statistics.median(horas), 1) if horas else None,
    }


# ---- Datos del motor para una fila del embudo ----

def _importe_estimado(ficha: dict) -> Decimal | None:
    importes = ficha.get("importes") or []
    elegido = next((i for i in importes if i.get("significado") == "valor_estimado"), importes[0] if importes else None)
    return encaje_mod.importe_en_euros(elegido)


def datos_de_ficha(ficha: dict, cfg: dict, ahora: datetime) -> dict:
    """Los campos de una fila del embudo a partir del expediente que devuelve el motor (GET /tenders/{id}). Función pura."""
    comprador = ficha.get("comprador") or {}
    plazo = (ficha.get("plazos") or {}).get("presentacion")
    importe = next((i for i in (ficha.get("importes") or []) if i.get("significado") == "valor_estimado"), None) or (ficha.get("importes") or [None])[0]
    puntos = encaje_mod.puntuar(
        {"cpv": ficha.get("cpv"), "nuts": ficha.get("nuts"), "importe": importe, "estado": ficha.get("estado"), "plazo_presentacion": plazo,
         "procedimiento": ficha.get("procedimiento")}, cfg, ahora)
    valor = _importe_estimado(ficha)
    return {
        "motor_id": ficha["id"], "motor_version": ficha.get("version_entidad"), "expediente": ficha.get("expediente") or ficha["id"],
        "organismo": motor._corto(comprador.get("nombre"), 200) or None, "titulo": motor._corto(ficha.get("titulo"), 500) or "(sin título)",
        "cpv": [str(c) for c in (ficha.get("cpv") or [])][:20], "importe": valor, "fecha_limite": plazo, "enlace": resumen_mod._url(ficha.get("url_origen")),
        "encaje": puntos["encaje"],
    }


# ---- Base de datos ----

COLUMNAS = ("id, motor_id, motor_version, expediente, organismo, titulo, cpv, importe, fecha_limite, enlace, encaje, estado, estado_motor, motivo_perdida, "
            "decision, viabilidad, viabilidad_peticion, creado, actualizado, decidida_en, presentada_en, resuelta_en")


def _fila(f: dict) -> dict:
    out = dict(f)
    out["motor_id"] = str(f["motor_id"]) if f.get("motor_id") else None
    for k in ("importe", "encaje"):
        out[k] = float(f[k]) if isinstance(f.get(k), Decimal) else f.get(k)
    for k in ("fecha_limite", "creado", "actualizado", "decidida_en", "presentada_en", "resuelta_en"):
        out[k] = f[k].isoformat() if f.get(k) else None
    out["motivo_perdida_texto"] = MOTIVOS_PERDIDA.get(f.get("motivo_perdida") or "")
    return out


async def listar(estado: str | None = None, motor_id: str | None = None, limite: int = 200) -> list[dict]:
    if estado is not None and estado not in ESTADOS:
        raise ErrorEmbudo(f"Estado desconocido: {estado!r}")
    if motor_id is not None:
        try:
            motor_id = str(uuid.UUID(motor_id))
        except ValueError:
            raise ErrorEmbudo("motor_id no es un identificador válido") from None
    limite = max(1, min(int(limite), 500))
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute(
            f"""SELECT {COLUMNAS} FROM licitaciones WHERE (%s::text IS NULL OR estado = %s) AND (%s::uuid IS NULL OR motor_id = %s::uuid)
                ORDER BY actualizado DESC, id DESC LIMIT %s""", [estado, estado, motor_id, motor_id, limite])
        return [_fila(f) for f in await cur.fetchall()]


async def resumen(dias: int = 30, ahora: datetime | None = None) -> dict:
    if not 1 <= dias <= 365:
        raise ErrorEmbudo("dias debe estar entre 1 y 365")
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute("SELECT estado, creado, decidida_en, presentada_en, resuelta_en, motivo_perdida FROM licitaciones")
        filas = await cur.fetchall()
    return calcular_resumen(filas, dias, ahora or datetime.now(timezone.utc), ajustes.zona_horaria)


async def estudiar(motor_id: str, consulta=None, ahora: datetime | None = None) -> dict:
    """«Estudiar»: mete un expediente del motor en el embudo (o lo actualiza). Los datos los pide el servidor al motor, no los manda el navegador.
    Si ya estaba detectada, pasa a «en_estudio»; si estaba en otro estado, se conserva (solo se refrescan los datos del motor)."""
    try:
        motor_id = str(uuid.UUID(str(motor_id)))
    except ValueError:
        raise ErrorEmbudo("motor_id no es un identificador válido") from None
    ahora = ahora or datetime.now(timezone.utc)
    ficha = await (consulta or motor._get)(f"/tenders/{motor_id}")
    d = datos_de_ficha(ficha, resumen_mod.config(), ahora)
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute(
            f"""INSERT INTO licitaciones (motor_id, motor_version, expediente, organismo, titulo, cpv, importe, fecha_limite, enlace, encaje, estado, decidida_en)
                VALUES (%(motor_id)s, %(motor_version)s, %(expediente)s, %(organismo)s, %(titulo)s, %(cpv)s, %(importe)s, %(fecha_limite)s, %(enlace)s, %(encaje)s,
                        'en_estudio', %(ahora)s)
                ON CONFLICT (motor_id) DO UPDATE SET
                    motor_version = EXCLUDED.motor_version, expediente = EXCLUDED.expediente, organismo = EXCLUDED.organismo, titulo = EXCLUDED.titulo,
                    cpv = EXCLUDED.cpv, importe = EXCLUDED.importe, fecha_limite = EXCLUDED.fecha_limite, enlace = EXCLUDED.enlace, encaje = EXCLUDED.encaje,
                    estado = CASE WHEN licitaciones.estado = 'detectada' THEN 'en_estudio' ELSE licitaciones.estado END,
                    decidida_en = CASE WHEN licitaciones.estado = 'detectada' THEN %(ahora)s ELSE licitaciones.decidida_en END,
                    actualizado = %(ahora)s
                RETURNING {COLUMNAS}""", {**d, "ahora": ahora})
        return _fila(await cur.fetchone())


async def cambiar_estado(id: int, nuevo: str, motivo: str | None = None, ahora: datetime | None = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT estado FROM licitaciones WHERE id = %s FOR UPDATE", [id])
            f = await cur.fetchone()
            if not f:
                raise NoExiste("No existe esa licitación en el embudo")
            motivo = validar_cambio(f["estado"], nuevo, motivo)
            fechas = fechas_del_cambio(f["estado"], nuevo, ahora)
            sets = ["estado = %s", "motivo_perdida = %s", "actualizado = %s"] + [f"{k} = %s" for k in fechas]
            cur = await conn.execute(f"UPDATE licitaciones SET {', '.join(sets)} WHERE id = %s RETURNING {COLUMNAS}",
                                     [nuevo, motivo, ahora, *fechas.values(), id])
            return _fila(await cur.fetchone())


# ---- Lo que hace el consumidor de eventos (cerebro/licitaciones/consumidor.py): solo escribe estas dos cosas, nunca decide por la gente ----

def datos_de_resumen(item: dict, cfg: dict, ahora: datetime) -> dict:
    """Los campos de una fila del embudo a partir de un expediente de la LISTA del motor (GET /tenders: `importe` y `plazo_presentacion`, a diferencia
    de la ficha, que trae `importes` y `plazos`). Calcula el encaje con el perfil de config/licitaciones.yaml. Función pura."""
    comprador = item.get("comprador") or {}
    puntos = encaje_mod.puntuar(item, cfg, ahora)
    return {
        "motor_id": item["id"], "motor_version": item.get("version_entidad"), "expediente": item.get("expediente") or item["id"],
        "organismo": motor._corto(comprador.get("nombre"), 200) or None, "titulo": motor._corto(item.get("titulo"), 500) or "(sin título)",
        "cpv": [str(c) for c in (item.get("cpv") or [])][:20], "importe": encaje_mod.importe_en_euros(item.get("importe")),
        "fecha_limite": item.get("plazo_presentacion"), "enlace": resumen_mod._url(item.get("url_origen")), "encaje": puntos["encaje"],
        "estado_motor": item.get("estado"), "fuera_de_importe": puntos["fuera_de_importe"],
    }


def cumple_el_umbral(d: dict, encaje_min: int) -> tuple[bool, str]:
    """¿Entra en el embudo como «detectada»? Debe estar abierta, dentro del importe y con encaje suficiente. Devuelve (sí/no, motivo en una frase)."""
    if d["estado_motor"] not in encaje_mod.ABIERTAS:
        return False, f"no está abierta ({d['estado_motor']})"
    if d["fuera_de_importe"]:
        return False, "supera el importe máximo"
    if d["encaje"] is None:
        return False, "sin encaje calculable"
    if d["encaje"] < encaje_min:
        return False, f"encaje {d['encaje']} por debajo de {encaje_min}"
    return True, f"encaje {d['encaje']}"


async def registrar_detectada(d: dict, ahora: datetime | None = None) -> bool | None:
    """Alta (o refresco de datos) de una licitación detectada. Solo avanza de versión: una reentrega o un evento viejo no pisa nada. NUNCA toca el
    estado de la gente (si ya se estudia, se presentó…, se conservan). Devuelve True si es nueva, False si se ha refrescado, None si era vieja."""
    ahora = ahora or datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute(
            """INSERT INTO licitaciones (motor_id, motor_version, expediente, organismo, titulo, cpv, importe, fecha_limite, enlace, encaje, estado, estado_motor, actualizado)
               VALUES (%(motor_id)s, %(motor_version)s, %(expediente)s, %(organismo)s, %(titulo)s, %(cpv)s, %(importe)s, %(fecha_limite)s, %(enlace)s, %(encaje)s,
                       'detectada', %(estado_motor)s, %(ahora)s)
               ON CONFLICT (motor_id) DO UPDATE SET
                   motor_version = EXCLUDED.motor_version, expediente = EXCLUDED.expediente, organismo = EXCLUDED.organismo, titulo = EXCLUDED.titulo,
                   cpv = EXCLUDED.cpv, importe = EXCLUDED.importe, fecha_limite = EXCLUDED.fecha_limite, enlace = EXCLUDED.enlace, encaje = EXCLUDED.encaje,
                   estado_motor = EXCLUDED.estado_motor, actualizado = EXCLUDED.actualizado
               WHERE licitaciones.motor_version IS NULL OR licitaciones.motor_version < EXCLUDED.motor_version
               RETURNING (xmax = 0) AS nueva""", {**d, "ahora": ahora})
        fila = await cur.fetchone()
    return None if fila is None else bool(fila["nueva"])


async def actualizar_estado_motor(motor_id: str, version: int, estado_motor: str, ahora: datetime | None = None) -> str | None:
    """Anota el estado que tiene ahora el expediente en el motor (adjudicada, formalizada, anulada…) si la licitación ya está en el embudo.
    Si nadie la ha tocado (sigue «detectada») y el motor la ha ANULADO, pasa sola a «descartada»: no hay nada que valorar. Lo demás lo decide la gente;
    el panel solo avisa. Devuelve el estado del embudo tras el cambio, o None si no está en el embudo o el evento era viejo."""
    ahora = ahora or datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute(
            """UPDATE licitaciones SET estado_motor = %(em)s, motor_version = %(v)s, actualizado = %(ahora)s,
                      estado = CASE WHEN estado = 'detectada' AND %(em)s = 'anulada' THEN 'descartada' ELSE estado END
               WHERE motor_id = %(id)s AND (motor_version IS NULL OR motor_version <= %(v)s)
               RETURNING estado""", {"em": estado_motor, "v": version, "id": str(uuid.UUID(motor_id)), "ahora": ahora})
        fila = await cur.fetchone()
    return None if fila is None else fila["estado"]


# ---- Lo que usa el rastreo diario (cerebro/licitaciones/rastreo.py): el informe de Viabilidad es consultivo, nunca cambia el estado ni `decision` ----

async def pendientes_de_viabilidad(limite: int, dias_minimos: int = 3, ahora: datetime | None = None) -> list[dict]:
    """Las licitaciones «detectada» a las que aún no se ha pedido informe de viabilidad y que merece la pena valorar: siguen abiertas en el motor y su plazo, si lo
    hay, queda a más de `dias_minimos` días (con menos no da tiempo a preparar una oferta). De más a menos encaje, y a igualdad, la de plazo más próximo."""
    ahora = ahora or datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute(
            f"""SELECT {COLUMNAS} FROM licitaciones
                WHERE estado = 'detectada' AND viabilidad IS NULL AND motor_id IS NOT NULL
                  AND (estado_motor IS NULL OR estado_motor IN ('abierta','anuncio_previo'))
                  AND (fecha_limite IS NULL OR fecha_limite > %s::timestamptz + make_interval(days => %s))
                ORDER BY encaje DESC NULLS LAST, fecha_limite ASC NULLS LAST, id ASC LIMIT %s""", [ahora, dias_minimos, max(0, int(limite))])
        return [_fila(f) for f in await cur.fetchall()]


async def contar_pendientes_de_viabilidad(dias_minimos: int = 3, ahora: datetime | None = None) -> int:
    ahora = ahora or datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute(
            """SELECT count(*) AS n FROM licitaciones
               WHERE estado = 'detectada' AND viabilidad IS NULL AND motor_id IS NOT NULL
                 AND (estado_motor IS NULL OR estado_motor IN ('abierta','anuncio_previo'))
                 AND (fecha_limite IS NULL OR fecha_limite > %s::timestamptz + make_interval(days => %s))""", [ahora, dias_minimos])
        return (await cur.fetchone())["n"]


async def guardar_viabilidad(lid: int, informe: dict, reemplazar: bool = False) -> bool:
    """Guarda el informe de viabilidad de una licitación. Por defecto solo si aún no tenía (el rastreo diario nunca pisa uno anterior); con `reemplazar` (una persona lo ha
    vuelto a pedir) lo sustituye. Al guardarse se borra la petición en curso. Devuelve True si lo guarda."""
    donde = "" if reemplazar else " AND viabilidad IS NULL"
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute(f"UPDATE licitaciones SET viabilidad = %s, viabilidad_peticion = NULL WHERE id = %s{donde} RETURNING id", [Jsonb(informe), lid])
        return await cur.fetchone() is not None


ESTADOS_RESUELTOS = ("ganada", "perdida", "descartada")
VENTANA_PETICION = timedelta(minutes=20)      # una petición «en curso» más antigua se da por perdida (el trabajador se cayó) y se puede volver a pedir


async def obtener(lid: int) -> dict | None:
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        cur = await conn.execute(f"SELECT {COLUMNAS} FROM licitaciones WHERE id = %s", [lid])
        f = await cur.fetchone()
        return _fila(f) if f else None


async def reservar_peticion_viabilidad(lid: int, usuario: str, reemplazar: bool = False, ahora: datetime | None = None) -> dict:
    """Anota que una persona pide el informe de viabilidad de una licitación, antes de encolar el trabajo. Rechaza lo que no tiene sentido: una licitación que no existe
    (NoExiste), ya resuelta o sin expediente en el motor (ErrorEmbudo), o que ya tiene informe (sin `reemplazar`) o ya tiene uno en curso (Conflicto)."""
    ahora = ahora or datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT estado, motor_id, viabilidad, viabilidad_peticion FROM licitaciones WHERE id = %s FOR UPDATE", [lid])
            f = await cur.fetchone()
            if not f:
                raise NoExiste("No existe esa licitación en el embudo")
            if f["estado"] in ESTADOS_RESUELTOS:
                raise ErrorEmbudo("Esa licitación ya está resuelta: no hace falta valorar su viabilidad")
            if not f["motor_id"]:
                raise ErrorEmbudo("Esa licitación no está vinculada a un expediente del motor de licitaciones")
            p = f["viabilidad_peticion"] or {}
            if p.get("estado") == "en_curso" and _hace_menos(p.get("en"), VENTANA_PETICION, ahora):
                raise Conflicto("Ya se ha pedido el informe: está en curso")
            if f["viabilidad"] and not reemplazar:
                raise Conflicto("Esa licitación ya tiene informe de viabilidad; para pedir otro hay que confirmar que se sustituye")
            peticion = {"estado": "en_curso", "por": usuario, "en": ahora.isoformat()}
            await conn.execute("UPDATE licitaciones SET viabilidad_peticion = %s WHERE id = %s", [Jsonb(peticion), lid])
            return peticion


def _hace_menos(cuando, ventana: timedelta, ahora: datetime) -> bool:
    try:
        t = datetime.fromisoformat(str(cuando))
    except ValueError:
        return False
    return t.tzinfo is not None and ahora - t < ventana


async def cerrar_peticion_viabilidad(lid: int, error: str | None = None, ahora: datetime | None = None) -> None:
    """Termina la petición sin informe: con `error` queda anotado para que el panel lo diga; sin él, se borra."""
    ahora = ahora or datetime.now(timezone.utc)
    nuevo = Jsonb({"estado": "error", "error": str(error)[:300], "en": ahora.isoformat()}) if error else None
    async with await psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row) as conn:
        await conn.execute("UPDATE licitaciones SET viabilidad_peticion = %s WHERE id = %s", [nuevo, lid])
