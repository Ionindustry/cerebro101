"""Estado de las copias de seguridad para ARES y aviso a soporte@ si pasan días sin una copia correcta.

Las copias las hace el servidor (scripts/copia_automatica.sh, desde una tarea de Windows): fuera de los contenedores. Esos scripts ANOTAN aquí su resultado (`python -m cerebro.copias registrar …`, por
`docker compose exec`) y de ahí salen la tarjeta «Copias de seguridad» (última copia, su tamaño, si salió bien y si la restauración se ha probado) y el vigilante: cada 6 horas (tarea
`vigilar_copias`), si hace más de `dias_sin_copia` (3) que no hay una copia CORRECTA, se avisa a soporte@ (los mismos destinatarios que los fallos del motor) y no se repite hasta pasadas 24 h. Si aún no
se ha anotado ninguna copia (se acaba de instalar), cuenta desde que se empezó a vigilar. Sin IA.

    docker compose exec -T api python -m cerebro.copias registrar <copia|restauracion> <true|false> <carpeta> <mensaje> [bytes]
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from .ajustes import ajustes

log = logging.getLogger("cerebro.copias")
DIAS_SIN_COPIA = 3
REPETIR_AVISO_H = 24
CONSERVAR = 60          # filas que se guardan de cada tipo


# ---- Ajustes que se cambian desde ARES (tabla copias_ajustes). El script de copias los lee por `python -m cerebro.copias config`; si no hay nada guardado, manda lo de siempre (.env y valores por defecto).
DEFECTOS = {"conservar": 7, "extra": "", "conservar_extra": 0, "dias_aviso": DIAS_SIN_COPIA}
# la segunda copia va a un disco o unidad que ve el servidor (WSL): /mnt/<unidad>/…, /media/<usuario>/…, /srv/… o /home/<usuario>/…; siempre dentro de una carpeta, nunca la raíz de la unidad
RE_EXTRA = re.compile(r"^/(?:mnt/[a-z]|media/[A-Za-z0-9._-]+|srv|home/[A-Za-z0-9._-]+)/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")


def _entero(valor, nombre: str, minimo: int, maximo: int) -> int:
    try:
        if isinstance(valor, bool) or (isinstance(valor, float) and not valor.is_integer()):
            raise ValueError
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        raise ValueError(f"«{nombre}» tiene que ser un número entero") from None
    if not minimo <= n <= maximo:
        raise ValueError(f"«{nombre}» tiene que estar entre {minimo} y {maximo}")
    return n


def validar(datos: dict) -> dict:
    """Los ajustes que llegan del panel, comprobados y normalizados; solo las claves conocidas y presentes. ValueError con un mensaje claro si algo no vale. Pura."""
    if not isinstance(datos, dict):
        raise ValueError("Los ajustes no tienen el formato esperado")
    desconocidas = set(datos) - set(DEFECTOS)
    if desconocidas:
        raise ValueError("Ajuste desconocido: " + ", ".join(sorted(map(str, desconocidas))))
    out: dict = {}
    if "conservar" in datos:
        out["conservar"] = _entero(datos["conservar"], "Copias que se conservan", 1, 60)
    if "conservar_extra" in datos:
        out["conservar_extra"] = _entero(datos["conservar_extra"], "Copias que se conservan en la segunda ubicación (0 = no borrar nunca)", 0, 365)
    if "dias_aviso" in datos:
        out["dias_aviso"] = _entero(datos["dias_aviso"], "Días sin copia para avisar", 1, 14)
    if "extra" in datos:
        bruta = str(datos["extra"] or "").strip()
        e = bruta.rstrip("/")
        if bruta and (not e or not RE_EXTRA.match(e) or any(parte in (".", "..") for parte in e.split("/"))):
            raise ValueError("La segunda ubicación tiene que ser una carpeta del servidor, por ejemplo /mnt/d/Copias101 (sin espacios ni símbolos raros, y dentro de una carpeta, no la raíz de la unidad)")
        out["extra"] = e
    return out


async def ajustes_guardados() -> dict:
    """Lo que hay guardado en la tabla (solo lo que alguien ha fijado desde ARES). {} si la tabla no existe o la base falla."""
    try:
        async with await _conectar() as conn:
            cur = await conn.execute("SELECT clave, valor, por, actualizado FROM copias_ajustes")
            return {f["clave"]: f for f in await cur.fetchall()}
    except Exception as e:      # noqa: BLE001 — sin ajustes se sigue con los de siempre
        log.warning("copias: no se han podido leer los ajustes: %s", type(e).__name__)
        return {}


def _valor(clave: str, texto):
    return str(texto) if clave == "extra" else int(texto)


async def en_vigor() -> dict:
    """Los ajustes en vigor: {"valores": {...}, "fijados": {clave: {por, actualizado}}}. Lo no fijado desde ARES lleva el valor por defecto (el script puede usar antes lo que ponga el .env)."""
    g = await ajustes_guardados()
    valores = dict(DEFECTOS)
    fijados = {}
    for k, f in g.items():
        if k in DEFECTOS:
            try:
                valores[k] = _valor(k, f["valor"])
                fijados[k] = {"por": f["por"], "actualizado": f["actualizado"].isoformat()}
            except (TypeError, ValueError):
                continue
    return {"valores": valores, "fijados": fijados}


async def guardar(datos: dict, por: str) -> dict:
    """Valida y guarda los ajustes que llegan (solo esas claves) y devuelve los ajustes en vigor. ValueError si algo no vale. Se aplican en la próxima copia."""
    v = validar(datos)
    if not v:
        raise ValueError("No hay ningún ajuste que guardar")
    async with await _conectar() as conn:
        for k, val in v.items():
            await conn.execute("INSERT INTO copias_ajustes (clave, valor, por) VALUES (%s,%s,%s) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, por = EXCLUDED.por, actualizado = now()", [k, str(val), por[:120]])
    log.info("copias: %s cambia los ajustes: %s", por, ", ".join(sorted(v)))
    return await en_vigor()


async def _dias_aviso() -> int:
    return int((await en_vigor())["valores"]["dias_aviso"])


def _conectar():
    return psycopg.AsyncConnection.connect(ajustes.database_url, row_factory=dict_row)


async def registrar(tipo: str, ok: bool, carpeta: str = "", mensaje: str = "", bytes_: int | None = None, ahora: datetime | None = None) -> None:
    if tipo not in ("copia", "restauracion", "aviso", "inicio"):
        raise ValueError("tipo desconocido")
    async with await _conectar() as conn:
        await conn.execute("INSERT INTO copias_registro (tipo, ok, carpeta, bytes, mensaje, creado) VALUES (%s,%s,%s,%s,%s,%s)",
                           [tipo, bool(ok), str(carpeta)[:300], bytes_, " ".join(str(mensaje).split())[:500], ahora or datetime.now(timezone.utc)])
        await conn.execute("DELETE FROM copias_registro WHERE tipo = %s AND id NOT IN (SELECT id FROM copias_registro WHERE tipo = %s ORDER BY creado DESC, id DESC LIMIT %s)", [tipo, tipo, CONSERVAR])


async def _ultima(conn, tipo: str, solo_ok: bool = False) -> dict | None:
    cur = await conn.execute(f"SELECT ok, bytes, mensaje, creado FROM copias_registro WHERE tipo = %s{' AND ok' if solo_ok else ''} ORDER BY creado DESC, id DESC LIMIT 1", [tipo])
    return await cur.fetchone()


def _fila(f: dict | None) -> dict | None:
    return None if not f else {"ok": f["ok"], "bytes": f["bytes"], "mensaje": f["mensaje"], "fecha": f["creado"].isoformat()}


def evaluar(ultima_ok: datetime | None, inicio: datetime | None, ahora: datetime, dias: int = DIAS_SIN_COPIA) -> dict:
    """Si toca alertar: {"alerta": bool, "dias_sin_copia": float|None, "motivo": str}. Cuenta desde la última copia correcta o, si no hay ninguna, desde que se empezó a vigilar. Pura."""
    desde = ultima_ok or inicio
    if desde is None:
        return {"alerta": False, "dias_sin_copia": None, "motivo": "Aún no se ha empezado a vigilar"}
    d = (ahora - desde).total_seconds() / 86400
    if d <= dias:
        return {"alerta": False, "dias_sin_copia": round(d, 1), "motivo": ""}
    motivo = (f"Hace {d:.0f} días de la última copia de seguridad correcta" if ultima_ok else f"No consta ninguna copia de seguridad correcta desde hace {d:.0f} días")
    return {"alerta": True, "dias_sin_copia": round(d, 1), "motivo": motivo}


async def estado(ahora: datetime | None = None, dias: int | None = None) -> dict:
    """Lo que enseña la tarjeta de ARES."""
    ahora = ahora or datetime.now(timezone.utc)
    dias = dias if dias is not None else await _dias_aviso()
    async with await _conectar() as conn:
        ultima, buena, rest, inicio = (await _ultima(conn, "copia"), await _ultima(conn, "copia", True), await _ultima(conn, "restauracion"), await _ultima(conn, "inicio"))
    ev = evaluar(buena["creado"] if buena else None, inicio["creado"] if inicio else None, ahora, dias)
    return {"ultima": _fila(ultima), "ultima_correcta": _fila(buena), "restauracion": _fila(rest), "dias_sin_copia": ev["dias_sin_copia"], "alerta": ev["alerta"], "motivo": ev["motivo"], "dias_limite": dias}


async def vigilar(enviar=None, ahora: datetime | None = None, dias: int | None = None) -> dict:
    """Una pasada del vigilante: avisa a soporte@ si hay que hacerlo y no se avisó ya en las últimas 24 h. Devuelve {"estado": «ok»|«avisado»|«ya_avisado»|«sin_destinatarios»|«error_correo»}."""
    ahora = ahora or datetime.now(timezone.utc)
    dias = dias if dias is not None else await _dias_aviso()
    async with await _conectar() as conn:
        buena, inicio, aviso = await _ultima(conn, "copia", True), await _ultima(conn, "inicio"), await _ultima(conn, "aviso")
    if inicio is None:
        await registrar("inicio", True, mensaje="Empieza la vigilancia de las copias", ahora=ahora)
        inicio = {"creado": ahora}
    ev = evaluar(buena["creado"] if buena else None, inicio["creado"], ahora, dias)
    if not ev["alerta"]:
        return {"estado": "ok"}
    if aviso and ahora - aviso["creado"] < timedelta(hours=REPETIR_AVISO_H):
        return {"estado": "ya_avisado"}
    from . import avisar_soporte
    ok, mal = avisar_soporte.avisar("Copia de seguridad: llevas días sin una copia correcta",
                                    f"{ev['motivo']}.\n\nSi el PC ha estado apagado, enciéndelo y lanza ./scripts/copia_automatica.sh en el servidor. Si la tarea de Windows «Cerebro - copia» no está instalada: "
                                    "powershell -ExecutionPolicy Bypass -File autoarranque.ps1 -Instalar (como administrador).", enviar)
    if not ok and not mal:
        return {"estado": "sin_destinatarios"}
    if mal and not ok:
        return {"estado": "error_correo"}
    await registrar("aviso", True, mensaje=ev["motivo"], ahora=ahora)
    return {"estado": "avisado"}


def main(argv: list[str]) -> int:
    if len(argv) >= 4 and argv[0] == "registrar":
        tipo, ok, carpeta, mensaje = argv[1], argv[2].lower() in ("true", "1", "si", "sí"), argv[3], (argv[4] if len(argv) > 4 else "")
        tam = int(argv[5]) if len(argv) > 5 and argv[5].isdigit() else None
        asyncio.run(registrar(tipo, ok, carpeta, mensaje, tam))
        return 0
    if argv[:1] == ["config"]:                        # lo que se ha fijado en ARES, como «clave=valor» (lo lee scripts/copia_automatica.sh)
        for k, f in asyncio.run(ajustes_guardados()).items():
            if k in DEFECTOS and "\n" not in str(f["valor"]):
                print(f"{k}={f['valor']}")
        return 0
    print("Uso: python -m cerebro.copias registrar <copia|restauracion> <true|false> <carpeta> <mensaje> [bytes]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
