"""Voz: si Whisper falla por la tarjeta gráfica, pasa a CPU y sigue transcribiendo (sin cargar modelos reales)."""
import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


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


class TestHablar(unittest.TestCase):
    """Texto a voz (Piper simulado): WAV si está la voz, errores que se entienden si no."""

    def servidor(self, con_voz=True, config="{}"):
        import tempfile
        s, _ = cargar_servidor()
        carpeta = Path(tempfile.mkdtemp())
        voz = carpeta / "es_ES-prueba.onnx"
        if con_voz:
            voz.write_bytes(b"modelo")
            Path(str(voz) + ".json").write_text(config)
        s.VOCES["es"] = str(voz)
        return s

    def hablar(self, s, cuerpo, piper=None):
        from fastapi.testclient import TestClient
        with mock.patch.object(s.subprocess, "run", piper or self.piper_ok):
            with TestClient(s.app) as c:
                return c.post("/hablar", json=cuerpo)

    @staticmethod
    def piper_ok(args, input, **k):
        Path(args[args.index("--output_file") + 1]).write_bytes(b"RIFF....WAVE")
        piper_ok.llamadas.append((args, input))
        return types.SimpleNamespace(returncode=0)

    def test_devuelve_un_wav_y_pasa_el_texto_a_piper(self):
        piper_ok.llamadas.clear()
        r = self.hablar(self.servidor(), {"texto": "Hola Albert", "idioma": "es"})
        self.assertEqual((r.status_code, r.headers["content-type"], r.content), (200, "audio/wav", b"RIFF....WAVE"))
        self.assertEqual(piper_ok.llamadas[0][1], b"Hola Albert")

    def test_sin_la_voz_dice_como_descargarla(self):
        r = self.hablar(self.servidor(con_voz=False), {"texto": "Hola", "idioma": "es"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("scripts/voces_descargar.py", r.json()["error"])

    def test_sin_texto_o_con_texto_enorme(self):
        s = self.servidor()
        self.assertEqual(self.hablar(s, {"texto": "  ", "idioma": "es"}).status_code, 422)
        piper_ok.llamadas.clear()
        self.hablar(s, {"texto": "a" * 5000, "idioma": "es"})
        self.assertEqual(len(piper_ok.llamadas[0][1]), s.MAX_TEXTO_HABLADO)

    def test_si_piper_falla_el_error_se_explica(self):
        import subprocess

        def falla(args, input, **k):
            raise subprocess.CalledProcessError(1, args, stderr=b"boom")
        r = self.hablar(self.servidor(), {"texto": "Hola", "idioma": "es"}, falla)
        self.assertEqual(r.status_code, 500)
        self.assertIn("síntesis", r.json()["error"])

    def test_se_elige_el_locutor_por_nombre_o_por_numero(self):
        import os
        s = self.servidor(config='{"speaker_id_map": {"M": 0, "F": 1}}')
        for valor, esperado in (("F", "1"), ("M", "0"), ("1", "1")):
            piper_ok.llamadas.clear()
            with mock.patch.dict(os.environ, {"PIPER_LOCUTOR_ES": valor}):
                self.assertEqual(self.hablar(s, {"texto": "Hola", "idioma": "es"}).status_code, 200)
            args = piper_ok.llamadas[0][0]
            self.assertEqual(args[args.index("--speaker") + 1], esperado, valor)

    def test_sin_locutor_no_se_pide_ninguno(self):
        import os
        piper_ok.llamadas.clear()
        with mock.patch.dict(os.environ, {"PIPER_LOCUTOR_ES": ""}):
            self.hablar(self.servidor(config='{"speaker_id_map": {"M": 0, "F": 1}}'), {"texto": "Hola", "idioma": "es"})
        self.assertNotIn("--speaker", piper_ok.llamadas[0][0])

    def test_un_locutor_que_no_existe_dice_cuales_hay(self):
        import os
        with mock.patch.dict(os.environ, {"PIPER_LOCUTOR_ES": "X"}):
            r = self.hablar(self.servidor(config='{"speaker_id_map": {"M": 0, "F": 1}}'), {"texto": "Hola", "idioma": "es"})
        self.assertEqual(r.status_code, 500)
        self.assertIn("M, F", r.json()["error"])
        with mock.patch.dict(os.environ, {"PIPER_LOCUTOR_ES": "X"}):
            r = self.hablar(self.servidor(), {"texto": "Hola", "idioma": "es"})
        self.assertIn("ninguno", r.json()["error"])

    def test_la_voz_se_cambia_con_el_entorno(self):
        import os
        with mock.patch.dict(os.environ, {"PIPER_VOZ_ES": "/voces/otra.onnx", "PIPER_VOZ_CA": ""}):
            s, _ = cargar_servidor()
        self.assertEqual((s.VOCES["es"], s.VOCES["ca"]), ("/voces/otra.onnx", "/voces/ca_ES-upc_ona-medium.onnx"))

    def test_la_salud_dice_que_voces_hay(self):
        from fastapi.testclient import TestClient
        s = self.servidor(con_voz=False)
        with TestClient(s.app) as c:
            self.assertFalse(c.get("/salud").json()["voces"]["es"])


def piper_ok(args, input, **k):          # noqa: F811 - la versión con registro de llamadas
    Path(args[args.index("--output_file") + 1]).write_bytes(b"RIFF....WAVE")
    piper_ok.llamadas.append((args, input))
    return types.SimpleNamespace(returncode=0)


piper_ok.llamadas = []
TestHablar.piper_ok = staticmethod(piper_ok)


if __name__ == "__main__":
    unittest.main()
