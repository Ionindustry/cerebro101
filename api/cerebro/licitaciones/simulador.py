"""Simulador de ofertas: con qué baja se ha ganado en concursos parecidos y qué probabilidad y margen daría cada precio.

Todo el cálculo es código determinista sobre las adjudicaciones del motor (`/awards`); la IA no calcula importes. El modelo es DELIBERADAMENTE sencillo y se dice cuál es:

  - Se buscan concursos parecidos (mismo grupo de CPV, zona y tamaño de presupuesto; si hay pocos se amplía y se dice cómo).
  - De cada uno se toma la baja del ganador (1 − adjudicado / presupuesto base, sin IVA).
  - SUPUESTO: gana la mejor oferta económica. Entonces, ofrecer una baja b habría ganado el concurso pasado i si b supera la baja de su ganador. La probabilidad de ganar con b es
    la fracción de concursos parecidos en los que habría ganado (con su intervalo de Wilson al 95 %, que dice cuánta incertidumbre hay con tan pocos datos).
  - Si la licitación puntúa criterios de juicio de valor, el precio no decide solo y la probabilidad es optimista: se avisa.
  - Riesgo de baja anormal: de los concursos cuyo ganador bajó entre b − 5 y b + 5 puntos, cuántos fueron marcados como anormales (sin dato si hay menos de 5).
  - Margen esperado = probabilidad × (precio − coste), con el coste que indique la persona; sin coste no se recomienda precio.
  - *Backtesting*: se simula cada concurso pasado «a ciegas» con los demás y se mide si las probabilidades predichas coinciden con lo que ocurrió. Si la muestra es corta o el error
    es grande, el resultado se marca como orientativo y NO es apto para decidir.

La decisión del precio y presentar la oferta siguen siendo humanas.
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta

from ..herramientas import licitaciones as motor

log = logging.getLogger("cerebro.licitaciones.simulador")
DEFECTO = {"muestra_min": 30, "error_max": 0.10, "riesgo_anormal_max": 0.20, "paso_baja_pct": 1, "baja_max_pct": 40, "paginas_max": 5, "anios": 5, "baja_sospechosa": 0.9}


class ErrorSimulador(ValueError):
    """Lo que el simulador no puede hacer con esa licitación; el mensaje es para la persona."""


def configuracion(cfg: dict | None = None) -> dict:
    c = {**DEFECTO, **((cfg or {}).get("simulador") or {})}
    c["muestra_min"] = max(int(c["muestra_min"]), 5)
    c["paso_baja_pct"] = min(max(float(c["paso_baja_pct"]), 0.25), 5)
    c["baja_max_pct"] = min(max(float(c["baja_max_pct"]), 5), 80)
    c["paginas_max"] = min(max(int(c["paginas_max"]), 1), 10)
    return c


# ---- Estadística (pura) ----

def percentil(valores: list[float], q: float) -> float | None:
    """Percentil q (0-1) con interpolación lineal; None sin datos."""
    v = sorted(valores)
    if not v:
        return None
    if len(v) == 1:
        return v[0]
    pos = q * (len(v) - 1)
    i = int(math.floor(pos))
    j = min(i + 1, len(v) - 1)
    return v[i] + (v[j] - v[i]) * (pos - i)


def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confianza de Wilson para una proporción k/n (k puede llevar medios por los empates)."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / d
    mitad = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centro - mitad), min(1.0, centro + mitad)


def p_ganar(bajas: list[float], b: float) -> tuple[float, float, float]:
    """(probabilidad, mínimo, máximo) de ganar ofreciendo la baja b, suponiendo que gana la mejor oferta económica. Un empate cuenta medio."""
    n = len(bajas)
    if n == 0:
        return 0.0, 0.0, 1.0
    k = sum(1.0 for x in bajas if x < b) + 0.5 * sum(1 for x in bajas if x == b)
    lo, hi = wilson(k, n)
    return k / n, lo, hi


def p_anormal(muestra: list[dict], b: float, ventana: float = 0.05, minimo: int = 5) -> float | None:
    """Riesgo de baja anormal a una baja b: de los concursos cuyo ganador bajó entre b − 5 y b + 5 puntos y de los que se sabe si fue anormal, la fracción marcada como anormal.
    None con menos de `minimo` concursos (sin dato, no 0)."""
    xs = [m for m in muestra if abs(m["baja"] - b) <= ventana + 1e-9 and m.get("baja_anormal") is not None]
    if len(xs) < minimo:
        return None
    return sum(1 for m in xs if m["baja_anormal"]) / len(xs)


def curva(muestra: list[dict], presupuesto: float, coste: float | None, c: dict) -> list[dict]:
    bajas = [m["baja"] for m in muestra]
    tope = min(c["baja_max_pct"], math.ceil(((percentil(bajas, 0.95) or 0) * 100) + 5)) if bajas else c["baja_max_pct"]
    paso, b_pct, filas = c["paso_baja_pct"], 0.0, []
    while b_pct <= tope + 1e-9:
        b = b_pct / 100
        p, lo, hi = p_ganar(bajas, b)
        precio = round(presupuesto * (1 - b), 2)
        fila = {"baja_pct": round(b_pct, 2), "precio": precio, "p_ganar": round(p, 3), "p_ganar_min": round(lo, 3), "p_ganar_max": round(hi, 3), "p_anormal": None}
        pa = p_anormal(muestra, b)
        fila["p_anormal"] = None if pa is None else round(pa, 3)
        if coste is not None:
            fila["margen_esperado"] = round(p * (precio - coste), 2)
            fila["margen_si_gana"] = round(precio - coste, 2)
        filas.append(fila)
        b_pct += paso
    return filas


def recomendar(filas: list[dict], coste: float | None, riesgo_max: float) -> tuple[dict | None, str]:
    """El punto de la curva con mejor margen esperado, con precio por encima del coste y riesgo de baja anormal dentro del límite (los que no tienen dato se aceptan, y se avisa)."""
    if coste is None:
        return None, "Indica tu coste estimado (sin IVA) para ver qué precio da mejor margen esperado."
    # El riesgo de baja anormal solo puede crecer con la baja: pasado el primer punto con riesgo por encima del límite, los más bajos de precio tampoco valen aunque no tengan dato.
    corte = min((f["baja_pct"] for f in filas if f["p_anormal"] is not None and f["p_anormal"] > riesgo_max), default=None)
    validas = [f for f in filas if f["precio"] > coste and (corte is None or f["baja_pct"] < corte) and (f["p_anormal"] is None or f["p_anormal"] <= riesgo_max)]
    if not validas:
        return None, "Con ese coste ningún precio de la curva da margen positivo dentro del riesgo de baja anormal permitido."
    mejor = max(validas, key=lambda f: (f["margen_esperado"], -f["baja_pct"]))
    if mejor["margen_esperado"] <= 0:
        return None, "Con ese coste, ningún precio da un margen esperado positivo con los datos de concursos parecidos."
    return mejor, f"Mejor margen esperado dentro de un riesgo de baja anormal de hasta el {round(riesgo_max * 100)} %."


def backtest(muestra: list[dict], c: dict) -> dict:
    """Calibración con el pasado: para cada concurso, con los demás se calcula la baja que daría una probabilidad q de ganar (q = 0,1…0,9) y se mira si habría ganado ese concurso.
    Si la probabilidad predicha q coincide con la frecuencia observada, el modelo está calibrado. Devuelve el error medio |observada − predicha| y el detalle por nivel."""
    n = len(muestra)
    if n < 10:
        return {"n": n, "error_calibracion": None, "apto": False, "niveles": [], "motivo": "muestra demasiado corta para comprobarlo con el pasado"}
    niveles = []
    for q in (0.1, 0.3, 0.5, 0.7, 0.9):
        ganados = 0.0
        for i, m in enumerate(muestra):
            otros = [x["baja"] for j, x in enumerate(muestra) if j != i]
            b = percentil(otros, q)
            ganados += 1.0 if b > m["baja"] else 0.5 if b == m["baja"] else 0.0
        niveles.append({"predicha": q, "observada": round(ganados / n, 3)})
    error = sum(abs(x["observada"] - x["predicha"]) for x in niveles) / len(niveles)
    apto = n >= c["muestra_min"] and error <= c["error_max"]
    return {"n": n, "error_calibracion": round(error, 3), "apto": apto, "niveles": niveles,
            "motivo": "" if apto else ("muestra por debajo del mínimo" if n < c["muestra_min"] else "el error de calibración supera el máximo acordado")}


# ---- Lo que se pide al motor ----

def presupuesto_de(ficha: dict) -> tuple[float | None, str]:
    """El presupuesto base sin IVA de la licitación (en euros), o el valor estimado si no hay; None si no hay ninguno positivo."""
    for significado in ("presupuesto_base", "valor_estimado"):
        for i in ficha.get("importes") or []:
            if i.get("significado") == significado and i.get("impuestos") == "sin_iva" and i.get("moneda", "EUR") == "EUR":
                try:
                    v = float(i["valor"])
                except (KeyError, TypeError, ValueError):
                    continue
                if v > 0:
                    return v, significado
    return None, ""


def peso_juicio_de_valor(ficha: dict) -> float:
    return sum(float(c.get("peso") or 0) for c in ficha.get("criterios") or [] if str(c.get("tipo", "")).upper() in ("SUBJ", "JUICIO_DE_VALOR", "SUBJETIVO"))


def niveles_de_busqueda(ficha: dict, presupuesto: float) -> list[tuple[str, dict]]:
    """Del más parecido al más amplio: (descripción, parámetros de /awards)."""
    cpvs = [str(c) for c in ficha.get("cpv") or [] if str(c)]
    if not cpvs:
        raise ErrorSimulador("Esta licitación no tiene CPV: no hay con qué buscar concursos parecidos")
    nuts = [str(n).upper() for n in ficha.get("nuts") or [] if str(n)]
    cpv5, cpv3 = cpvs[0][:5], cpvs[0][:3]

    def tramo(lo, hi):
        return {"importe_min": f"{presupuesto * lo:.2f}", "importe_max": f"{presupuesto * hi:.2f}"}
    zona4 = [nuts[0][:4]] if nuts and len(nuts[0]) >= 4 else []
    zona2 = [nuts[0][:2]] if nuts and len(nuts[0]) >= 2 else []
    niv = []
    if zona4:
        niv.append((f"CPV {cpv5}…, zona {zona4[0]}, presupuesto entre 0,5× y 2×", {"cpv": [cpv5], "nuts": zona4, **tramo(0.5, 2)}))
    if zona2:
        niv.append((f"CPV {cpv5}…, zona {zona2[0]}, presupuesto entre 0,5× y 2×", {"cpv": [cpv5], "nuts": zona2, **tramo(0.5, 2)}))
    niv.append((f"CPV {cpv5}…, cualquier zona, presupuesto entre 0,5× y 2×", {"cpv": [cpv5], **tramo(0.5, 2)}))
    niv.append((f"CPV {cpv3}…, cualquier zona, presupuesto entre 0,25× y 4×", {"cpv": [cpv3], **tramo(0.25, 4)}))
    return niv


async def _leer_muestra(consulta, params: dict, excluir: str, hoy: date, c: dict) -> list[dict]:
    p = {**params, "resultado": "adjudicado", "adjudicada_desde": (hoy - timedelta(days=365 * c["anios"])).isoformat(), "orden": "fecha", "limit": 100}
    salida, cursor = [], None
    for _ in range(c["paginas_max"]):
        r = await consulta("/awards", {**p, **({"cursor": cursor} if cursor else {})})
        for x in r.get("items") or []:
            b = x.get("baja")
            try:
                b = float(b)
            except (TypeError, ValueError):
                continue
            if str(x.get("licitacion_id")) == excluir or not 0 <= b <= c["baja_sospechosa"]:
                continue
            salida.append({"baja": b, "baja_anormal": x.get("baja_anormal"), "ofertas": x.get("ofertas_recibidas"), "fecha": x.get("fecha_adjudicacion")})
        cursor = r.get("siguiente_cursor")
        if not cursor:
            break
    return salida


async def simular(motor_id: str, coste=None, consulta=None, cfg: dict | None = None, hoy: date | None = None) -> dict:
    """La simulación de una licitación. `coste` es el coste estimado sin IVA (opcional). Devuelve muestra, curva, recomendación (si hay coste) y la comprobación con el pasado."""
    c = configuracion(cfg)
    hoy = hoy or date.today()
    consulta = consulta or motor._get
    if not isinstance(motor_id, str) or not motor._UUID.match(motor_id):
        raise ErrorSimulador("licitacion debe ser el identificador (UUID) de la licitación")
    if coste is not None:
        try:
            coste = float(coste)
        except (TypeError, ValueError):
            raise ErrorSimulador("El coste debe ser un número en euros, sin IVA") from None
        if not 0 < coste < 1e10:
            raise ErrorSimulador("El coste debe ser un número positivo en euros, sin IVA")
    ficha = await consulta(f"/tenders/{motor_id}")
    presupuesto, origen = presupuesto_de(ficha)
    if presupuesto is None:
        raise ErrorSimulador("Esta licitación no tiene presupuesto base ni valor estimado sin IVA: no se puede calcular la baja")
    elegido, mejor = None, ([], "", {})
    for descripcion, params in niveles_de_busqueda(ficha, presupuesto):
        m = await _leer_muestra(consulta, params, motor_id, hoy, c)
        if len(m) > len(mejor[0]):
            mejor = (m, descripcion, params)
        if len(m) >= c["muestra_min"]:
            elegido = mejor = (m, descripcion, params)
            break
    muestra, descripcion, _ = mejor
    suficiente = elegido is not None
    avisos = []
    if not muestra:
        raise ErrorSimulador("El motor no tiene adjudicaciones de concursos parecidos (¿histórico sin cargar?): no se puede simular")
    if not suficiente:
        avisos.append(f"Solo hay {len(muestra)} concursos parecidos (se piden al menos {c['muestra_min']}): la estimación es muy incierta")
    if elegido is not None and descripcion != niveles_de_busqueda(ficha, presupuesto)[0][0]:
        avisos.append("No había suficientes concursos tan parecidos como se quería: se ha ampliado la búsqueda («" + descripcion + "»)")
    pv = peso_juicio_de_valor(ficha)
    if pv > 0:
        avisos.append(f"Esta licitación puntúa un {pv:g} % por juicio de valor: el precio no decide solo, así que la probabilidad de ganar es optimista")
    bajas = [m["baja"] for m in muestra]
    filas = curva(muestra, presupuesto, coste, c)
    reco, motivo = recomendar(filas, coste, c["riesgo_anormal_max"])
    bt = backtest(muestra, c)
    if reco and reco["p_anormal"] is None:
        avisos.append("Sin datos suficientes del riesgo de baja anormal a ese precio: compruébalo en el pliego antes de ofertar")
    apto = suficiente and bt["apto"] and pv == 0
    fechas = sorted(m["fecha"] for m in muestra if m.get("fecha"))
    anormales = [m["baja_anormal"] for m in muestra if m.get("baja_anormal") is not None]
    ofertas = [m["ofertas"] for m in muestra if isinstance(m.get("ofertas"), int)]
    return {
        "licitacion": {"id": motor_id, "titulo": str(ficha.get("titulo") or "")[:200], "presupuesto": presupuesto, "presupuesto_origen": origen, "moneda": "EUR", "peso_juicio_de_valor": pv},
        "muestra": {"n": len(muestra), "suficiente": suficiente, "mercado": descripcion, "desde": fechas[0] if fechas else None, "hasta": fechas[-1] if fechas else None,
                    "ofertas_medias": round(sum(ofertas) / len(ofertas), 1) if ofertas else None},
        "bajas": {k: None if (v := percentil(bajas, q)) is None else round(v * 100, 2) for k, q in (("p10", .1), ("p25", .25), ("p50", .5), ("p75", .75), ("p90", .9))}
                 | {"media": round(sum(bajas) / len(bajas) * 100, 2), "con_baja_anormal_pct": round(sum(1 for a in anormales if a) / len(anormales) * 100, 1) if anormales else None},
        "curva": filas, "coste": coste, "recomendacion": reco, "motivo_recomendacion": motivo, "backtest": bt, "apto_para_decidir": apto, "avisos": avisos,
        "supuestos": ["Gana la mejor oferta económica (el precio decide solo).", "Los concursos parecidos de los últimos años se repiten: baja de su ganador = lo que habría que superar.",
                      "La baja es 1 − adjudicado / presupuesto base, sin IVA; solo cuentan concursos con ese dato fiable."],
        "nota": "Estimación orientativa de código determinista: el precio y la decisión de presentarse son siempre de una persona." + ("" if apto else " NO es apta para decidir por sí sola."),
    }
