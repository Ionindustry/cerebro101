"""Puntuación de encaje de una licitación con el perfil de 101.cat (docs/PROYECTO_LICITACIONES.md §7.9, config/licitaciones.yaml).

Función pura y explicable: devuelve la puntuación (0–100) y las razones en castellano, para que Dirección vea POR QUÉ una licitación está arriba.
Criterios: CPV (con jerarquía), zona (Cataluña primero), importe frente al límite, días hasta el cierre y tipo de procedimiento.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

# Procedimientos (los normalizados del motor) por lo abiertos a concurrencia: más puntos cuanto más abiertos.
PROCEDIMIENTO = {
    "abierto": 1.0, "abierto_simplificado": 1.0, "abierto_simplificado_abreviado": 1.0, "restringido": 1.0, "basado_en_acuerdo_marco": 1.0,
    "negociado_con_publicidad": 0.6, "licitacion_con_negociacion": 0.6, "dialogo_competitivo": 0.6, "asociacion_innovacion": 0.6,
    "menor": 0.5, "negociado_sin_publicidad": 0.2,
}
ABIERTAS = {"abierta", "anuncio_previo"}


def estado_efectivo(estado: str | None, plazo, ahora=None) -> str | None:
    """El estado que se enseña de una licitación guardada en el Cerebro (embudo, avisos): la plataforma deja una licitación «abierta» mucho después de terminar su plazo, y lo
    que se guardó al detectarla no se entera. Una «abierta» cuyo plazo ya pasó es «cerrada» (igual que hace el motor al leer). `plazo` es un datetime con zona horaria, o None."""
    if estado != "abierta" or plazo is None:
        return estado
    ahora = ahora or datetime.now(timezone.utc)
    try:
        return "cerrada" if plazo < ahora else estado
    except TypeError:                                   # plazo sin zona horaria: no se puede comparar, se deja como está
        return estado


def prefijo(codigo: str) -> str:
    """El prefijo significativo de un CPV de 8 cifras: sin los ceros finales (72000000 → «72»), para comparar descendientes."""
    p = codigo.rstrip("0")
    return p if len(p) >= 2 else codigo[:2]


def importe_en_euros(importe: dict | None) -> Decimal | None:
    """El valor del importe del motor como decimal, o None si falta o no es en euros."""
    if not importe or (importe.get("moneda") or "EUR") != "EUR":
        return None
    try:
        return Decimal(str(importe["valor"]))
    except (InvalidOperation, KeyError, TypeError):
        return None


def _cpv(codigos: list[str], interes: list[dict]) -> tuple[float, str | None]:
    """(fracción de los puntos de CPV, razón). Exacto = todo; descendiente de uno de la lista = 0,7; ascendiente = 0,35."""
    mejor, razon = 0.0, None
    for c in codigos or []:
        for i in interes:
            lista = i["codigo"]
            if c == lista:
                return 1.0, f"CPV {c} ({i['area']})"
            if c.startswith(prefijo(lista)) and mejor < 0.7:
                mejor, razon = 0.7, f"CPV {c}, dentro de {lista} ({i['area']})"
            elif lista.startswith(prefijo(c)) and mejor < 0.35:
                mejor, razon = 0.35, f"CPV {c}, más general que {lista} ({i['area']})"
    return mejor, razon


def puntuar(item: dict, cfg: dict, ahora: datetime) -> dict:
    """Puntúa una licitación (con los campos del resumen del motor). Devuelve:
    {encaje, razones, fuera_de_importe, dias_plazo}; `encaje` es None si lo único aplicable no permite puntuar."""
    w = cfg["pesos"]
    obtenido = aplicable = 0.0
    razones: list[str] = []

    def suma(clave: str, fraccion: float, razon: str | None = None, aplica: bool = True):
        nonlocal obtenido, aplicable
        if not aplica:
            return
        aplicable += w[clave]
        obtenido += w[clave] * fraccion
        if razon:
            razones.append(razon)

    f, r = _cpv(item.get("cpv") or [], cfg["cpv"])
    suma("cpv", f, r)

    nuts = item.get("nuts") or []
    z = cfg["zona"]
    if any(n.startswith(z["prioritaria"]) for n in nuts):
        suma("zona", 1.0, "Cataluña")
    elif any(n.startswith(z["pais"]) for n in nuts):
        suma("zona", 0.6, "España")
    elif not nuts:
        suma("zona", 0.25)
    else:
        suma("zona", 0.0, "fuera de España")

    valor = importe_en_euros(item.get("importe"))
    fuera = valor is not None and valor > Decimal(str(cfg["importe_max"]))
    if valor is None:
        suma("importe", 0.4, "importe no indicado")
    elif fuera:
        suma("importe", 0.0, f"por encima de {int(cfg['importe_max']):,} €".replace(",", "."))
    else:
        suma("importe", 1.0, f"{int(valor):,} €".replace(",", "."))

    dias = None
    abierta = item.get("estado") in ABIERTAS
    plazo = item.get("plazo_presentacion")
    if abierta:
        if plazo:
            dias = (datetime.fromisoformat(plazo.replace("Z", "+00:00")) - ahora).total_seconds() / 86400
            if dias < 0:
                suma("plazo", 0.0, "plazo terminado")
            elif dias < 3:
                suma("plazo", 0.2, f"plazo muy justo ({max(int(dias), 0)} días)")
            elif dias < 7:
                suma("plazo", 0.55, f"plazo justo ({int(dias)} días)")
            else:
                suma("plazo", 1.0, f"{int(dias)} días de plazo")
        else:
            suma("plazo", 0.4, "sin plazo indicado")
    # En lo ya adjudicado o anulado el plazo no aplica: no resta ni suma.

    suma("procedimiento", PROCEDIMIENTO.get(item.get("procedimiento") or "", 0.4))
    encaje = round(100 * obtenido / aplicable) if aplicable else None
    return {"encaje": encaje, "razones": razones, "fuera_de_importe": fuera, "dias_plazo": None if dias is None else round(dias, 1)}
