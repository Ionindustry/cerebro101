"""Aptitud de 101.cat frente a los requisitos de un pliego: una SUGERENCIA por requisito, calculada con el perfil de la empresa (config/licitaciones.yaml → perfil_licitador).

Es una orientación del sistema, no una valoración jurídica y NO es la matriz de cumplimiento: la matriz (cumple / parcial / no cumple) la anota siempre una persona
(pliegos.marcar_cumplimiento). Aquí solo se le ahorra el trabajo de partida: «con lo que sabemos de la empresa, este requisito probablemente no se cumple porque…, y estas son las vías».
Reglas deterministas y prudentes: ante la duda no se sugiere nada («revisar»). Pura: no toca base de datos ni red.
"""
from __future__ import annotations

import re
import unicodedata

AVISO = "Sugerencia automática a partir del perfil de la empresa: orientativa, no jurídica. La valoración la hace una persona y la validez final la confirma el asesor."
SUGERENCIAS = ("cumple", "parcial", "no_cumple", "revisar")

VIA_MEDIOS = "Integrar la solvencia de otra empresa que se comprometa por escrito a poner sus medios a disposición (art. 75 LCSP)."
VIA_UTE = "Presentarse en UTE con una empresa que sí tenga esa solvencia (art. 69 LCSP)."
VIA_NUEVA = ("Una empresa de nueva creación suele poder acreditar la solvencia técnica por otros medios (titulación y experiencia del equipo, medios personales y materiales) "
             "en vez de por trabajos ya ejecutados: comprueba que el pliego lo admite.")


def _n(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


def importe(texto: str) -> float | None:
    """El mayor importe en euros que aparece en un texto («300.000 €», «1.500.000,50 euros», «600000 €»), o None."""
    mejor = None
    for m in re.finditer(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?\s*(?:€|euros?\b|eur\b)", str(texto or ""), re.I):
        v = float(m.group(1).replace(".", "") + ("." + m.group(2) if m.group(2) else ""))
        mejor = v if mejor is None or v > mejor else mejor
    return mejor


def _res(sug: str, motivo: str, vias: list[str] | None = None) -> dict:
    return {"sugerencia": sug, "motivo": motivo, "vias": vias or []}


CERTIFICACIONES = (("iso 9001", r"iso\s*9001"), ("iso 14001", r"iso\s*14001"), ("iso 27001", r"iso\s*27001"), ("iso 45001", r"iso\s*45001"),
                   ("ens", r"\bens\b|esquema nacional de seguridad"))


def _certificaciones(texto: str, perfil: dict) -> dict | None:
    pedidas = [(n, p) for n, p in CERTIFICACIONES if re.search(p, texto)]
    if not pedidas:
        return None
    tiene = [_n(c) for c in (perfil.get("certificaciones") or []) if isinstance(c, str)]
    cumple, proceso, faltan = [], [], []
    for nombre, _ in pedidas:
        propias = [c for c in tiene if nombre in c]
        if not propias:
            faltan.append(nombre.upper())
        elif all(re.search(r"en proceso|en tramite|en curso|pendiente", c) for c in propias):
            proceso.append(nombre.upper())
        else:
            cumple.append(nombre.upper())
    if faltan:
        return _res("no_cumple", f"El pliego pide {', '.join(faltan)} y no consta en el perfil de la empresa.", [VIA_MEDIOS, VIA_UTE])
    if proceso:
        return _res("parcial", f"{', '.join(proceso)} está en proceso de certificación: aún no se puede aportar el certificado. Mira si el pliego admite otra prueba equivalente o la fecha en que se acreditará.")
    return _res("cumple", f"Consta en el perfil: {', '.join(cumple)}.")


def _seguro(texto: str, bruto: str, perfil: dict) -> dict | None:
    if not re.search(r"seguro (de )?(responsabilidad civil|indemnizacion|riesgos profesionales)|poliza de (responsabilidad|seguro)", texto):
        return None
    propio = str(perfil.get("seguro_rc") or "").strip()
    if not propio:
        return _res("revisar", "El pliego pide seguro de responsabilidad civil y en el perfil no consta ninguno.")
    pedido, tengo = importe(bruto), importe(propio)        # el importe se lee del texto original: al normalizar se pierde el «€»
    if pedido is None or tengo is None:
        return _res("revisar", f"El pliego pide seguro de responsabilidad civil; en el perfil consta «{propio}». Compara la cobertura exigida con la de la póliza.")
    if tengo >= pedido:
        return _res("cumple", f"El seguro de la empresa ({tengo:,.0f} €) cubre lo exigido ({pedido:,.0f} €).".replace(",", "."))
    return _res("parcial", f"El seguro de la empresa ({tengo:,.0f} €) es menor que el exigido ({pedido:,.0f} €): habría que ampliar la póliza.".replace(",", "."))


def sugerir(req: dict, perfil: dict | None) -> dict | None:
    """La sugerencia para UN requisito del pliego ({tipo, resumen, valor, cita}) o None si no hay nada que decir con los datos del perfil."""
    p = perfil if isinstance(perfil, dict) else {}
    if not p:
        return None
    bruto = " ".join(str(req.get(k) or "") for k in ("resumen", "valor", "cita"))
    texto = _n(bruto)
    tipo = str(req.get("tipo") or "")
    nueva = bool(p.get("nueva_creacion"))

    if re.search(r"rolece|roece|registro oficial de licitadores", texto):
        r = _n(p.get("rolece"))
        if r in ("si", "sí", "inscrita", "inscrito"):
            return _res("cumple", "El perfil dice que la empresa está inscrita en el ROLECE.")
        if "tramite" in r:
            return _res("parcial", "La inscripción en el ROLECE está en trámite: mira si el pliego admite acreditarla con la solicitud o hay que tenerla ya en la fecha de presentación.")
        if r == "no":
            return _res("no_cumple", "La empresa no está inscrita en el ROLECE.")
        return _res("revisar", "En el perfil no consta si la empresa está inscrita en el ROLECE.")

    if re.search(r"clasificacion (empresarial|del contratista|exigida|requerida)|grupo [a-z]\b.{0,30}subgrupo|\bsubgrupo\b", texto) and "no es exigible" not in texto and "no se exige" not in texto:
        if nueva:
            return _res("no_cumple", "Se pide clasificación empresarial: exige un historial de solvencia que una empresa de nueva creación no tiene.", [VIA_UTE, VIA_MEDIOS])
        return _res("revisar", "Se pide clasificación empresarial: comprueba el grupo y subgrupo con los de la empresa.")

    c = _certificaciones(texto, p)
    if c:
        return c

    s = _seguro(texto, bruto, p)
    if s:
        return s

    if nueva and (tipo == "solvencia_economica" or re.search(r"volumen (anual )?de negocios|cifra (anual )?de negocios|cuentas anuales|facturacion", texto)):
        return _res("no_cumple", "Se exige solvencia económica por volumen de negocios o cuentas: la empresa es de nueva creación y no tiene histórico que acreditar.", [VIA_MEDIOS, VIA_UTE])

    if nueva and (tipo == "solvencia_tecnica" or re.search(r"trabajos (similares|realizados|ejecutados)|servicios (similares|realizados|ejecutados)|relacion de (los principales )?(trabajos|servicios|suministros)|experiencia (previa|minima|acreditada)", texto)):
        exp = str(p.get("experiencia") or "").strip()
        motivo = "Se exige solvencia técnica por trabajos o experiencia previa de la empresa, y la empresa es de nueva creación."
        if exp:
            motivo += f" Consta en el perfil: «{exp}» (experiencia del equipo, no de la empresa)."
        return _res("no_cumple" if re.search(r"trabajos|servicios|suministros", texto) else "parcial", motivo, [VIA_NUEVA, VIA_MEDIOS, VIA_UTE])

    return None


def con_sugerencias(requisitos: list[dict], perfil: dict | None = None) -> list[dict]:
    """Los mismos requisitos con la clave `sugerencia` ({sugerencia, motivo, vias} o None). No modifica los de entrada."""
    if perfil is None:
        from . import resumen as resumen_mod
        perfil = resumen_mod.config().get("perfil_licitador")
    return [{**r, "sugerencia": sugerir(r, perfil)} for r in requisitos]


def resumen(requisitos_con_sugerencia: list[dict]) -> dict:
    """Cuántos requisitos tienen cada sugerencia, y si hay alguno que bloquea (no cumple) para decidir de un vistazo si compensa seguir."""
    cuenta = {s: 0 for s in SUGERENCIAS}
    for r in requisitos_con_sugerencia:
        s = (r.get("sugerencia") or {}).get("sugerencia")
        if s in cuenta:
            cuenta[s] += 1
    return {**cuenta, "bloqueos": cuenta["no_cumple"], "aviso": AVISO}
