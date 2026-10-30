"""LibreOffice en un proceso aparte: convierte .doc, .odt o .rtf en .docx. Módulo AUTÓNOMO (solo biblioteca estándar): lo usa el servicio `conversor` (servicios/conversor), que es
quien lleva LibreOffice dentro de su propio contenedor, y cualquier prueba o equipo de desarrollo que lo tenga instalado. La API no lo ejecuta en producción: llama al servicio.

El documento es de terceros y LibreOffice es un programa grande, así que se usa con cautela: entorno vacío (solo PATH, un HOME temporal y el idioma), perfil nuevo y desechable con el
nivel de seguridad de macros más alto (no se ejecuta ninguna) y sin actualizar vínculos, sin interfaz, con plazo de tiempo y límites de ficheros, sobre una COPIA en una carpeta temporal.
El resultado se valida (un zip de Word de verdad, de tamaño razonable) antes de devolverse y el original no se toca.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

CONVERTIBLES = ("doc", "odt", "rtf")
MAX_SALIDA = 60 << 20
PLAZO = 120

# Seguridad de macros al nivel 3 («muy alta»: solo macros firmadas de orígenes de confianza, y no hay ninguno) y sin actualizar vínculos al abrir.
PERFIL = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item>
</oor:items>
"""


CABECERAS = {"doc": b"\xd0\xcf\x11\xe0", "odt": b"PK", "rtf": b"{\\rtf"}      # el contenido ha de ser lo que dice el formato (si no, LibreOffice lo abriría como texto)


class ErrorConversion(Exception):
    """Lo que no se pudo convertir; el mensaje es para la persona."""


def disponible() -> bool:
    return shutil.which("soffice") is not None


def _limites() -> None:      # pragma: no cover — se ejecuta en el proceso hijo
    try:
        import resource
        for limite, valor in ((resource.RLIMIT_CPU, PLAZO), (resource.RLIMIT_FSIZE, MAX_SALIDA * 2), (resource.RLIMIT_CORE, 0)):
            resource.setrlimit(limite, (valor, valor))
    except (ImportError, ValueError, OSError):
        pass


def es_docx(ruta: Path) -> bool:
    try:
        with zipfile.ZipFile(ruta) as z:
            return "word/document.xml" in z.namelist() and sum(i.file_size for i in z.infolist()) < (300 << 20)
    except (zipfile.BadZipFile, OSError):
        return False


def convertir(origen: Path, destino: Path, formato: str) -> Path:
    """Convierte `origen` (formato: doc, odt o rtf) en el .docx `destino`."""
    if formato not in CONVERTIBLES:
        raise ErrorConversion(f"El formato {formato} no se convierte a Word")
    exe = shutil.which("soffice")
    if not exe:
        raise ErrorConversion("LibreOffice no está instalado")
    with open(origen, "rb") as f:
        if not f.read(8).startswith(CABECERAS[formato]):
            raise ErrorConversion(f"El contenido del documento no es {formato}")
    with tempfile.TemporaryDirectory(prefix="conversion-") as tmp:
        t = Path(tmp)
        entrada = t / f"entrada.{formato}"
        shutil.copyfile(origen, entrada)
        (t / "perfil" / "user").mkdir(parents=True)
        (t / "perfil" / "user" / "registrymodifications.xcu").write_text(PERFIL, encoding="utf-8")
        salida = t / "salida"
        salida.mkdir()
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(t), "LANG": "C.UTF-8"}
        try:
            subprocess.run([exe, "--headless", "--norestore", "--nolockcheck", "--nologo", "--nodefault", f"-env:UserInstallation={(t / 'perfil').as_uri()}",
                            "--convert-to", "docx:MS Word 2007 XML", "--outdir", str(salida), str(entrada)],
                           cwd=tmp, env=env, capture_output=True, timeout=PLAZO, check=False, preexec_fn=_limites)
        except subprocess.TimeoutExpired:
            raise ErrorConversion("El documento tarda demasiado en convertirse a Word") from None
        except OSError:
            raise ErrorConversion("No se ha podido ejecutar la conversión a Word") from None
        resultado = salida / "entrada.docx"
        if not resultado.is_file() or resultado.stat().st_size > MAX_SALIDA or not es_docx(resultado):
            raise ErrorConversion(f"No se ha podido convertir el documento ({formato}) a Word")
        destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(resultado, destino)
    os.chmod(destino, 0o600)
    return destino
