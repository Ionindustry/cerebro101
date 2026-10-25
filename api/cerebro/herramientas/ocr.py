"""OCR de imágenes y PDF escaneados con Tesseract y Poppler (programas del sistema, instalados en la imagen del Cerebro).

Entrada no fiable: se ejecutan SIN shell, con límite de tiempo, de memoria y de tamaño de imagen, en una carpeta temporal que se borra.
El texto sale del OCR y puede tener errores (sobre todo en cifras): quien lo use para datos económicos debe comprobarlos.
"""
from __future__ import annotations

import os
import resource
import shutil
import subprocess
import tempfile
from pathlib import Path

IDIOMAS = "spa+cat+eng"
PIXELES_MAX = 60_000_000          # ~ 7700 x 7700: más es una imagen sospechosa o un error
PAGINAS_OCR_MAX = 12
DPI = 300
TIEMPO_MAX = 150                  # segundos por llamada
MEMORIA_MAX = 3 * 1024 ** 3


class OcrNoDisponible(RuntimeError):
    pass


class OcrFallido(ValueError):
    pass


def disponible() -> bool:
    return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))


def _limites():
    resource.setrlimit(resource.RLIMIT_AS, (MEMORIA_MAX, MEMORIA_MAX))
    resource.setrlimit(resource.RLIMIT_CPU, (TIEMPO_MAX, TIEMPO_MAX + 10))


def _ejecutar(orden: list[str], **k) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(orden, capture_output=True, timeout=TIEMPO_MAX, preexec_fn=_limites, check=False, **k)
    except subprocess.TimeoutExpired as e:
        raise OcrFallido("El OCR ha tardado demasiado (documento muy grande o complejo)") from e
    except FileNotFoundError as e:
        raise OcrNoDisponible(f"Falta el programa {orden[0]} en el servidor") from e


def _comprobar_imagen(ruta: Path) -> None:
    try:
        from PIL import Image
        with Image.open(ruta) as im:
            ancho, alto = im.size
    except Exception as e:  # noqa: BLE001
        raise OcrFallido("El fichero no es una imagen válida") from e
    if ancho * alto > PIXELES_MAX:
        raise OcrFallido(f"La imagen es demasiado grande ({ancho}x{alto} píxeles)")


def _tesseract(ruta: Path, idiomas: str) -> str:
    r = _ejecutar(["tesseract", str(ruta), "stdout", "-l", idiomas, "--psm", "3"])
    if r.returncode != 0:
        raise OcrFallido("El OCR no ha podido leer la imagen: " + r.stderr.decode(errors="replace")[:200])
    return r.stdout.decode("utf-8", errors="replace").strip()


def ocr_imagen(datos: bytes, extension: str, idiomas: str = IDIOMAS) -> str:
    if not disponible():
        raise OcrNoDisponible("El OCR (tesseract) no está instalado en este servidor")
    with tempfile.TemporaryDirectory(prefix="ocr_") as d:
        ruta = Path(d) / f"entrada{extension if extension in ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.gif', '.bmp', '.webp') else '.png'}"
        ruta.write_bytes(datos)
        _comprobar_imagen(ruta)
        return _tesseract(ruta, idiomas)


def ocr_pdf(datos: bytes, idiomas: str = IDIOMAS, paginas_max: int = PAGINAS_OCR_MAX) -> tuple[str, int]:
    """(texto, páginas leídas). Convierte las primeras páginas a imagen y las lee."""
    if not disponible():
        raise OcrNoDisponible("El OCR (tesseract/poppler) no está instalado en este servidor")
    with tempfile.TemporaryDirectory(prefix="ocr_") as d:
        carpeta = Path(d)
        (carpeta / "entrada.pdf").write_bytes(datos)
        r = _ejecutar(["pdftoppm", "-r", str(DPI), "-f", "1", "-l", str(paginas_max), "-png", str(carpeta / "entrada.pdf"), str(carpeta / "pag")])
        if r.returncode != 0:
            raise OcrFallido("No se han podido convertir las páginas del PDF a imagen: " + r.stderr.decode(errors="replace")[:200])
        paginas = sorted(carpeta.glob("pag*.png"))
        if not paginas:
            raise OcrFallido("El PDF no tiene páginas legibles")
        partes = []
        for i, p in enumerate(paginas, 1):
            _comprobar_imagen(p)
            partes.append(f"[Página {i}]\n{_tesseract(p, idiomas)}")
        return "\n\n".join(partes), len(paginas)
