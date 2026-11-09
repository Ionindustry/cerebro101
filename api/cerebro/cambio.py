"""Tipo de cambio actualizado en línea: el que publica cada día laborable el BANCO CENTRAL EUROPEO (https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml, gratuito y sin clave).

Se baja una vez al día (tarea programada, tras las 16:00 de Madrid, que es cuando lo publica), se guarda en la tabla `tipos_cambio` y `cerebro/precios.py` usa el más reciente para convertir a euros el coste de los
proveedores que trabajan en otra moneda. Si no se puede bajar (sin internet, el BCE caído), el sistema sigue con el último guardado y, si es demasiado viejo, con el de `config/precios.yaml` AVISANDO de ello.

Seguridad: la dirección es fija en el código (nadie la elige, así que no hay riesgo de que se pida a una dirección interna); el XML se lee con `defusedxml` (sin entidades externas ni «bombas»), con límite de tamaño y de tiempo,
y cada tipo se valida (positivo y razonable) antes de guardarse. El BCE da «unidades de la moneda por 1 EUR»; aquí se guarda lo contrario (euros por unidad), que es lo que se multiplica.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import httpx
import psycopg
from defusedxml import ElementTree as ET
from psycopg.rows import dict_row

from .ajustes import ajustes

log = logging.getLogger("cerebro.cambio")
URL_BCE = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
MAX_BYTES = 200_000
TIMEOUT = 20.0
AGENTE_HTTP = "Cerebro101-Cambio/0.1 (+https://101.cat)"
OCHO = Decimal("0.00000001")


class ErrorCambio(RuntimeError):
    """No se ha podido obtener o leer el tipo de cambio; el mensaje es para la persona."""


def parsear(xml: bytes) -> tuple[date, dict[str, Decimal]]:
    """(fecha, {moneda: euros por unidad}) del XML del BCE. Solo se aceptan tipos positivos y razonables; un XML raro es un error, no un dato inventado."""
    try:
        raiz = ET.fromstring(xml)
    except Exception as e:      # noqa: BLE001 — defusedxml también lanza por entidades o DTD prohibidos
        raise ErrorCambio("El XML del tipo de cambio no es válido") from e
    fecha: date | None = None
    tipos: dict[str, Decimal] = {}
    for nodo in raiz.iter():
        if nodo.tag.endswith("Cube") and nodo.get("time"):
            try:
                fecha = date.fromisoformat(nodo.get("time"))
            except ValueError:
                raise ErrorCambio("El XML del tipo de cambio trae una fecha rara") from None
        if nodo.tag.endswith("Cube") and nodo.get("currency") and nodo.get("rate"):
            moneda = nodo.get("currency").strip().upper()
            try:
                unidades_por_euro = Decimal(nodo.get("rate"))
            except Exception:  # noqa: BLE001
                continue
            if len(moneda) != 3 or not moneda.isalpha() or not unidades_por_euro.is_finite() or not Decimal("0.0001") <= unidades_por_euro <= Decimal("1000000"):
                continue
            tipos[moneda] = (1 / unidades_por_euro).quantize(OCHO, rounding=ROUND_HALF_UP)
    if fecha is None or not tipos:
        raise ErrorCambio("El XML del tipo de cambio no trae fecha o no trae tipos")
    if not Decimal("0.00000001") <= min(tipos.values()):
        raise ErrorCambio("El XML del tipo de cambio trae valores imposibles")
    return fecha, tipos


async def bajar(transporte=None) -> bytes:
    """El XML del BCE de hoy. Dirección fija, https, tamaño y tiempo acotados."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transporte, follow_redirects=False) as c:
            async with c.stream("GET", URL_BCE, headers={"User-Agent": AGENTE_HTTP, "Accept": "application/xml,text/xml"}) as r:
                if r.status_code != 200:
                    raise ErrorCambio(f"El Banco Central Europeo responde con error {r.status_code}")
                trozos, total = [], 0
                async for t in r.aiter_bytes():
                    total += len(t)
                    if total > MAX_BYTES:
                        raise ErrorCambio("La respuesta del Banco Central Europeo es demasiado grande")
                    trozos.append(t)
                return b"".join(trozos)
    except httpx.HTTPError as e:
        raise ErrorCambio(f"No se ha podido consultar el Banco Central Europeo ({type(e).__name__})") from None


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


async def guardar(fecha: date, tipos: dict[str, Decimal]) -> int:
    """Guarda (o actualiza) los tipos de ese día. Se puede repetir sin duplicar."""
    async with await _conectar() as conn:
        async with conn.transaction():
            for moneda, v in tipos.items():
                await conn.execute(
                    """INSERT INTO tipos_cambio (fecha, moneda, eur_por_unidad, fuente) VALUES (%s,%s,%s,'BCE')
                       ON CONFLICT (fecha, moneda) DO UPDATE SET eur_por_unidad = EXCLUDED.eur_por_unidad, obtenido = now()""", [fecha, moneda, v])
    return len(tipos)


async def actualizar(transporte=None) -> dict:
    """Baja los tipos del BCE y los guarda. Lo llama la tarea diaria (y `scripts/actualizar_cambio.py` a mano). Un fallo se anota en el registro y sube: la tarea lo reintenta en la pasada siguiente."""
    fecha, tipos = parsear(await bajar(transporte))
    n = await guardar(fecha, tipos)
    log.info("cambio: %d tipos del BCE de %s (USD→EUR %s)", n, fecha, tipos.get("USD"))
    return {"fecha": fecha.isoformat(), "monedas": n, "usd": str(tipos.get("USD"))}


async def ultimos(monedas: list[str] | None = None) -> dict[str, dict]:
    """El tipo más reciente de cada moneda: {moneda: {"fecha": date, "eur_por_unidad": Decimal}}. Vacío si todavía no se ha bajado ninguno."""
    async with await _conectar() as conn:
        cur = await conn.execute(
            """SELECT DISTINCT ON (moneda) moneda, fecha, eur_por_unidad FROM tipos_cambio WHERE (%s::text[] IS NULL OR moneda = ANY(%s)) ORDER BY moneda, fecha DESC""",
            [monedas, monedas])
        return {f["moneda"]: {"fecha": f["fecha"], "eur_por_unidad": f["eur_por_unidad"]} for f in await cur.fetchall()}


def hoy() -> date:
    return datetime.now(timezone.utc).date()


async def configuracion_de_precios(cfg: dict | None = None) -> dict:
    """La configuración de precios lista para calcular: la de `config/precios.yaml` (o la indicada) con el tipo de cambio en línea más reciente. Si la base no responde, se queda con el de respaldo y lo avisa en cada fila."""
    from . import precios
    c = precios.configuracion(cfg)
    ult: dict = {}
    if c["cambio_online"]["activo"]:
        try:
            ult = await ultimos()
        except Exception as e:      # noqa: BLE001 — sin base de datos el cálculo sigue con el respaldo
            log.warning("cambio: no se han podido leer los tipos guardados: %s: %s", type(e).__name__, e)
    return precios.con_cambios_en_linea(c, ult, hoy())
