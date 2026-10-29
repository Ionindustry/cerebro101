"""Extractor de texto de documentos (pliegos): se ejecuta como un PROCESO APARTE, `python -m cerebro.licitaciones.extractor <fichero> <formato>`, y escribe en la salida
estándar un JSON con las páginas. Es la única parte del Cerebro que abre un documento de terceros (SEC-142, SEC-144), por eso:

  - corre con límites del sistema operativo puestos por él mismo antes de abrir nada: memoria (1 GB), CPU (110 s), tamaño de lo que puede escribir (las imágenes de página del OCR) y ficheros abiertos;
  - quien lo lanza (pliegos.py) le da un entorno VACÍO (sin claves, sin la dirección de la base de datos), un directorio de trabajo temporal y un plazo;
  - nunca ejecuta nada del documento: solo lee texto (PDF con pypdf; Word, OpenDocument y Excel como XML/hojas; macros y objetos incrustados se ignoran);
  - las páginas de un PDF sin texto seleccionable (escaneos) se leen con OCR: Poppler las convierte a imagen y Tesseract las lee, sin shell, con el mismo entorno vacío y
    los mismos límites (heredados por los programas hijos), con tope de páginas y de tiempo; lo que no da tiempo a leer se avisa;
  - la salida es solo texto, con tope de páginas y de tamaño.

Una «página» es una página del PDF; en los demás formatos, donde no hay páginas, se corta el texto en bloques de unos 3000 caracteres (o una hoja, en Excel) y se numeran:
la cita dice «bloque 3» en vez de «página 3». Es la defensa en profundidad hasta que haya un contenedor sin red (docs/SEGURIDAD.md §3.10): sin importar los demás módulos del Cerebro.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree

PAGINAS_MAX = 500                    # SEC-142
CARACTERES_PAGINA = 60_000           # lo que se guarda como máximo de una página
CARACTERES_TOTAL = 3_000_000
BLOQUE = 3000
FILAS_MAX = 5000
DESCOMPRIMIDO_MAX = 200 * 1024 * 1024
SIN_TEXTO = 20                       # una página con menos caracteres que estos se trata como imagen
OCR_PAGINAS_MAX = 120                # páginas que se intentan leer con OCR en una pasada
OCR_IDIOMAS = "spa+cat+eng"
OCR_LADO_PX = 2400                   # lado largo de la imagen: ~290 ppp en un A4; fija el tamaño aunque la página sea de un plano enorme
OCR_HILOS = 3
OCR_PLAZO_S = 95                     # desde que arranca el extractor: pasado esto no se empiezan más páginas (el lanzador lo corta a los 130 s)
OCR_PLAZO_DURO_S = 120
_inicio: float | None = None        # lo pone main() al arrancar el proceso; sin él (pruebas), el plazo cuenta desde que empieza el OCR


class NoSePuedeLeer(Exception):
    """El mensaje es para la persona: dice qué le pasa al documento."""


def poner_limites() -> None:
    """Límites del sistema operativo para este proceso. Si el sistema no los admite (Windows), el plazo y el entorno vacío de quien lo lanza siguen protegiendo."""
    try:
        import resource
    except ImportError:      # pragma: no cover
        return
    for limite, valor in ((resource.RLIMIT_AS, 1 << 30), (resource.RLIMIT_CPU, 110), (resource.RLIMIT_FSIZE, 32 << 20), (resource.RLIMIT_NOFILE, 64), (resource.RLIMIT_CORE, 0)):
        try:
            resource.setrlimit(limite, (valor, valor))
        except (ValueError, OSError):
            pass


def _limpiar(t: str) -> str:
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", t or "")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def _en_bloques(texto: str) -> list[str]:
    """Corta un texto largo en bloques de ~BLOQUE caracteres por saltos de línea (sin partir un párrafo salvo que él solo pase del bloque)."""
    bloques, actual = [], ""
    for linea in texto.split("\n"):
        while len(linea) > BLOQUE:
            if actual:
                bloques.append(actual)
                actual = ""
            bloques.append(linea[:BLOQUE])
            linea = linea[BLOQUE:]
        if len(actual) + len(linea) + 1 > BLOQUE and actual:
            bloques.append(actual)
            actual = ""
        actual = f"{actual}\n{linea}" if actual else linea
    if actual.strip():
        bloques.append(actual)
    return [b.strip() for b in bloques if b.strip()]


def _zip(datos: bytes) -> zipfile.ZipFile:
    try:
        z = zipfile.ZipFile(io.BytesIO(datos))
    except zipfile.BadZipFile as e:
        raise NoSePuedeLeer("El documento está dañado o no es lo que dice ser") from e
    if sum(i.file_size for i in z.infolist()) > DESCOMPRIMIDO_MAX:
        raise NoSePuedeLeer("El documento ocupa demasiado al descomprimirse: no se abre por seguridad")
    return z


def _ocr_disponible() -> bool:
    return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))


def _entorno_ocr() -> dict:
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "OMP_THREAD_LIMIT": "1"}


def _ocr_pagina(ruta: str, n: int, carpeta: str, empezar_antes: float, terminar_antes: float) -> str | None:
    """El texto de la página n (desde 1) leído con OCR, '' si no hay nada o None si ya no hay tiempo. Sin shell, entorno mínimo, plazo por llamada.
    Los dos límites son instantes de time.monotonic(): no se empieza una página pasado el primero y ninguna llamada pasa del segundo."""
    if time.monotonic() > empezar_antes:
        return None
    base = os.path.join(carpeta, f"p{n}")
    try:
        r = subprocess.run(["pdftoppm", "-f", str(n), "-l", str(n), "-scale-to", str(OCR_LADO_PX), "-gray", "-png", "-singlefile", ruta, base],
                           capture_output=True, timeout=max(1, min(40, terminar_antes - time.monotonic())), check=False, env=_entorno_ocr(), cwd=carpeta,
                           stdin=subprocess.DEVNULL)
        if r.returncode != 0 or not os.path.exists(base + ".png"):
            return ""
        t = subprocess.run(["tesseract", base + ".png", "stdout", "-l", OCR_IDIOMAS, "--psm", "3"],
                           capture_output=True, timeout=max(1, min(40, terminar_antes - time.monotonic())), check=False, env=_entorno_ocr(), cwd=carpeta,
                           stdin=subprocess.DEVNULL)
        return _limpiar(t.stdout.decode("utf-8", "replace")) if t.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        return None
    finally:
        try:
            os.remove(base + ".png")
        except OSError:
            pass


def _rangos(numeros: list[int]) -> str:
    partes, i = [], 0
    while i < len(numeros):
        j = i
        while j + 1 < len(numeros) and numeros[j + 1] == numeros[j] + 1:
            j += 1
        partes.append(str(numeros[i]) if i == j else f"{numeros[i]}-{numeros[j]}")
        i = j + 1
    return ", ".join(partes)


def _con_ocr(ruta: str, paginas: list[str], avisos: list[str]) -> None:
    """Rellena con OCR las páginas sin texto (cambia `paginas` y `avisos`). Lo que se lee por OCR puede tener errores, sobre todo en cifras: se dice qué páginas son."""
    vacias = [i + 1 for i, t in enumerate(paginas) if len(t) < SIN_TEXTO]
    if not vacias:
        return
    if not ruta or not _ocr_disponible():
        avisos.append(f"Las páginas {_rangos(vacias[:40])} no tienen texto seleccionable (parecen un escaneo) y este servidor no tiene OCR: hace falta que las revise una persona")
        return
    pendientes = vacias[:OCR_PAGINAS_MAX]
    inicio = _inicio if _inicio is not None else time.monotonic()
    empezar_antes, terminar_antes = inicio + OCR_PLAZO_S, inicio + OCR_PLAZO_DURO_S
    with tempfile.TemporaryDirectory(prefix="ocr-", dir=os.getcwd()) as carpeta:
        def una(n: int):
            return n, _ocr_pagina(ruta, n, carpeta, empezar_antes, terminar_antes)
        with ThreadPoolExecutor(max_workers=OCR_HILOS) as pool:
            resultados = list(pool.map(una, pendientes))
    leidas = [n for n, t in resultados if t]
    for n, t in resultados:
        if t:
            paginas[n - 1] = t
    sin_leer = [n for n, t in resultados if t is None] + vacias[OCR_PAGINAS_MAX:]
    if leidas:
        avisos.append(f"Leídas con OCR las páginas {_rangos(sorted(leidas))}: pueden tener errores (sobre todo en cifras); comprueba las citas en el original")
    if sin_leer:
        avisos.append(f"Sin leer por falta de tiempo o de tope ({len(sin_leer)} páginas sin texto, desde la {min(sin_leer)}): hace falta que las revise una persona")
    vacias_final = [n for n in vacias if len(paginas[n - 1]) < SIN_TEXTO and n not in sin_leer]
    if vacias_final and not leidas and not sin_leer:
        avisos.append("El PDF casi no tiene texto, ni siquiera con OCR (parece un escaneo en blanco o ilegible): hace falta que lo revise una persona")


def _pdf(datos: bytes, ruta: str | None = None) -> tuple[list[str], str, list[str]]:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError
    avisos = []
    try:
        lector = PdfReader(io.BytesIO(datos))
        if lector.is_encrypted and not lector.decrypt(""):
            raise NoSePuedeLeer("El PDF está protegido con contraseña: no se puede leer sin ella")
        total = len(lector.pages)
        paginas = [_limpiar(p.extract_text() or "") for p in lector.pages[:PAGINAS_MAX]]
    except NoSePuedeLeer:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, OSError, RecursionError, AttributeError) as e:
        raise NoSePuedeLeer(f"No se ha podido leer el PDF ({type(e).__name__})") from e
    if total > PAGINAS_MAX:
        avisos.append(f"Solo se han leído las {PAGINAS_MAX} primeras páginas de {total}")
    _con_ocr(ruta, paginas, avisos)
    return paginas, "página", avisos


def _texto_xml(raiz, etiquetas_parrafo: set[str], etiquetas_texto: set[str]) -> list[str]:
    parrafos = []
    for p in raiz.iter():
        if p.tag in etiquetas_parrafo:
            t = "".join((x.text or "") if x.tag in etiquetas_texto else " " for x in p.iter() if x.tag in etiquetas_texto or x.tag.endswith(("}tab", "}br", "}s")))
            if t.strip():
                parrafos.append(t.strip())
    return parrafos


def _docx(datos: bytes) -> tuple[list[str], str, list[str]]:
    z = _zip(datos)
    if "word/document.xml" not in z.namelist():
        raise NoSePuedeLeer("El fichero no es un documento Word válido")
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        raiz = ElementTree.fromstring(z.read("word/document.xml"))
    except ElementTree.ParseError as e:
        raise NoSePuedeLeer("El documento Word está dañado") from e
    texto = "\n".join(_texto_xml(raiz, {ns + "p"}, {ns + "t"}))
    return _en_bloques(_limpiar(texto)), "bloque", (["Se ignoran las macros y los objetos incrustados"] if "word/vbaProject.bin" in z.namelist() else [])


def _odf(datos: bytes) -> tuple[list[str], str, list[str]]:
    z = _zip(datos)
    if "content.xml" not in z.namelist():
        raise NoSePuedeLeer("El fichero no es un documento OpenDocument válido")
    ns = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
    try:
        raiz = ElementTree.fromstring(z.read("content.xml"))
    except ElementTree.ParseError as e:
        raise NoSePuedeLeer("El documento OpenDocument está dañado") from e
    parrafos = []
    for p in raiz.iter():
        if p.tag in (ns + "p", ns + "h"):
            t = "".join(p.itertext()).strip()
            if t:
                parrafos.append(t)
    return _en_bloques(_limpiar("\n".join(parrafos))), "bloque", []


def _xlsx(datos: bytes) -> tuple[list[str], str, list[str]]:
    _zip(datos)
    from openpyxl import load_workbook
    try:
        libro = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 — openpyxl lanza varios tipos según el daño
        raise NoSePuedeLeer(f"No se ha podido leer el Excel ({type(e).__name__})") from e
    hojas, filas = [], 0
    for hoja in libro.worksheets:
        partes = [f"[Hoja «{hoja.title}»]"]
        for fila in hoja.iter_rows(values_only=True):
            if filas >= FILAS_MAX:
                partes.append(f"… (se leen como máximo {FILAS_MAX} filas)")
                break
            if any(c is not None and str(c).strip() for c in fila):
                partes.append(" | ".join("" if c is None else str(c) for c in fila).rstrip(" |"))
                filas += 1
        hojas.append("\n".join(partes))
    libro.close()
    return [_limpiar(h) for h in hojas], "hoja", []


LECTORES = {"pdf": _pdf, "docx": _docx, "odt": _odf, "ods": _odf, "xlsx": _xlsx}


def extraer(datos: bytes, formato: str, ruta: str | None = None) -> dict:
    """`ruta` es el fichero del que salen `datos`: solo el PDF la usa (Poppler necesita el fichero para el OCR); sin ella no hay OCR."""
    lector = LECTORES.get(formato)
    if lector is None:
        raise NoSePuedeLeer(f"Los documentos «{formato}» no se leen")
    paginas, unidad, avisos = lector(datos, ruta) if formato == "pdf" else lector(datos)
    salida, total = [], 0
    for i, t in enumerate(paginas, start=1):
        t = t[:CARACTERES_PAGINA]
        total += len(t)
        if total > CARACTERES_TOTAL:
            avisos.append("El documento tiene tanto texto que solo se guarda el principio")
            break
        salida.append({"n": i, "texto": t})
    return {"unidad": unidad, "paginas": salida, "avisos": avisos}


def main(argv: list[str]) -> int:
    global _inicio
    _inicio = time.monotonic()
    poner_limites()
    if len(argv) != 3:
        print(json.dumps({"error": "uso: extractor <fichero> <formato>"}))
        return 2
    try:
        with open(argv[1], "rb") as f:
            datos = f.read(210 * 1024 * 1024)
        resultado = extraer(datos, argv[2], argv[1])
    except NoSePuedeLeer as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    except MemoryError:
        print(json.dumps({"error": "El documento necesita demasiada memoria para leerse"}))
        return 1
    except Exception as e:  # noqa: BLE001 — un documento hostil puede romper el lector de muchas maneras; nada de eso debe tumbar a quien lo lanzó
        print(json.dumps({"error": f"No se ha podido leer el documento ({type(e).__name__})"}))
        return 1
    print(json.dumps(resultado, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
