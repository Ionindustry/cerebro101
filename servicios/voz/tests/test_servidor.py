"""Voz: si Whisper falla por la tarjeta gráfica, pasa a CPU y sigue transcribiendo (sin cargar modelos reales)."""
import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path


class Segmento:
    def __init__(self, texto): self.text = texto


class Info:
    language = "es"


def cargar_servidor():
    """Importa servidor.py con un `faster_whisper` falso: un modelo en cuda que falla como en el PC de Albert y uno en cpu que funciona."""
    cargas = []

    class FalsoWhisper:
        def __init__(self, nombre, device, compute_type):
            self.nombre, self.device = nombre, device
            cargas.append((nombre, device, compute_type))

        def transcribe(self, ruta, vad_filter=True):
            if self.device == "cuda":
                raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")
            return iter([Segmento(" hola "), Segmento("Jarvis ")]), Info()

    falso = types.ModuleType("faster_whisper")
    falso.WhisperModel = FalsoWhisper
    sys.modules["faster_whisper"] = falso
    espec = importlib.util.spec_from_file_location("voz_servidor", Path(__file__).resolve().parents[1] / "servidor.py")
    modulo = importlib.util.module_from_spec(espec)
    espec.loader.exec_module(modulo)
    return modulo, cargas


class TestVoz(unittest.TestCase):
    def test_si_la_tarjeta_falla_pasa_a_cpu_y_transcribe(self):
        s, cargas = cargar_servidor()
        texto, idioma = s._transcribir_fichero("/tmp/x.webm")
        self.assertEqual((texto, idioma), ("hola Jarvis", "es"))
        self.assertEqual(cargas, [("large-v3-turbo", "cuda", "float16"), ("small", "cpu", "int8")])
        self.assertEqual(s._estado["dispositivo"], "cpu")
        self.assertIn("libcublas", s._estado["alternativa"])

    def test_tras_cambiar_a_cpu_no_vuelve_a_cargar_nada(self):
        s, cargas = cargar_servidor()
        s._transcribir_fichero("/tmp/x.webm")
        s._transcribir_fichero("/tmp/x.webm")
        self.assertEqual(len(cargas), 2)

    def test_un_error_que_no_es_de_la_tarjeta_se_propaga(self):
        s, _ = cargar_servidor()
        s._estado.update(dispositivo="cpu", whisper=types.SimpleNamespace(transcribe=lambda *a, **k: (_ for _ in ()).throw(ValueError("audio roto"))))
        with self.assertRaises(ValueError):
            s._transcribir_fichero("/tmp/x.webm")

    def test_el_modelo_y_el_dispositivo_se_fijan_con_el_entorno(self):
        import os
        os.environ.update(WHISPER_DISPOSITIVO="cpu", WHISPER_MODELO="tiny")
        try:
            s, cargas = cargar_servidor()
            texto, _ = s._transcribir_fichero("/tmp/x.webm")
        finally:
            del os.environ["WHISPER_DISPOSITIVO"], os.environ["WHISPER_MODELO"]
        self.assertEqual((texto, cargas), ("hola Jarvis", [("tiny", "cpu", "int8")]))

    def test_la_api_transcribe_y_cuenta_su_estado(self):
        from fastapi.testclient import TestClient
        s, _ = cargar_servidor()
        with TestClient(s.app) as c:
            r = c.post("/transcribir", files={"audio": ("voz.webm", io.BytesIO(b"datos"), "audio/webm")})
            self.assertEqual((r.status_code, r.json()), (200, {"texto": "hola Jarvis", "idioma": "es"}))
            e = c.get("/salud").json()
        self.assertEqual((e["dispositivo"], e["modelo"], e["cargado"]), ("cpu", "small", True))


if __name__ == "__main__":
    unittest.main()
