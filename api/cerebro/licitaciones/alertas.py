"""Alertas de licitaciones: búsquedas guardadas con aviso en el panel (docs/PROYECTO_LICITACIONES.md §8, ADR 0007 §4).

Una alerta es un filtro (el mismo que acepta GET /tenders del motor) y los eventos de los que avisar (nueva, adjudicada…). El consumidor de eventos
(consumidor.py) pregunta al MOTOR si el expediente del evento cumple el filtro —así el filtro lo evalúa siempre quien lo entiende, texto libre incluido— y,
si lo cumple, deja un aviso. Viven en el Cerebro y no en el motor porque aquí está la identidad de las personas y sus departamentos (el motor aún no la tiene:
Keycloak en la API del motor, SEC-031); el motor sigue siendo solo de lectura.

Permisos: ven y crean alertas personales quienes tienen acceso a Licitaciones; una alerta de departamento la ven los miembros del departamento (y Dirección) y la
crean o cambian el responsable de ese departamento y Dirección. Todo lo que no toca la base de datos son funciones puras, probadas por separado.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..ajustes import ajustes

EVENTOS = ("licitacion.nueva", "licitacion.modificada", "licitacion.adjudicada", "licitacion.formalizada", "licitacion.anulada")
CANALES = ("panel", "resumen_diario")      # «correo» cuando haya envío (ver db/esquema.sql)
SOLO_DEPARTAMENTO = {"resumen_diario"}       # canales que solo admite una alerta de departamento (una personal no puede salir en un resumen que ve Dirección)
AMBITOS = ("personal", "departamento")

# Quién consulta licitaciones: los mismos grupos que la pasarela del panel (panel/lib/licitaciones.js).
GRUPOS_CON_ACCESO = {"licitaciones", "direccion", "comercial", "telecom", "areas"}

ESTADOS_MOTOR = {"anuncio_previo", "abierta", "cerrada", "adjudicada", "formalizada", "anulada", "desierta"}
PROCEDIMIENTOS = {
    "abierto", "abierto_simplificado", "abierto_simplificado_abreviado", "restringido", "negociado_con_publicidad", "negociado_sin_publicidad",
    "dialogo_competitivo", "asociacion_innovacion", "licitacion_con_negociacion", "basado_en_acuerdo_marco", "menor", "otro",
}
RE_CPV = re.compile(r"^[0-9]{2,8}$")
RE_NUTS = re.compile(r"^[A-Z]{2}[0-9A-Z]{0,3}$")
RE_IMPORTE = re.compile(r"^[0-9]{1,12}(\.[0-9]{1,2})?$")
RE_COMPRADOR = re.compile(r"^(nif:[0-9A-Z]{9}|dir3:[0-9A-Z]{9,10})$")
RE_DEPARTAMENTO = re.compile(r"^[a-z0-9_-]{1,40}$")
LISTAS = {"cpv": (20, RE_CPV.match, "2 a 8 cifras"), "nuts": (20, RE_NUTS.match, "código NUTS, p. ej. ES512"),
          "estado": (7, lambda s: s in ESTADOS_MOTOR, "estado desconocido"), "procedimiento": (10, lambda s: s in PROCEDIMIENTOS, "procedimiento desconocido"),
          "comprador": (20, RE_COMPRADOR.match, "nif:XXXXXXXXX o dir3:XXXXXXXXX")}
MAX_ALERTAS_POR_PERSONA = 50


class ErrorAlerta(ValueError):
    """Una petición que las alertas no admiten; el mensaje es para quien la hace."""


class NoExiste(LookupError):
    pass


class SinPermiso(PermissionError):
    pass


# ---- Validación (pura) ----

def limpiar_filtro(f) -> dict:
    """Valida el filtro y lo devuelve normalizado (listas sin repetidos). Exige al menos un criterio: un filtro vacío avisaría de todo."""
    if not isinstance(f, dict):
        raise ErrorAlerta("El filtro debe ser un objeto")
    out: dict = {}
    for k, v in f.items():
        if k == "q":
            if not isinstance(v, str) or not 2 <= len(v.strip()) <= 200 or any(ord(c) < 32 for c in v):
                raise ErrorAlerta("filtro.q: entre 2 y 200 caracteres, sin caracteres de control")
            out["q"] = v.strip()
        elif k in LISTAS:
            tope, valido, ayuda = LISTAS[k]
            if not isinstance(v, list) or not v or len(v) > tope or not all(isinstance(x, str) and valido(x) for x in v):
                raise ErrorAlerta(f"filtro.{k}: lista de hasta {tope} valores ({ayuda})")
            out[k] = list(dict.fromkeys(v))
        elif k in ("importe_min", "importe_max"):
            if not isinstance(v, str) or not RE_IMPORTE.match(v):
                raise ErrorAlerta(f"filtro.{k}: importe decimal en euros, p. ej. 125000.50")
            out[k] = v
        else:
            raise ErrorAlerta(f"filtro.{k}: criterio desconocido (admitidos: q, {', '.join(LISTAS)}, importe_min, importe_max)")
    if not out:
        raise ErrorAlerta("El filtro no puede estar vacío: avisaría de todas las licitaciones")
    return out


def limpiar_eventos(e) -> list[str]:
    if not isinstance(e, list) or not e or not all(isinstance(x, str) and x in EVENTOS for x in e):
        raise ErrorAlerta("eventos: una lista no vacía con valores de " + ", ".join(EVENTOS))
    return [x for x in EVENTOS if x in e]            # en un orden estable y sin repetidos


def limpiar_nombre(n) -> str:
    if not isinstance(n, str) or not 1 <= len(n.strip()) <= 120 or any(ord(c) < 32 for c in n):
        raise ErrorAlerta("nombre: entre 1 y 120 caracteres")
    return n.strip()


def limpiar_canal(c, ambito: str | None = None) -> str:
    """El canal de entrega. Con `ambito` también comprueba que una alerta personal no pida un canal que solo admiten las de departamento."""
    if c not in CANALES:
        raise ErrorAlerta("canal: " + " o ".join(f"«{x}»" for x in CANALES))
    if c in SOLO_DEPARTAMENTO and ambito is not None and ambito != "departamento":
        raise ErrorAlerta("El canal «resumen_diario» es solo para alertas de departamento: el resumen lo ven Dirección y Licitaciones")
    return c


def limpiar_departamento(ambito: str, d) -> str | None:
    if ambito not in AMBITOS:
        raise ErrorAlerta("ambito: personal o departamento")
    if ambito == "personal":
        if d:
            raise ErrorAlerta("Una alerta personal no lleva departamento")
        return None
    if not isinstance(d, str) or not RE_DEPARTAMENTO.match(d):
        raise ErrorAlerta("departamento: obligatorio en una alerta de departamento")
    return d


# ---- Permisos (puros). `usuario` es cerebro.api.auth.Usuario: id, roles, departamentos ----

def con_acceso(usuario) -> bool:
    return "direccion" in usuario.roles or "servicio" in usuario.roles or bool(set(usuario.departamentos) & GRUPOS_CON_ACCESO)


def puede_crear(usuario, ambito: str, departamento: str | None) -> bool:
    if not con_acceso(usuario):
        return False
    if ambito == "personal":
        return True
    return "direccion" in usuario.roles or ("responsable" in usuario.roles and departamento in usuario.departamentos)


def puede_ver(usuario, alerta: dict) -> bool:
    if not con_acceso(usuario):
        return False
    if alerta["ambito"] == "personal":
        return alerta["propietario"] == usuario.id
    return "direccion" in usuario.roles or alerta["departamento"] in usuario.departamentos


def puede_cambiar(usuario, alerta: dict) -> bool:
    if alerta["ambito"] == "personal":
        return con_acceso(usuario) and alerta["propietario"] == usuario.id
    return puede_crear(usuario, "departamento", alerta["departamento"])


def parametros_de_consulta(filtro: dict, fuente_externa: str, id_origen: str) -> dict:
    """La consulta al motor que dice si UN expediente cumple el filtro: el filtro más la fuente y el identificador de origen."""
    return {**filtro, "fuente": fuente_externa, "id_origen": id_origen, "limit": 1}


# ---- Base de datos ----

COLUMNAS = "id, nombre, propietario, ambito, departamento, filtro, eventos, canal, activa, creada, cambiada, ultima_entrega"


def _alerta(f: dict, usuario=None) -> dict:
    out = dict(f)
    for k in ("creada", "cambiada", "ultima_entrega"):
        out[k] = f[k].isoformat() if f.get(k) else None
    out["eventos"] = list(f["eventos"])
    if usuario is not None:
        out["puede_cambiar"] = puede_cambiar(usuario, f)
    return out


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


async def listar(usuario) -> list[dict]:
    """Las alertas que ve el usuario: las suyas personales y las de sus departamentos (todas las de departamento, si es Dirección)."""
    if not con_acceso(usuario):
        raise SinPermiso("Tu usuario no tiene acceso a Licitaciones")
    async with await _conectar() as conn:
        cur = await conn.execute(f"SELECT {COLUMNAS} FROM licitaciones_alertas ORDER BY activa DESC, creada DESC, id DESC")
        filas = await cur.fetchall()
    return [_alerta(f, usuario) for f in filas if puede_ver(usuario, f)]


async def crear(usuario, datos: dict) -> dict:
    if not isinstance(datos, dict):
        raise ErrorAlerta("Petición no válida")
    ambito = datos.get("ambito")
    departamento = limpiar_departamento(ambito, datos.get("departamento"))
    if not puede_crear(usuario, ambito, departamento):
        raise SinPermiso("No puedes crear esa alerta" + (": las de un departamento las crea su responsable o Dirección" if ambito == "departamento" else ""))
    valores = (limpiar_nombre(datos.get("nombre")), usuario.id, ambito, departamento, Jsonb(limpiar_filtro(datos.get("filtro"))),
               limpiar_eventos(datos.get("eventos")), limpiar_canal(datos.get("canal", "panel"), ambito), bool(datos.get("activa", True)))
    async with await _conectar() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT count(*) AS n FROM licitaciones_alertas WHERE propietario = %s", [usuario.id])
            if (await cur.fetchone())["n"] >= MAX_ALERTAS_POR_PERSONA:
                raise ErrorAlerta(f"Has llegado al máximo de {MAX_ALERTAS_POR_PERSONA} alertas: borra alguna")
            cur = await conn.execute(
                f"""INSERT INTO licitaciones_alertas (nombre, propietario, ambito, departamento, filtro, eventos, canal, activa)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING {COLUMNAS}""", valores)
            return _alerta(await cur.fetchone(), usuario)


async def _leer(conn, aid: int, usuario, para_cambiar: bool) -> dict:
    cur = await conn.execute(f"SELECT {COLUMNAS} FROM licitaciones_alertas WHERE id = %s FOR UPDATE", [aid])
    f = await cur.fetchone()
    if f is None or not puede_ver(usuario, f):               # lo que no ves, para ti no existe
        raise NoExiste("No existe esa alerta")
    if para_cambiar and not puede_cambiar(usuario, f):
        raise SinPermiso("No puedes cambiar esa alerta")
    return f


async def cambiar(usuario, aid: int, datos: dict) -> dict:
    """Cambia nombre, filtro, eventos, canal y/o activa. El ámbito, el departamento y el dueño no se cambian: se borra y se crea otra."""
    if not con_acceso(usuario):
        raise SinPermiso("Tu usuario no tiene acceso a Licitaciones")
    if not isinstance(datos, dict) or not datos:
        raise ErrorAlerta("Indica qué cambiar")
    permitido = {"nombre", "filtro", "eventos", "activa", "canal"}
    if set(datos) - permitido:
        raise ErrorAlerta("Solo se puede cambiar: " + ", ".join(sorted(permitido)))
    nuevo: dict = {}
    if "nombre" in datos:
        nuevo["nombre"] = limpiar_nombre(datos["nombre"])
    if "filtro" in datos:
        nuevo["filtro"] = Jsonb(limpiar_filtro(datos["filtro"]))
    if "eventos" in datos:
        nuevo["eventos"] = limpiar_eventos(datos["eventos"])
    if "canal" in datos:
        nuevo["canal"] = limpiar_canal(datos["canal"])          # la regla del ámbito se comprueba abajo, con la alerta delante
    if "activa" in datos:
        if not isinstance(datos["activa"], bool):
            raise ErrorAlerta("activa: verdadero o falso")
        nuevo["activa"] = datos["activa"]
    async with await _conectar() as conn:
        async with conn.transaction():
            actual = await _leer(conn, aid, usuario, True)
            if "canal" in nuevo:
                limpiar_canal(nuevo["canal"], actual["ambito"])
            sets = ", ".join(f"{k} = %s" for k in nuevo) + ", cambiada = now()"
            cur = await conn.execute(f"UPDATE licitaciones_alertas SET {sets} WHERE id = %s RETURNING {COLUMNAS}", [*nuevo.values(), aid])
            return _alerta(await cur.fetchone(), usuario)


async def borrar(usuario, aid: int) -> None:
    if not con_acceso(usuario):
        raise SinPermiso("Tu usuario no tiene acceso a Licitaciones")
    async with await _conectar() as conn:
        async with conn.transaction():
            await _leer(conn, aid, usuario, True)
            await conn.execute("DELETE FROM licitaciones_alertas WHERE id = %s", [aid])       # sus avisos se borran con ella


# ---- Lo que usa el consumidor de eventos ----

async def activas_para(evento: str) -> list[dict]:
    """Las alertas activas que piden avisar de este tipo de evento («licitacion.nueva»…)."""
    async with await _conectar() as conn:
        cur = await conn.execute(f"SELECT {COLUMNAS} FROM licitaciones_alertas WHERE activa AND %s = ANY (eventos) ORDER BY id", [evento])
        return await cur.fetchall()


async def registrar_aviso(alerta_id: int, evento_id: str, tipo: str, d: dict, ahora: datetime | None = None) -> bool:
    """Deja el aviso de una alerta por un evento. Idempotente: el mismo evento no avisa dos veces. Devuelve True si es nuevo."""
    ahora = ahora or datetime.now(timezone.utc)
    async with await _conectar() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """INSERT INTO licitaciones_avisos (alerta_id, evento_id, tipo, motor_id, titulo, organismo, encaje, importe, fecha_limite, enlace, estado_motor, creado)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (alerta_id, evento_id) DO NOTHING RETURNING id""",
                [alerta_id, evento_id, tipo, d["motor_id"], d["titulo"], d.get("organismo"), d.get("encaje"), d.get("importe"), d.get("fecha_limite"),
                 d.get("enlace"), d.get("estado_motor"), ahora])
            nuevo = await cur.fetchone() is not None
            if nuevo:
                await conn.execute("UPDATE licitaciones_alertas SET ultima_entrega = %s WHERE id = %s", [ahora, alerta_id])
    return nuevo


async def ya_avisada(alerta_id: int, evento_id: str) -> bool:
    async with await _conectar() as conn:
        cur = await conn.execute("SELECT 1 FROM licitaciones_avisos WHERE alerta_id = %s AND evento_id = %s", [alerta_id, evento_id])
        return await cur.fetchone() is not None


# ---- Avisos (lo que ve la gente en el panel) ----

def _aviso(f: dict) -> dict:
    out = dict(f)
    out["motor_id"] = str(f["motor_id"])
    for k in ("encaje", "importe"):
        out[k] = float(f[k]) if f.get(k) is not None else None
    for k in ("fecha_limite", "creado"):
        out[k] = f[k].isoformat() if f.get(k) else None
    return out


async def listar_avisos(usuario, solo_no_leidos: bool = False, limite: int = 50) -> dict:
    """Los avisos de las alertas que ve el usuario, del más reciente al más antiguo, y cuántos hay sin leer."""
    if not con_acceso(usuario):
        raise SinPermiso("Tu usuario no tiene acceso a Licitaciones")
    limite = max(1, min(int(limite), 200))
    async with await _conectar() as conn:
        cur = await conn.execute(
            """SELECT v.id, v.alerta_id, a.nombre AS alerta, a.ambito, a.departamento, a.propietario, v.tipo, v.motor_id, v.titulo, v.organismo, v.encaje, v.importe,
                      v.fecha_limite, v.enlace, v.estado_motor, v.leido, v.creado
               FROM licitaciones_avisos v JOIN licitaciones_alertas a ON a.id = v.alerta_id ORDER BY v.creado DESC, v.id DESC""")
        filas = [f for f in await cur.fetchall() if puede_ver(usuario, f)]
    sin_leer = sum(1 for f in filas if not f["leido"])
    if solo_no_leidos:
        filas = [f for f in filas if not f["leido"]]
    return {"sin_leer": sin_leer, "items": [_aviso({k: v for k, v in f.items() if k != "propietario"}) for f in filas[:limite]]}


async def marcar_leidos(usuario, ids: list[int] | None = None) -> int:
    """Marca como leídos los avisos indicados (o todos los que ve el usuario). Es compartido: en una alerta de departamento lo lee el departamento."""
    if ids is not None and (not isinstance(ids, list) or len(ids) > 500 or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)):
        raise ErrorAlerta("ids: una lista de hasta 500 números")
    visibles = [a["id"] for a in await listar(usuario)]
    if not visibles:
        return 0
    async with await _conectar() as conn:
        cur = await conn.execute(
            "UPDATE licitaciones_avisos SET leido = true WHERE NOT leido AND alerta_id = ANY (%s) AND (%s::bigint[] IS NULL OR id = ANY (%s::bigint[]))",
            [visibles, ids, ids])
        return cur.rowcount


# ---- Lo que usa el resumen de las 16:00 (cerebro/licitaciones/resumen.py) ----

async def avisos_para_resumen(desde: datetime, hasta: datetime, por_alerta: int = 5) -> dict:
    """Los avisos del periodo [desde, hasta) de las alertas de departamento con canal «resumen_diario», agrupados por alerta. Una alerta personal no entra nunca
    (también lo impide la base de datos). Devuelve {total, items: [{alerta_id, nombre, departamento, total, avisos: [...los `por_alerta` de más encaje]}]}."""
    async with await _conectar() as conn:
        cur = await conn.execute(
            """SELECT a.id AS alerta_id, a.nombre, a.departamento, v.tipo, v.motor_id, v.titulo, v.organismo, v.encaje, v.importe, v.fecha_limite, v.estado_motor, v.creado
               FROM licitaciones_avisos v JOIN licitaciones_alertas a ON a.id = v.alerta_id
               WHERE a.canal = 'resumen_diario' AND a.ambito = 'departamento' AND v.creado >= %s AND v.creado < %s
               ORDER BY a.nombre, a.id, v.encaje DESC NULLS LAST, v.creado DESC, v.id DESC""", [desde, hasta])
        filas = await cur.fetchall()
    grupos: dict[int, dict] = {}
    for f in filas:
        g = grupos.setdefault(f["alerta_id"], {"alerta_id": f["alerta_id"], "nombre": f["nombre"], "departamento": f["departamento"], "total": 0, "avisos": []})
        g["total"] += 1
        if len(g["avisos"]) < por_alerta:
            g["avisos"].append({"motor_id": str(f["motor_id"]), "tipo": f["tipo"], "titulo": f["titulo"], "organismo": f["organismo"], "estado_motor": f["estado_motor"],
                                "encaje": float(f["encaje"]) if f["encaje"] is not None else None, "importe": float(f["importe"]) if f["importe"] is not None else None,
                                "fecha_limite": f["fecha_limite"].isoformat() if f["fecha_limite"] else None})
    return {"total": len(filas), "items": list(grupos.values())}
