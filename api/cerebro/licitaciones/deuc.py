"""El DEUC base de cada sociedad, subido desde Jarvis.

La persona sube al chat el DEUC ya rellenado con los datos de la empresa (Word o PDF con formulario) y le pide a Jarvis que lo guarde para una sociedad. El agente PROPONE la acción
(`plantillas.guardar_deuc`); una persona la aprueba viendo qué fichero es y para qué sociedad; solo entonces se guarda. El fichero ya pasó por la cuarentena y el antivirus de las subidas
(cerebro/subidas.py); aquí se comprueba además que es lo que dice ser (un Word de verdad, o un PDF CON campos de formulario) y que no lleva macros.

Se guarda en el volumen de datos (DEUC_DIR/<sociedad>/<sha256>.<formato>), no en la ficha de empresa del ERP: adjuntar un fichero a una Company obliga a dar al usuario técnico permiso de
ESCRITURA sobre las empresas, y eso no se concede. La versión más reciente de cada sociedad es la que se usa en las ofertas (`empresa.deuc_base`); las anteriores se conservan.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
from pathlib import Path

from .. import subidas as S
from . import conversion_local as L
from . import empresa as E
from . import formularios as F
from . import ofertas as O

log = logging.getLogger("cerebro.licitaciones.deuc")
DIR = Path(os.environ.get("DEUC_DIR", "/datos/licitaciones/deuc"))
FORMATOS = ("docx", "pdf")


class ErrorDeuc(ValueError):
    """Lo que el documento o la petición no admiten; el mensaje es para la persona."""


def _carpeta(empresa: str) -> Path:
    # el nombre de la sociedad viene del ERP (ya validado contra la lista); aun así, solo caracteres seguros para el nombre de carpeta
    return DIR / (re.sub(r"[^\w.\-]+", "_", empresa, flags=re.UNICODE).strip("._")[:80] or "sociedad")


async def _revisar(documento: str, empresa: str | None) -> tuple[str, dict, Path]:
    """Comprueba el documento subido y la sociedad. Devuelve (sociedad, ficha del documento, ruta del fichero limpio). ErrorDeuc con un mensaje para la persona si no sirve."""
    try:
        nombre_empresa = await E.elegir(empresa)
    except E.VariasEmpresas as e:
        raise ErrorDeuc("Hay varias sociedades en el ERP: indica para cuál es el DEUC. Sociedades: " + ", ".join(x["nombre"] for x in e.empresas)) from None
    except E.ErrorEmpresa as e:
        raise ErrorDeuc(str(e)) from None
    try:
        did = S._id(documento)
        async with await S._conectar() as conn:
            f = await S._disponible(conn, did)
    except (S.ErrorSubida, S.NoExiste) as e:
        raise ErrorDeuc(str(e)) from None
    if f["estado"] != "limpio":
        raise ErrorDeuc("Ese documento lleva macros: no se admite como DEUC (guárdalo sin macros)")
    if f["formato"] not in FORMATOS:
        raise ErrorDeuc(f"El DEUC base tiene que ser un Word (.docx) o un PDF con formulario; este documento es {f['formato']}")
    ruta = S._carpeta("limpio") / f"{did}.{f['formato']}"
    if not ruta.is_file():
        raise ErrorDeuc("El fichero del documento ya no está disponible: vuelve a subirlo")
    if f["formato"] == "docx" and not L.es_docx(ruta):
        raise ErrorDeuc("El documento no es un Word (.docx) válido")
    if f["formato"] == "pdf":
        try:
            det = await asyncio.to_thread(F.ejecutar_aislado, {"accion": "detectar", "ruta": str(ruta), "formato": "pdf"})
        except F.ErrorFormulario as e:
            raise ErrorDeuc(f"No se ha podido leer el PDF: {e}") from None
        if not det["campos"]:
            raise ErrorDeuc("Ese PDF no tiene campos de formulario editables, así que no se puede rellenar. Súbelo en Word (.docx) o como PDF con formulario")
    return nombre_empresa, f, ruta


async def vista(documento: str, empresa: str | None = None, **_) -> dict:
    """Lo que ve quien aprueba: qué fichero se guarda y para qué sociedad. Falla antes de pedir aprobación si el documento no sirve."""
    sociedad, f, _ruta = await _revisar(documento, empresa)
    actual = await actual_de(sociedad)
    return {"titulo": f"Guardar el DEUC base de «{sociedad}»",
            "campos": [["Sociedad", sociedad], ["Fichero", f["nombre"]], ["Formato", "Word (.docx)" if f["formato"] == "docx" else "PDF con formulario"],
                       ["Tamaño", f"{f['bytes'] / 1024:.0f} KB"],
                       ["Sustituye a", f"{actual['nombre']} (subido el {actual['creado'][:10]})" if actual else "(no había ninguno)"],
                       ["Para qué", "Es el DEUC que se copiará a cada oferta de esta sociedad; en cada concurso solo se rellenan los campos propios del concurso. Se conservan las versiones anteriores."]]}


async def guardar(documento: str, empresa: str | None = None, por: str = "agente") -> dict:
    """Guarda el documento subido como DEUC base de la sociedad. Lo llama la herramienta SOLO tras la aprobación de una persona."""
    sociedad, f, ruta = await _revisar(documento, empresa)
    datos = ruta.read_bytes()
    sha = hashlib.sha256(datos).hexdigest()
    destino = _carpeta(sociedad) / f"{sha}.{f['formato']}"
    destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    shutil.copyfile(ruta, tmp)
    os.chmod(tmp, 0o600)
    tmp.replace(destino)
    async with await O._conectar() as conn:
        cur = await conn.execute("INSERT INTO deuc_base (empresa, nombre, formato, sha256, bytes, por) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", [sociedad, f["nombre"], f["formato"], sha, len(datos), str(por)[:200]])
        did = (await cur.fetchone())["id"]
    log.info("deuc: %s guarda «%s» como DEUC base de %s (%s, %d bytes)", por, f["nombre"], sociedad, f["formato"], len(datos))
    return {"guardado": True, "id": did, "sociedad": sociedad, "fichero": f["nombre"], "formato": f["formato"]}


async def actual_de(empresa: str) -> dict | None:
    """La ficha de la versión más reciente subida desde Jarvis para la sociedad, o None."""
    async with await O._conectar() as conn:
        cur = await conn.execute("SELECT id, nombre, formato, sha256, bytes, por, creado FROM deuc_base WHERE empresa = %s ORDER BY creado DESC, id DESC LIMIT 1", [empresa])
        f = await cur.fetchone()
    return None if not f else {**f, "creado": f["creado"].isoformat()}


async def base_local(empresa: str) -> tuple[str, bytes, str] | None:
    """(nombre, contenido, formato) del DEUC base subido desde Jarvis, o None si no hay. Se comprueba que el fichero sigue siendo el que se guardó (mismo sha256)."""
    f = await actual_de(empresa)
    if not f:
        return None
    ruta = _carpeta(empresa) / f"{f['sha256']}.{f['formato']}"
    try:
        datos = ruta.read_bytes()
    except OSError:
        raise ErrorDeuc("El DEUC base de la sociedad ya no está en el servidor: vuelve a subirlo desde Jarvis") from None
    if hashlib.sha256(datos).hexdigest() != f["sha256"]:
        raise ErrorDeuc("El DEUC base de la sociedad ha cambiado en el disco: vuelve a subirlo desde Jarvis")
    return f["nombre"], datos, f["formato"]
