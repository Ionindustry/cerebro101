"""Servicio de conversión: recibe un .doc, .odt o .rtf y devuelve un .docx hecho con LibreOffice (api/cerebro/licitaciones/conversion_local.py).

Solo biblioteca estándar. POST /convertir?formato=odt con el documento en el cuerpo (máx. 60 MB) → 200 con el .docx, o 4xx/5xx con {"error": "..."}. GET /salud → 200.
Corre en un contenedor sin salida a internet, sin acceso a ningún otro servicio y de solo lectura. Atiende de una en una (LibreOffice gasta mucha memoria).
"""
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import conversion_local as L

LIMITE = 60 << 20
TURNO = threading.Semaphore(1)


class Manejador(BaseHTTPRequestHandler):
    server_version = "conversor"

    def _responder(self, codigo: int, cuerpo: bytes, tipo: str = "application/json") -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _error(self, codigo: int, mensaje: str) -> None:
        self._responder(codigo, json.dumps({"error": mensaje}, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):  # noqa: N802
        if urlparse(self.path).path == "/salud":
            self._responder(200 if L.disponible() else 503, b'{"ok": true}' if L.disponible() else b'{"ok": false}')
        else:
            self._error(404, "no existe")

    def do_POST(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path != "/convertir":
            return self._error(404, "no existe")
        formato = (parse_qs(u.query).get("formato") or [""])[0]
        if formato not in L.CONVERTIBLES:
            return self._error(422, f"El formato {formato[:10]} no se convierte a Word")
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if not 0 < n <= LIMITE:
            return self._error(413, "El documento está vacío o es demasiado grande")
        datos = self.rfile.read(n)
        with TURNO, tempfile.TemporaryDirectory(prefix="conv-") as tmp:
            entrada, salida = Path(tmp) / f"doc.{formato}", Path(tmp) / "doc.docx"
            entrada.write_bytes(datos)
            try:
                L.convertir(entrada, salida, formato)
            except L.ErrorConversion as e:
                return self._error(422, str(e))
            self._responder(200, salida.read_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    def log_message(self, formato, *args):      # sin el contenido de nada: solo qué se pide
        print("conversor:", formato % args, flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Manejador).serve_forever()
