"""Catálogo de productos de proveedores: buscar un producto, comparar lo que cuesta en cada proveedor, ver si tiene ficha técnica y qué cambios de tarifa hay pendientes.

Es de SOLO LECTURA y sale de lo ya cargado: las tarifas aplicadas (`importaciones_precios`), las fichas técnicas (`fichas_tecnicas`) y las actualizaciones de tarifa preparadas (`tarifas_actualizaciones`).
Los costes los calcula el código (mejor coste ya en euros con logística y cambio, como la lista de venta); el agente no calcula ni inventa cifras.
CONFIDENCIAL: las tarifas de proveedor no salen de la empresa. Tras usar esta herramienta el agente solo trabaja con modelos locales en esa petición.
"""
from __future__ import annotations

import re
from decimal import Decimal

from .. import cambio, precios
from .. import precios_venta as PV
from ..licitaciones import fichas
from .. import tarifas_auto
from .base import Herramienta, registrar

MAX_RESULTADOS = 15


def _norm(t) -> str:
    return precios.norm(t)


def _palabras(consulta: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9.\-]{1,}", _norm(consulta))][:8]


def buscar_en(ofertas: dict, cfg: dict, consulta: str = "", marca: str = "", familia: str = "", limite: int = 8) -> dict:
    """Los artículos de las tarifas que contienen TODAS las palabras de la consulta (en código, referencia, descripción, marca o familia), con su mejor coste en euros. Pura."""
    palabras, m, f = _palabras(consulta), _norm(marca), _norm(familia)
    if not palabras and not m and not f:
        raise ValueError("Indica qué buscar: una consulta (referencia, nombre…), una marca o una familia")
    limite = max(1, min(int(limite or 8), MAX_RESULTADOS))
    out, total = [], 0
    for codigo in sorted(ofertas):
        vistas = list(ofertas[codigo].values())
        o0 = vistas[0]
        texto = _norm(f"{codigo} {o0.get('ref')} {o0.get('desc')} {o0.get('marca')} {o0.get('familia')}")
        if (m and m != _norm(o0.get("marca"))) or (f and f != _norm(o0.get("familia"))) or any(w not in texto for w in palabras):
            continue
        total += 1
        if len(out) >= limite:
            continue
        mejor = precios.mejor_coste(vistas, cfg)
        out.append({"codigo": codigo, "ref": o0.get("ref"), "marca": o0.get("marca"), "familia": o0.get("familia"), "descripcion": str(o0.get("desc") or "")[:160],
                    "proveedores": len(vistas), "mejor_proveedor": mejor["proveedor"] if mejor else None, "coste_eur": str(mejor["coste_eur"].quantize(Decimal("0.01"))) if mejor else None,
                    "stock": mejor.get("stock") if mejor else None, "con_enlace_de_ficha": bool(o0.get("enlaces"))})
    return {"encontrados": total, "mostrados": len(out), "articulos": out, "aviso": None if total <= len(out) else f"Hay {total}: afina la búsqueda (marca, familia o más palabras)"}


def proveedores_en(ofertas: dict, cfg: dict, codigo: str = "", referencia: str = "") -> dict:
    """Lo que ofrece cada proveedor del mismo artículo, ordenado por coste en euros (con logística y cambio): coste, moneda, canal, stock y avisos. Pura."""
    ref = _norm(referencia)
    cod = next((c for c in ofertas if c == codigo), None) or (next((c for c in sorted(ofertas) if any(_norm(o.get("ref")) == ref for o in ofertas[c].values())), None) if ref else None)
    if not cod:
        raise LookupError("No hay ningún artículo con ese código o referencia en las tarifas cargadas")
    filas = []
    for o in ofertas[cod].values():
        try:
            c, av = precios.coste_en_euros(o["coste"], o.get("moneda", ""), o.get("canal", ""), cfg)
        except precios.ErrorPrecios as e:
            filas.append({"proveedor": o["proveedor"], "canal": o.get("canal"), "coste_origen": str(o["coste"]), "moneda": o.get("moneda"), "coste_eur": None, "stock": o.get("stock"), "avisos": [str(e)]})
            continue
        filas.append({"proveedor": o["proveedor"], "canal": o.get("canal"), "coste_origen": str(o["coste"]), "moneda": o.get("moneda"), "coste_eur": str(c.quantize(Decimal("0.01"))), "stock": o.get("stock"), "avisos": av[:3]})
    filas.sort(key=lambda x: (x["coste_eur"] is None, Decimal(x["coste_eur"]) if x["coste_eur"] else Decimal(0)))
    o0 = next(iter(ofertas[cod].values()))
    return {"codigo": cod, "ref": o0.get("ref"), "marca": o0.get("marca"), "descripcion": str(o0.get("desc") or "")[:200], "pvp_fabricante": o0.get("pvp"), "ofertas": filas,
            "nota": "El coste ya incluye la logística y el cambio del día; el precio de venta lo decide Dirección en «Precios»."}


async def _material() -> tuple[dict, dict]:
    ofertas, _sin = await PV._ofertas()
    return ofertas, await cambio.configuracion_de_precios()


async def buscar(consulta: str = "", marca: str = "", familia: str = "", limite: int = 8) -> dict:
    ofertas, cfg = await _material()
    if not ofertas:
        raise LookupError("Todavía no hay tarifas de proveedores cargadas en el ERP")
    return buscar_en(ofertas, cfg, consulta, marca, familia, limite)


async def proveedores_de(codigo: str = "", referencia: str = "") -> dict:
    ofertas, cfg = await _material()
    if not (codigo or referencia):
        raise ValueError("Indica el código o la referencia del artículo")
    return proveedores_en(ofertas, cfg, codigo, referencia)


async def ficha(referencia: str, marca: str = "") -> dict:
    """Las fichas técnicas cargadas de esa referencia (y marca) y si el texto está listo para consultarlo con «conocimiento»."""
    ref = re.sub(r"[^a-z0-9]", "", _norm(referencia))
    if len(ref) < 3:
        raise ValueError("Indica la referencia completa (mínimo 3 caracteres)")
    async with await fichas._conectar() as conn:
        cur = await conn.execute("SELECT id, marca, referencia, nombre, estado, origen, url, paginas, trozos, creado FROM fichas_tecnicas WHERE estado IN ('indexada', 'sin_texto') "
                                 "AND (regexp_replace(lower(referencia), '[^a-z0-9]', '', 'g') = %s OR regexp_replace(lower(nombre), '[^a-z0-9]', '', 'g') LIKE %s) ORDER BY id DESC LIMIT 10", [ref, f"%{ref}%"])
        filas = await cur.fetchall()
    if marca:
        filas = [f for f in filas if not f["marca"] or _norm(f["marca"]) == _norm(marca)]
    return {"referencia": referencia, "fichas": [{**{k: f[k] for k in ("id", "marca", "referencia", "nombre", "estado", "origen", "url", "paginas")}, "creado": f["creado"].isoformat()} for f in filas],
            "nota": "Para leer lo que dice una ficha, busca su texto con la herramienta «conocimiento» (departamento licitaciones) usando marca y referencia; si no hay ficha, pídela o cárgala en Licitaciones → Fichas técnicas."}


async def fichas_pendientes() -> dict:
    """De los artículos de las tarifas con enlace a ficha técnica: cuántos se podrían cargar (dominios autorizados), cuántos quedan fuera por dominio y cuántas fichas hay ya cargadas."""
    ofertas, _cfg = await _material()
    lineas = [{"ref": o.get("ref"), "marca": o.get("marca"), "enlaces": o.get("enlaces") or {}} for por in ofertas.values() for o in por.values()]
    c = fichas.candidatas(lineas, fichas.configuracion()["hosts"])
    return {"articulos": len(ofertas), "fichas_por_cargar": len(c["permitidas"]), "dominios_sin_autorizar": dict(list(c["fuera"].items())[:10]), "articulos_sin_enlace": c["sin_enlace"],
            "nota": "Se cargan desde Licitaciones → Fichas técnicas de producto. Los dominios sin autorizar los decide Dirección en config/fichas.yaml (solo dominios oficiales del fabricante)."}


async def tarifas_pendientes() -> dict:
    """Las tarifas nuevas de proveedores pendientes de revisar (con su resumen de cambios) y los proveedores cuya comprobación ha fallado. Para avisar a Dirección: el agente no las aplica."""
    d = await tarifas_auto.listar(10)
    pend = [a for a in d["actualizaciones"] if a["estado"] == "pendiente"]
    return {"pendientes": [{"id": a["id"], "proveedor": a["proveedor_id"], "fichero": a["nombre"], "cambios": {k: a["cambios"].get(k) for k in ("articulos", "nuevos", "retirados", "suben", "bajan", "variacion_media_pct", "sospechosa", "avisos", "mayores")}} for a in pend],
            "proveedores_con_error": [{"proveedor": p["id"], "error": p["error"]} for p in d["proveedores"] if p["error"]], "errores_configuracion": d["errores_configuracion"],
            "nota": "Las aplica Dirección en Jarvis → Precios; tú solo avisas."}


registrar(Herramienta(
    nombre="catalogo",
    descripcion="Catálogo de productos de proveedores ya cargados (solo lectura): buscar, comparar costes por proveedor, fichas técnicas y tarifas nuevas pendientes. Las cifras las calcula el sistema: no las recalcules. Confidencial.",
    operaciones={"buscar": buscar, "proveedores_de": proveedores_de, "ficha": ficha, "fichas_pendientes": fichas_pendientes, "tarifas_pendientes": tarifas_pendientes},
    ayuda={"buscar": "artículos con TODAS las palabras de «consulta» (o de una marca/familia): mejor coste en euros, proveedor y stock",
           "proveedores_de": "lo que ofrece cada proveedor de un artículo («codigo» o «referencia»), por coste en euros",
           "ficha": "fichas técnicas ya cargadas de una referencia",
           "fichas_pendientes": "cuántas fichas se podrían cargar y qué dominios faltan por autorizar",
           "tarifas_pendientes": "tarifas nuevas por revisar por Dirección y proveedores con fallo"},
    ejemplos={"buscar": {"consulta": "MS-C8573"}},
    confidencial=True,
))
