"""Los datos de la empresa (o empresas) para rellenar la documentación administrativa de una oferta. SALEN DEL ERP —Company, Address y Contact—: así toda la información está en el
mismo sitio. Nada se inventa ni se guarda aparte: cada dato lleva su origen («ERP · Company 101 S.L. · tax_id») y lo que falta se dice con el sitio del ERP donde completarlo.

Lo lee el sistema, no los agentes (categoría «sistema» de config/erp_acceso.yaml), y solo una lista cerrada de campos."""
from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx
import yaml

from ..ajustes import ajustes

log = logging.getLogger("cerebro.licitaciones.empresa")

DEFECTO = {
    "departamento_erp": "licitaciones",
    "designaciones": ["administrador", "apoderado", "representante legal", "gerente", "director general", "consejero delegado"],
    "campos": {"empresa_registro": "registration_details", "representante_dni": "dni", "representante_poder": "poder"},
    "deuc_patron": "deuc|espd",
}
# Los datos que se pueden poner en un documento, y dónde se completa cada uno en el ERP si falta.
CLAVES = {
    "empresa.razon_social": "Empresa › Nombre de la empresa (company_name)",
    "empresa.nif": "Empresa › NIF/CIF (tax_id)",
    "empresa.domicilio": "Dirección enlazada a la empresa › Línea 1 (address_line1)",
    "empresa.cp": "Dirección enlazada a la empresa › Código postal (pincode)",
    "empresa.localidad": "Dirección enlazada a la empresa › Ciudad (city)",
    "empresa.provincia": "Dirección enlazada a la empresa › Provincia (state)",
    "empresa.pais": "Dirección enlazada a la empresa › País (country)",
    "empresa.telefono": "Empresa › Teléfono (phone_no) o la dirección",
    "empresa.email": "Empresa › Correo (email) o la dirección",
    "empresa.registro": "Empresa › Datos de inscripción (registration_details)",
    "representante.nombre": "Contacto enlazado a la empresa con cargo de administrador, apoderado, representante legal…",
    "representante.cargo": "Contacto del representante › Cargo (designation)",
    "representante.dni": "Contacto del representante › campo DNI/NIE",
    "representante.poder": "Contacto del representante › campo con los datos del poder",
}
_DESIGNACION_ESPACIOS = re.compile(r"\s+")


def _erp():
    """El módulo del ERP, importado al usarlo: `herramientas` importa la herramienta «plantillas», que importa este módulo, y un import al principio haría un ciclo si este se importa primero."""
    from ..herramientas import erpnext
    return erpnext


class ErrorEmpresa(ValueError):
    """No se pudo obtener la empresa (el ERP no responde, no hay permiso o hay que elegir una)."""


class VariasEmpresas(ErrorEmpresa):
    """Hay más de una empresa en el ERP y no se ha dicho con cuál se presenta la oferta."""

    def __init__(self, empresas: list[dict]):
        super().__init__("Hay varias empresas en el ERP: elige con cuál se presenta la oferta")
        self.empresas = empresas


def configuracion() -> dict:
    try:
        c = (yaml.safe_load((Path(ajustes.dir_config) / "licitaciones.yaml").read_text(encoding="utf-8")) or {}).get("empresa") or {}
    except OSError:
        c = {}
    return {"departamento_erp": str(c.get("departamento_erp") or DEFECTO["departamento_erp"]),
            "designaciones": [str(x).lower().strip() for x in (c.get("designaciones") or DEFECTO["designaciones"]) if x],
            "campos": {**DEFECTO["campos"], **{k: str(v) for k, v in (c.get("campos") or {}).items() if v}},
            "deuc_patron": str(c.get("deuc_patron") or DEFECTO["deuc_patron"])}


def _t(v, n: int = 300) -> str:
    return _DESIGNACION_ESPACIOS.sub(" ", str(v or "")).strip()[:n]


async def _pedir(doctype: str, filtros: list, base: list[str], opcionales: list[str], dep: str) -> tuple[list[dict], set[str]]:
    """Lee con una lista cerrada de campos. Los campos opcionales (los personalizados) pueden no existir en el ERP: si da error con ellos, se repite sin ellos."""
    try:
        return await _erp().listar_sistema(doctype, dep, filtros, base + opcionales), set(opcionales)
    except httpx.HTTPStatusError as e:
        if not opcionales or e.response.status_code not in (400, 417, 500):
            raise
    return await _erp().listar_sistema(doctype, dep, filtros, base), set()


async def _leer_erp(llamada):
    try:
        return await llamada
    except PermissionError as e:
        raise ErrorEmpresa(str(e)) from None
    except (httpx.HTTPError, OSError) as e:
        log.warning("empresa: no se ha podido leer el ERP: %s: %s", type(e).__name__, e)
        raise ErrorEmpresa("No se ha podido leer el ERP: inténtalo de nuevo en unos minutos") from None


async def empresas() -> list[dict]:
    """Las empresas del ERP: [{nombre, razon_social, nif}]. Para elegir con cuál se presenta una oferta."""
    dep = configuracion()["departamento_erp"]
    filas = await _leer_erp(_erp().listar_sistema("Company", dep, None, ["name", "company_name", "tax_id"], 50))
    return [{"nombre": f["name"], "razon_social": _t(f.get("company_name") or f["name"]), "nif": _t(f.get("tax_id"), 40)} for f in filas]


async def elegir(empresa: str | None = None) -> str:
    """El nombre (en el ERP) de la empresa que presenta la oferta: la indicada, o la única que haya."""
    lista = await empresas()
    if not lista:
        raise ErrorEmpresa("En el ERP no hay ninguna empresa (Company)")
    if empresa:
        if empresa not in {e["nombre"] for e in lista}:
            raise ErrorEmpresa(f"La empresa «{_t(empresa, 80)}» no existe en el ERP")
        return empresa
    if len(lista) == 1:
        return lista[0]["nombre"]
    raise VariasEmpresas(lista)


MAX_DEUC = 20 << 20


async def deuc_base(empresa: str) -> tuple[str, bytes] | None:
    """El DEUC base de la empresa: el Word cuyo nombre lleva «DEUC» (o «ESPD») adjunto a la Company en el ERP, con los datos de la empresa ya rellenados. Si hay varios, el más reciente.
    None si no hay ninguno. Se lee con la clave del departamento (categoría «sistema»: Company y File); un fichero que no es un Word de verdad no se admite."""
    cfg = configuracion()
    dep = cfg["departamento_erp"]
    filas = await _leer_erp(_erp().listar_sistema("File", dep, [["attached_to_doctype", "=", "Company"], ["attached_to_name", "=", empresa]],
                                                  ["name", "file_name", "file_url", "modified"], 50))
    patron = re.compile(cfg["deuc_patron"], re.I)
    validos = [f for f in filas if f.get("file_url") and str(f.get("file_name") or "").lower().endswith(".docx") and patron.search(str(f.get("file_name") or ""))]
    if not validos:
        return None
    elegido = max(validos, key=lambda f: str(f.get("modified") or ""))
    datos = await _leer_erp(_erp().descargar_sistema(elegido["file_url"], dep, MAX_DEUC))
    if datos[:2] != b"PK":
        raise ErrorEmpresa(f"El fichero «{_t(elegido['file_name'], 80)}» adjunto a la empresa no es un Word (.docx) válido")
    return _t(elegido["file_name"], 120), datos


def _origen(doctype: str, nombre: str, campo: str) -> str:
    return f"ERP · {doctype} {nombre} · {campo}"


def _elegir_direccion(filas: list[dict]) -> dict | None:
    for marca in ("is_your_company_address", "is_primary_address"):
        for f in filas:
            if f.get(marca):
                return f
    return filas[0] if filas else None


def _elegir_representante(filas: list[dict], designaciones: list[str]) -> dict | None:
    for d in designaciones:
        for f in filas:
            if d in _t(f.get("designation")).lower():
                return f
    return None


async def datos(empresa: str | None = None) -> dict:
    """Los datos de la empresa elegida: {"empresa": nombre, "valores": {clave: {"valor", "origen"}}, "faltan": {clave: dónde completarlo en el ERP}}."""
    cfg = configuracion()
    dep, campos = cfg["departamento_erp"], cfg["campos"]
    nombre = await elegir(empresa)
    enlace = [["Dynamic Link", "link_doctype", "=", "Company"], ["Dynamic Link", "link_name", "=", nombre]]
    val: dict[str, dict] = {}

    def poner(clave: str, valor, origen: str):
        v = _t(valor)
        if v:
            val[clave] = {"valor": v, "origen": origen}

    cias, ok_c = await _leer_erp(_pedir("Company", [["name", "=", nombre]], ["name", "company_name", "tax_id", "phone_no", "email", "country"], [campos["empresa_registro"]], dep))
    if cias:
        c = cias[0]
        poner("empresa.razon_social", c.get("company_name") or c["name"], _origen("Company", nombre, "company_name"))
        poner("empresa.nif", c.get("tax_id"), _origen("Company", nombre, "tax_id"))
        poner("empresa.telefono", c.get("phone_no"), _origen("Company", nombre, "phone_no"))
        poner("empresa.email", c.get("email"), _origen("Company", nombre, "email"))
        poner("empresa.pais", c.get("country"), _origen("Company", nombre, "country"))
        if campos["empresa_registro"] in ok_c:
            poner("empresa.registro", c.get(campos["empresa_registro"]), _origen("Company", nombre, campos["empresa_registro"]))

    dirs, _ = await _leer_erp(_pedir("Address", enlace + [["disabled", "=", 0]], ["name", "address_line1", "address_line2", "city", "state", "pincode", "country", "phone", "email_id",
                                                                                   "is_primary_address", "is_your_company_address"], [], dep))
    d = _elegir_direccion(dirs)
    if d:
        linea = ", ".join(x for x in (_t(d.get("address_line1")), _t(d.get("address_line2"))) if x)
        poner("empresa.domicilio", linea, _origen("Address", d["name"], "address_line1"))
        poner("empresa.cp", d.get("pincode"), _origen("Address", d["name"], "pincode"))
        poner("empresa.localidad", d.get("city"), _origen("Address", d["name"], "city"))
        poner("empresa.provincia", d.get("state"), _origen("Address", d["name"], "state"))
        if "empresa.pais" not in val:
            poner("empresa.pais", d.get("country"), _origen("Address", d["name"], "country"))
        if "empresa.telefono" not in val:
            poner("empresa.telefono", d.get("phone"), _origen("Address", d["name"], "phone"))
        if "empresa.email" not in val:
            poner("empresa.email", d.get("email_id"), _origen("Address", d["name"], "email_id"))

    contactos, ok_k = await _leer_erp(_pedir("Contact", enlace, ["name", "first_name", "last_name", "designation"], [campos["representante_dni"], campos["representante_poder"]], dep))
    r = _elegir_representante(contactos, cfg["designaciones"])
    if r:
        poner("representante.nombre", " ".join(x for x in (_t(r.get("first_name")), _t(r.get("last_name"))) if x), _origen("Contact", r["name"], "first_name"))
        poner("representante.cargo", r.get("designation"), _origen("Contact", r["name"], "designation"))
        if campos["representante_dni"] in ok_k:
            poner("representante.dni", r.get(campos["representante_dni"]), _origen("Contact", r["name"], campos["representante_dni"]))
        if campos["representante_poder"] in ok_k:
            poner("representante.poder", r.get(campos["representante_poder"]), _origen("Contact", r["name"], campos["representante_poder"]))
    return {"empresa": nombre, "valores": val, "faltan": {k: dnd for k, dnd in CLAVES.items() if k not in val}}
