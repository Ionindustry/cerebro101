"""Cotizaciones a proveedores: cuando una referencia no tiene precio en las tarifas, se le pide cotización a un proveedor que la distribuye.

REGLAS (decididas por Dirección):
  · El correo lo REDACTA SIEMPRE el sistema, con la plantilla de config/cotizaciones.yaml: no lo escribe un modelo ni una persona. Lleva SOLO tres datos: referencia, cantidad y plazo de entrega.
    Nunca el cliente, la licitación, la marca (solo sirve para elegir proveedor), precios nuestros ni nada más.
  · Dos modos, a elegir en cada caso: «enviar» (lo envía el sistema desde el buzón del departamento cuando Dirección pulsa «Enviar» y confirma en el panel; queda constancia a su nombre) y «manual»
    (el sistema deja el correo redactado para copiarlo y mandarlo una persona; después se marca como enviado).
  · La respuesta del proveedor (precio unitario, moneda, plazo, validez) se registra aquí y alimenta el coste de la partida de la oferta como «cotización de proveedor», en euros con el mismo cálculo de siempre.
  · Se crea también la «Petición de cotización» (Request for Quotation) en ERPNext, como borrador, cuando el artículo existe en el ERP; si no, se dice por qué y no bloquea nada.
Es confidencial (relación con proveedores): solo Dirección y Licitaciones.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .ajustes import ajustes

log = logging.getLogger("cerebro.cotizaciones")
DEFECTO = {"buzon_departamento": "operaciones", "dias_sin_respuesta": 3, "plazo_max_dias": 365,
           "asunto": "Solicitud de cotización · {referencia}", "saludo": "Buenos días:",
           "cuerpo": "{saludo}\n\nLes solicitamos cotización y disponibilidad del siguiente artículo:\n\n· Referencia: {referencia}\n· Cantidad: {cantidad} uds.\n· Plazo de entrega requerido: {plazo}\n\n"
                     "Les agradeceríamos que nos indicaran el precio unitario y el plazo de entrega.\n\nGracias de antemano.\n",
           "erp": {"activo": True}, "direcciones_de_prueba": []}
ESTADOS = ("borrador", "enviada", "respondida", "cancelada")
MODOS = ("enviar", "manual")
MAX_CANTIDAD = 100_000
RE_REFERENCIA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/+()#:-]{1,79}$")
MONEDAS = ("EUR", "USD", "GBP")


class ErrorCotizacion(ValueError):
    """Lo que el dato o el estado no admiten; el mensaje es para la persona."""


class NoExiste(LookupError):
    pass


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


@lru_cache(maxsize=2)
def _config(ruta: str) -> dict:
    try:
        c = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        c = {}
    cfg = {**DEFECTO, **{k: v for k, v in c.items() if k in DEFECTO}}
    cfg["dias_sin_respuesta"] = min(max(int(cfg["dias_sin_respuesta"]), 1), 60)
    cfg["plazo_max_dias"] = min(max(int(cfg["plazo_max_dias"]), 1), 730)
    cfg["direcciones_de_prueba"] = [str(d).strip().lower() for d in cfg["direcciones_de_prueba"]] if isinstance(cfg["direcciones_de_prueba"], list) else []
    cfg["erp"] = {**DEFECTO["erp"], **(cfg.get("erp") if isinstance(cfg.get("erp"), dict) else {})}
    return cfg


def configuracion() -> dict:
    return _config(str(Path(ajustes.dir_config) / "cotizaciones.yaml"))


# ---------------------------------------------------------------- validación y redacción (puras)
def validar_referencia(t) -> str:
    r = " ".join(str(t or "").split())
    if not RE_REFERENCIA.match(r):
        raise ErrorCotizacion("La referencia tiene que tener entre 2 y 80 caracteres (letras, números y . _ / - + ( ) # :)")
    return r


def validar_cantidad(v) -> int:
    try:
        if isinstance(v, bool) or (isinstance(v, float) and not v.is_integer()):
            raise ValueError
        n = int(str(v).strip())
    except (TypeError, ValueError):
        raise ErrorCotizacion("La cantidad tiene que ser un número entero") from None
    if not 1 <= n <= MAX_CANTIDAD:
        raise ErrorCotizacion(f"La cantidad tiene que estar entre 1 y {MAX_CANTIDAD:,}".replace(",", "."))
    return n


def validar_plazo(tipo, valor, cfg: dict | None = None, hoy: date | None = None) -> tuple[str, str]:
    """(«dias» | «fecha», valor normalizado). Los días, entre 1 y el máximo; la fecha, de hoy en adelante y dentro del máximo. Pura."""
    cfg = cfg or configuracion()
    hoy = hoy or date.today()
    if tipo == "dias":
        try:
            n = int(str(valor).strip())
        except (TypeError, ValueError):
            raise ErrorCotizacion("Los días de plazo tienen que ser un número entero") from None
        if not 1 <= n <= cfg["plazo_max_dias"]:
            raise ErrorCotizacion(f"El plazo tiene que estar entre 1 y {cfg['plazo_max_dias']} días")
        return "dias", str(n)
    if tipo == "fecha":
        try:
            f = date.fromisoformat(str(valor).strip())
        except ValueError:
            raise ErrorCotizacion("La fecha de entrega tiene que ser AAAA-MM-DD") from None
        if f < hoy or f > hoy + timedelta(days=cfg["plazo_max_dias"]):
            raise ErrorCotizacion(f"La fecha de entrega tiene que ser desde hoy hasta dentro de {cfg['plazo_max_dias']} días")
        return "fecha", f.isoformat()
    raise ErrorCotizacion("El plazo es «dias» o «fecha»")


def plazo_texto(tipo: str, valor: str) -> str:
    if tipo == "dias":
        return f"{valor} {'día' if valor == '1' else 'días'}"
    y, m, d = valor.split("-")
    return f"antes del {d}/{m}/{y}"


def redactar(referencia: str, cantidad: int, plazo_tipo: str, plazo_valor: str, cfg: dict | None = None) -> tuple[str, str]:
    """(asunto, cuerpo) del correo: SOLO referencia, cantidad y plazo de entrega, con la plantilla. Pura."""
    cfg = cfg or configuracion()
    datos = {"referencia": validar_referencia(referencia), "cantidad": validar_cantidad(cantidad), "plazo": plazo_texto(plazo_tipo, plazo_valor), "saludo": cfg["saludo"]}
    return str(cfg["asunto"]).format(**datos)[:200], str(cfg["cuerpo"]).format(**datos)


def direcciones_de_prueba(cfg: dict | None = None) -> list[str]:
    """Las direcciones de la propia empresa a las que se puede mandar una cotización DE PRUEBA (config/cotizaciones.yaml → direcciones_de_prueba): para ver el correo real sin molestar a un proveedor. Pura."""
    cfg = cfg or configuracion()
    return [str(d).strip().lower() for d in (cfg.get("direcciones_de_prueba") or []) if str(d).strip()]


def es_de_prueba(email, cfg: dict | None = None) -> bool:
    return str(email or "").strip().lower() in direcciones_de_prueba(cfg)


def validar_email(email: str, cfg: dict | None = None) -> str:
    """La dirección del proveedor: válida y no de la propia empresa (las reglas del correo de la empresa), salvo las direcciones de prueba que se listan expresamente en la configuración. Pura sobre la configuración de buzones."""
    from .herramientas import buzones, correo
    libres = direcciones_de_prueba(cfg)
    try:
        direccion = correo._destinatarios(str(email or "").strip(), libres)[0]
    except ValueError as e:
        raise ErrorCotizacion(str(e)) from None
    if direccion.lower() in libres:
        return direccion
    propios = [str(d).lower() for d in ((buzones.cargar().get("avisos") or {}).get("dominios") or [])]
    if direccion.rsplit("@", 1)[-1].lower() in propios:
        raise ErrorCotizacion("Una cotización se pide a un proveedor, no a una dirección de la propia empresa")
    return direccion


def _precio(v) -> Decimal:
    try:
        d = Decimal(str(v).strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        raise ErrorCotizacion("El precio no es un número") from None
    if not d.is_finite() or d <= 0 or d > Decimal("100000000") or d.as_tuple().exponent < -4:
        raise ErrorCotizacion("El precio unitario tiene que ser mayor que cero (como mucho 4 decimales)")
    return d


def validar_respuesta(datos: dict, hoy: date | None = None) -> dict:
    """La respuesta del proveedor, comprobada: precio unitario, moneda, plazo de entrega en días (opcional), validez (opcional) y nota. Pura."""
    hoy = hoy or date.today()
    moneda = str(datos.get("moneda") or "EUR").upper()
    if moneda not in MONEDAS:
        raise ErrorCotizacion(f"La moneda es una de {', '.join(MONEDAS)}")
    r = {"precio": str(_precio(datos.get("precio"))), "moneda": moneda}
    if datos.get("plazo_dias") not in (None, ""):
        try:
            n = int(str(datos["plazo_dias"]).strip())
        except ValueError:
            raise ErrorCotizacion("El plazo de entrega que da el proveedor tiene que ser un número de días") from None
        if not 0 <= n <= 730:
            raise ErrorCotizacion("El plazo de entrega que da el proveedor tiene que estar entre 0 y 730 días")
        r["plazo_dias"] = n
    if datos.get("validez_hasta") not in (None, ""):
        try:
            v = date.fromisoformat(str(datos["validez_hasta"]).strip())
        except ValueError:
            raise ErrorCotizacion("La validez de la oferta tiene que ser una fecha AAAA-MM-DD") from None
        if v < hoy:
            raise ErrorCotizacion("La validez de la oferta ya ha pasado")
        r["validez_hasta"] = v.isoformat()
    r["nota"] = " ".join(str(datos.get("nota") or "").split())[:500]
    return r


def sin_respuesta(c: dict, ahora: datetime | None = None, cfg: dict | None = None) -> bool:
    """¿Enviada hace más de N días y sin respuesta? Pura."""
    cfg = cfg or configuracion()
    ahora = ahora or datetime.now(timezone.utc)
    return c["estado"] == "enviada" and c.get("enviado_en") is not None and ahora - c["enviado_en"] > timedelta(days=cfg["dias_sin_respuesta"])


def _publica(f: dict, ahora: datetime | None = None, cfg: dict | None = None) -> dict:
    return {"id": f["id"], "licitacion": str(f["motor_id"]) if f["motor_id"] else None, "partida": f["partida_id"], "referencia": f["referencia"], "marca": f["marca"], "cantidad": f["cantidad"],
            "plazo_tipo": f["plazo_tipo"], "plazo_valor": f["plazo_valor"], "plazo": plazo_texto(f["plazo_tipo"], f["plazo_valor"]), "proveedor": f["proveedor"], "email": f["email"], "modo": f["modo"],
            "estado": f["estado"], "asunto": f["asunto"], "cuerpo": f["cuerpo"], "creado_por": f["creado_por"], "creado": f["creado"].isoformat(), "enviado_por": f["enviado_por"],
            "enviado_en": f["enviado_en"].isoformat() if f["enviado_en"] else None, "respuesta": f["respuesta"] or {}, "erp": f["erp"] or {}, "sin_respuesta": sin_respuesta(f, ahora, cfg)}


# ---------------------------------------------------------------- contactos de proveedor
async def contactos() -> list[dict]:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT proveedor, email, nombre, notas, por, actualizado FROM proveedores_contactos ORDER BY lower(proveedor)")
        return [{**f, "actualizado": f["actualizado"].isoformat()} for f in await cur.fetchall()]


async def guardar_contacto(proveedor: str, email: str, nombre: str, notas: str, por: str) -> dict:
    proveedor = " ".join(str(proveedor or "").split())
    if not 2 <= len(proveedor) <= 80:
        raise ErrorCotizacion("El proveedor tiene que tener entre 2 y 80 caracteres")
    email = validar_email(email)
    async with await _conectar() as conn:
        await conn.execute("INSERT INTO proveedores_contactos (proveedor, email, nombre, notas, por) VALUES (%s,%s,%s,%s,%s) "
                           "ON CONFLICT (proveedor) DO UPDATE SET email = EXCLUDED.email, nombre = EXCLUDED.nombre, notas = EXCLUDED.notas, por = EXCLUDED.por, actualizado = now()",
                           [proveedor, email, " ".join(str(nombre or "").split())[:80], " ".join(str(notas or "").split())[:300], por[:120]])
    return {"proveedor": proveedor, "email": email}


async def _email_de(proveedor: str) -> str | None:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT email FROM proveedores_contactos WHERE proveedor = %s", [proveedor])
        f = await cur.fetchone()
    return f["email"] if f else None


# ---------------------------------------------------------------- ciclo de una cotización
async def crear(datos: dict, por: str, cfg: dict | None = None, hoy: date | None = None) -> dict:
    """Crea la cotización en BORRADOR con el correo ya redactado. El correo del proveedor sale de su ficha de contacto si no se indica."""
    cfg = cfg or configuracion()
    referencia, cantidad = validar_referencia(datos.get("referencia")), validar_cantidad(datos.get("cantidad"))
    tipo, valor = validar_plazo(datos.get("plazo_tipo"), datos.get("plazo_valor"), cfg, hoy)
    modo = datos.get("modo")
    if modo not in MODOS:
        raise ErrorCotizacion("Elige el modo: «enviar» (lo envía el sistema cuando lo confirmes) o «manual» (lo mandas tú)")
    proveedor = " ".join(str(datos.get("proveedor") or "").split())
    if not 2 <= len(proveedor) <= 80:
        raise ErrorCotizacion("Elige el proveedor")
    email = datos.get("email") or await _email_de(proveedor)
    if not email:
        raise ErrorCotizacion(f"No hay correo de {proveedor}: añádelo en «Contactos de proveedores»")
    email = validar_email(email, cfg)
    asunto, cuerpo = redactar(referencia, cantidad, tipo, valor, cfg)
    motor = str(datos.get("licitacion") or "").strip().lower() or None
    if motor and not re.match(r"^[0-9a-f-]{36}$", motor):
        raise ErrorCotizacion("La licitación no es válida")
    async with await _conectar() as conn:
        cur = await conn.execute(
            "INSERT INTO cotizaciones (motor_id, partida_id, referencia, marca, cantidad, plazo_tipo, plazo_valor, proveedor, email, modo, asunto, cuerpo, creado_por) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            [motor, datos.get("partida") or None, referencia, " ".join(str(datos.get("marca") or "").split())[:60], cantidad, tipo, valor, proveedor, email, modo, asunto, cuerpo, por[:120]])
        f = await cur.fetchone()
    log.info("cotizaciones: %s crea la %s (%s, %s, modo %s)", por, f["id"], referencia, proveedor, modo)
    return _publica(f, cfg=cfg)


async def _cargar(cid: int, conn=None, bloquear: bool = False) -> dict:
    sql = "SELECT * FROM cotizaciones WHERE id = %s" + (" FOR UPDATE" if bloquear else "")
    if conn is None:
        async with await _conectar() as c:
            cur = await c.execute(sql, [cid])
            f = await cur.fetchone()
    else:
        cur = await conn.execute(sql, [cid])
        f = await cur.fetchone()
    if not f:
        raise NoExiste("No existe esa cotización")
    return f


async def leer(cid: int) -> dict:
    return _publica(await _cargar(cid))


async def listar(estado: str = "", licitacion: str = "", limite: int = 100) -> list[dict]:
    cond, params = [], []
    if estado:
        if estado not in ESTADOS:
            raise ErrorCotizacion("Estado desconocido")
        cond.append("estado = %s")
        params.append(estado)
    if licitacion:
        cond.append("motor_id::text = %s")
        params.append(licitacion.strip().lower())
    sql = "SELECT * FROM cotizaciones" + (" WHERE " + " AND ".join(cond) if cond else "") + " ORDER BY id DESC LIMIT %s"
    async with await _conectar() as conn:
        cur = await conn.execute(sql, [*params, min(max(int(limite), 1), 300)])
        filas = await cur.fetchall()
    cfg = configuracion()
    return [_publica(f, cfg=cfg) for f in filas]


async def _cambiar(cid: int, desde: tuple[str, ...], hacia: str, por: str, campos: dict | None = None, accion: str = "") -> dict:
    campos = campos or {}
    async with await _conectar() as conn:
        async with conn.transaction():
            f = await _cargar(cid, conn, True)
            if f["estado"] not in desde:
                raise ErrorCotizacion(f"Esta cotización está «{f['estado']}»: no se puede {accion or 'hacer eso'}")
            sets = ", ".join(f"{k} = %s" for k in campos)
            await conn.execute(f"UPDATE cotizaciones SET estado = %s, actualizado = now(){', ' + sets if sets else ''} WHERE id = %s", [hacia, *campos.values(), cid])
            f = await _cargar(cid, conn)
    log.info("cotizaciones: %s pasa la %s a %s", por, cid, hacia)
    return _publica(f)


async def marcar_enviada(cid: int, por: str) -> dict:
    """Modo manual: la persona ya ha mandado el correo."""
    f = await _cargar(cid)
    if f["modo"] != "manual":
        raise ErrorCotizacion("Esta cotización es de modo «enviar»: la envía el sistema")
    return await _cambiar(cid, ("borrador",), "enviada", por, {"enviado_por": por, "enviado_en": datetime.now(timezone.utc)}, "marcar como enviada")


async def enviar(cid: int, por: str, enviar_correo=None) -> dict:
    """Modo enviar: el sistema envía el correo YA REDACTADO desde el buzón del departamento. Lo llama quien confirma en el panel (Dirección). Si el envío falla, sigue en borrador y se dice por qué."""
    f = await _cargar(cid)
    if f["modo"] != "enviar":
        raise ErrorCotizacion("Esta cotización es de modo «manual»: la manda una persona")
    if f["estado"] != "borrador":
        raise ErrorCotizacion(f"Esta cotización está «{f['estado']}»: ya no se puede enviar")
    if enviar_correo is None:
        from .herramientas import correo
        enviar_correo = correo.enviar
    cfg = configuracion()
    try:
        if es_de_prueba(f["email"], cfg):          # a una dirección de prueba (soporte@): el asunto lo dice, para que nadie lo tome por una petición real
            await enviar_correo(cfg["buzon_departamento"], [f["email"]], "[PRUEBA] " + f["asunto"], f["cuerpo"], None, False, permitidas=[f["email"]])
        else:
            await enviar_correo(cfg["buzon_departamento"], [f["email"]], f["asunto"], f["cuerpo"], None, False)
    except Exception as e:  # noqa: BLE001 — el correo puede fallar de muchas formas (servidor, buzón, dirección): se dice y se puede reintentar
        log.warning("cotizaciones: no se ha podido enviar la %s: %s: %s", cid, type(e).__name__, e)
        raise ErrorCotizacion(f"No se ha podido enviar el correo ({str(e)[:160] or type(e).__name__}). Sigue en borrador: puedes reintentarlo o pasarla a modo manual.") from None
    return await _cambiar(cid, ("borrador",), "enviada", por, {"enviado_por": por, "enviado_en": datetime.now(timezone.utc)}, "enviar")


async def registrar_respuesta(cid: int, datos: dict, por: str, hoy: date | None = None) -> dict:
    """El proveedor ha contestado: se guarda el precio unitario, la moneda, el plazo y la validez. Vale desde borrador (te lo dijeron por teléfono) o enviada; se puede corregir mientras esté respondida."""
    r = {**validar_respuesta(datos, hoy), "por": por[:120], "fecha": datetime.now(timezone.utc).isoformat()}
    return await _cambiar(cid, ("borrador", "enviada", "respondida"), "respondida", por, {"respuesta": Jsonb(r)}, "registrar la respuesta")


async def cancelar(cid: int, por: str) -> dict:
    return await _cambiar(cid, ("borrador", "enviada"), "cancelada", por, None, "cancelar")


# ---------------------------------------------------------------- coste de las partidas
def _alnum(t) -> str:
    return re.sub(r"[^a-z0-9]", "", str(t or "").lower())


def coste_de_cotizacion(c: dict, cfg_precios: dict, hoy: date | None = None) -> dict | None:
    """La cotización respondida como un coste unitario en euros (mismo cálculo que las tarifas, canal «distribuidor»). None si ha caducado o no se puede calcular. Pura."""
    from . import precios
    hoy = hoy or date.today()
    r = c.get("respuesta") or {}
    if c["estado"] != "respondida" or not r.get("precio"):
        return None
    if r.get("validez_hasta") and date.fromisoformat(r["validez_hasta"]) < hoy:
        return None
    try:
        eur, avisos = precios.coste_en_euros(r["precio"], r.get("moneda") or "EUR", "distribuidor", cfg_precios)
    except precios.ErrorPrecios:
        return None
    return {"coste_unit_eur": eur.quantize(Decimal("0.01")), "proveedor": c["proveedor"], "canal": "cotizacion", "moneda": r.get("moneda") or "EUR", "coste_origen": r["precio"], "ref": c["referencia"],
            "marca": c.get("marca") or "", "plazo_dias": r.get("plazo_dias"), "validez_hasta": r.get("validez_hasta"), "cotizacion": c["id"], "avisos": list(dict.fromkeys(["cotización de proveedor", *avisos]))[:4]}


def emparejar(producto: str, partida_id: int | None, cotizaciones: list[dict]) -> dict | None:
    """La cotización respondida que corresponde a una partida: la ligada a ella o, si no, la de la referencia que aparece en su texto (mínimo 4 caracteres). La más reciente gana. Pura."""
    cand = [c for c in cotizaciones if c["estado"] == "respondida"]
    p = _alnum(producto)
    ligadas = [c for c in cand if partida_id is not None and c.get("partida") == partida_id]
    por_ref = [c for c in cand if len(_alnum(c["referencia"])) >= 4 and _alnum(c["referencia"]) in p]
    elegidas = ligadas or por_ref
    return max(elegidas, key=lambda c: c["id"]) if elegidas else None


async def respondidas() -> list[dict]:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT * FROM cotizaciones WHERE estado = 'respondida' ORDER BY id DESC LIMIT 500")
        return [_publica(f) for f in await cur.fetchall()]


# ---------------------------------------------------------------- ERPNext (Petición de cotización, borrador)
def doc_rfq(c: dict, item_code: str, proveedor_erp: str, hoy: date | None = None) -> dict:
    """La «Request for Quotation» en borrador para ERPNext. Lleva lo mismo que el correo (artículo, cantidad y fecha) y nada más. Pura."""
    hoy = hoy or date.today()
    entrega = hoy + timedelta(days=int(c["plazo_valor"])) if c["plazo_tipo"] == "dias" else date.fromisoformat(c["plazo_valor"])
    return {"transaction_date": hoy.isoformat(), "message_for_supplier": c["cuerpo"], "suppliers": [{"supplier": proveedor_erp}],
            "items": [{"item_code": item_code, "qty": c["cantidad"], "schedule_date": entrega.isoformat()}]}


async def enviar_al_erp(cid: int, item_code: str, por: str, crear=None, leer_item=None, leer_proveedor=None) -> dict:
    """Crea la Petición de cotización (borrador) en el ERP si el artículo y el proveedor existen allí; si no, lo dice y no bloquea nada. Guarda el resultado en la cotización."""
    cfg = configuracion()
    f = await _cargar(cid)
    if not cfg["erp"].get("activo", True):
        return await _guardar_erp(cid, {"estado": "desactivada", "motivo": "La integración con el ERP está desactivada en config/cotizaciones.yaml"})
    item_code = " ".join(str(item_code or "").split())
    if not item_code or len(item_code) > 140:
        return await _guardar_erp(cid, {"estado": "sin_articulo", "motivo": "Indica el código del artículo en el ERP (si no existe, créalo antes: no se crean artículos desde aquí)"})
    from .herramientas import erpnext
    leer_item, crear, leer_proveedor = leer_item or erpnext.leer, crear or erpnext.crear_borrador, leer_proveedor or erpnext.leer
    try:
        await leer_item("Item", item_code, "operaciones")
    except Exception:  # noqa: BLE001
        return await _guardar_erp(cid, {"estado": "sin_articulo", "motivo": f"El artículo «{item_code}» no existe en el ERP: créalo (o cárgalo con una tarifa) y vuelve a intentarlo"})
    try:
        await leer_proveedor("Supplier", f["proveedor"], "operaciones")
    except Exception:  # noqa: BLE001
        return await _guardar_erp(cid, {"estado": "sin_proveedor", "motivo": f"El proveedor «{f['proveedor']}» no existe en el ERP con ese nombre exacto"})
    try:
        d = await crear("Request for Quotation", doc_rfq(f, item_code, f["proveedor"]), "operaciones")
    except Exception as e:  # noqa: BLE001 — el ERP puede rechazarlo por muchos motivos: no bloquea la cotización
        log.warning("cotizaciones: el ERP no ha aceptado la petición de la %s: %s", cid, type(e).__name__)
        return await _guardar_erp(cid, {"estado": "error", "motivo": f"El ERP no ha aceptado la petición de cotización ({type(e).__name__}). La cotización sigue válida en Jarvis."})
    log.info("cotizaciones: %s crea la petición de cotización %s en el ERP para la %s", por, d.get("name"), cid)
    return await _guardar_erp(cid, {"estado": "creada", "nombre": str(d.get("name") or "")[:140], "item": item_code})


async def _guardar_erp(cid: int, erp: dict) -> dict:
    async with await _conectar() as conn:
        await conn.execute("UPDATE cotizaciones SET erp = %s, actualizado = now() WHERE id = %s", [Jsonb(erp), cid])
    return await leer(cid)


async def abiertas() -> list[dict]:
    """Las cotizaciones que esperan algo (en borrador o enviadas sin respuesta registrada). Para «Hoy»."""
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT * FROM cotizaciones WHERE estado IN ('borrador', 'enviada') ORDER BY id DESC LIMIT 200")
        filas = await cur.fetchall()
    cfg = configuracion()
    return [_publica(f, cfg=cfg) for f in filas]
