"""Buzones de correo: control de acceso por departamento, protecciones y camino completo contra un servidor IMAP/SMTP real.

Las pruebas con servidor necesitan GreenMail (docker run -p 3025:3025 -p 3143:3143 -e GREENMAIL_OPTS="-Dgreenmail.setup.test.smtp
-Dgreenmail.setup.test.imap -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.auth.disabled" greenmail/standalone:2.1.3) y
CEREBRO_PRUEBA_CORREO=localhost; si no, se omiten.
"""
import asyncio
import os
import smtplib
import tempfile
import unittest
from email.message import EmailMessage

import _sin_servicios  # noqa: F401
import yaml

from cerebro.herramientas import buzones as B
from cerebro.herramientas import correo

HOST = os.environ.get("CEREBRO_PRUEBA_CORREO")

CONFIG = {
    "servidor": {"imap": {"host": HOST or "localhost", "puerto": 3143, "seguridad": "ninguna"},
                 "smtp": {"host": HOST or "localhost", "puerto": 3025, "seguridad": "ninguna"}},
    "carpetas": {"entrada": "INBOX", "borradores": "Drafts", "enviados": "Sent"},
    "limites": {"destinatarios_max": 2, "texto_max": 500, "mensajes_max": 5},
    "pie_comercial": "Responde BAJA para no recibir más mensajes.",
    "buzones": {
        "administracion": {"direccion": "administracion@101.cat", "departamentos": ["finanzas", "direccion"], "firma": "Administración"},
        "rrhh": {"direccion": "rrhh@101.cat", "departamentos": ["personas"]},
        "comercial": {"direccion": "comercial@101.cat", "departamentos": ["comercial"]},
        "compras": {"direccion": "compras@101.cat", "departamentos": ["comercial", "operaciones"]},
    },
}


def ejecutar(c):
    return asyncio.run(c)


class Base(unittest.TestCase):
    def setUp(self):
        self.f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
        yaml.safe_dump(CONFIG, self.f)
        self.f.close()
        self.antes = dict(os.environ)
        B.RUTA_CONFIG, B.RUTA_SECRETOS = self.f.name, "/no/existe"
        for b in CONFIG["buzones"]:
            os.environ[f"CORREO_{b.upper()}_CLAVE"] = "x"
        B.limpiar_cache()

    def tearDown(self):
        os.unlink(self.f.name)
        os.environ.clear()
        os.environ.update(self.antes)
        B.RUTA_CONFIG, B.RUTA_SECRETOS = None, "/run/secretos/buzones.env"
        B.limpiar_cache()


class TestAcceso(Base):
    def test_cada_departamento_solo_ve_los_suyos(self):
        self.assertEqual(B.buzones_de("personas"), ["rrhh"])
        self.assertEqual(B.buzones_de("finanzas"), ["administracion"])
        self.assertEqual(B.buzones_de("atencion"), [])

    def test_buzon_ajeno_denegado(self):
        with self.assertRaises(PermissionError) as e:
            B.resolver("personas", "administracion")
        self.assertIn("rrhh", str(e.exception))

    def test_departamento_sin_buzon(self):
        with self.assertRaises(PermissionError):
            B.resolver("atencion", None)

    def test_un_unico_buzon_se_elige_solo_y_varios_exigen_indicarlo(self):
        self.assertEqual(B.resolver("personas", None)[0], "rrhh")
        with self.assertRaises(PermissionError) as e:
            B.resolver("comercial", None)
        self.assertIn("comercial, compras", str(e.exception))

    def test_sin_clave_el_buzon_no_esta_dado_de_alta(self):
        del os.environ["CORREO_RRHH_CLAVE"]
        with self.assertRaises(PermissionError) as e:
            B.credenciales("rrhh")
        self.assertIn("buzon_alta", str(e.exception))

    def test_el_usuario_por_defecto_es_la_direccion(self):
        self.assertEqual(B.credenciales("rrhh")[0], "rrhh@101.cat")
        os.environ["CORREO_RRHH_USUARIO"] = "rrhh"
        self.assertEqual(B.credenciales("rrhh")[0], "rrhh")

    def test_leer_con_buzon_ajeno_no_conecta(self):
        with self.assertRaises(PermissionError):
            ejecutar(correo.leer_bandeja("personas", buzon="administracion"))

    def test_listar_no_muestra_buzones_ajenos(self):
        self.assertEqual([b["buzon"] for b in ejecutar(correo.listar_buzones("finanzas"))], ["administracion"])

    def test_seguridad_invalida(self):
        CONFIG_MAL = dict(CONFIG)
        B._cargar.cache_clear()
        with open(self.f.name, "w", encoding="utf-8") as fh:
            yaml.safe_dump({**CONFIG_MAL, "servidor": {"imap": {"host": "h", "puerto": 1, "seguridad": "tls1"}}}, fh)
        with self.assertRaises(ValueError):
            B.servidor("rrhh", "imap")


class TestProtecciones(Base):
    def test_no_se_escribe_a_buzones_propios(self):
        with self.assertRaises(ValueError) as e:
            correo._destinatarios(["cliente@ejemplo.es", "Rrhh@101.cat"])
        self.assertIn("propia empresa", str(e.exception))

    def test_direccion_no_valida_y_limite(self):
        with self.assertRaises(ValueError):
            correo._destinatarios("esto no es un correo")
        with self.assertRaises(ValueError):
            correo._destinatarios(["a@x.es", "b@x.es", "c@x.es"])
        self.assertEqual(correo._destinatarios("Ana <ana@x.es>"), ["ana@x.es"])

    def test_inyeccion_de_cabeceras_no_pasa(self):
        with self.assertRaises(ValueError):
            correo._destinatarios("a@x.es\r\nBcc: otro@x.es")
        self.assertNotIn("\n", correo._limpiar_asunto("Hola\r\nBcc: otro@x.es"))

    def test_texto_vacio_o_largo(self):
        with self.assertRaises(ValueError):
            correo._texto_valido("   ", "asunto")
        with self.assertRaises(ValueError):
            correo._texto_valido("x" * 501, "asunto")
        with self.assertRaises(ValueError):
            correo._texto_valido("hola", "  ")

    def test_automaticos(self):
        def msg(**c):
            m = EmailMessage()
            m["From"] = c.pop("From", "Ana <ana@ejemplo.es>")
            for k, v in c.items():
                m[k.replace("_", "-")] = v
            m.set_content("x")
            return correo.email.message_from_bytes(m.as_bytes())
        self.assertFalse(correo.es_automatico(msg()))
        self.assertTrue(correo.es_automatico(msg(Auto_Submitted="auto-replied")))
        self.assertTrue(correo.es_automatico(msg(Precedence="bulk")))
        self.assertTrue(correo.es_automatico(msg(List_Id="<x.lista>")))
        self.assertTrue(correo.es_automatico(msg(From="noreply@banco.es")))
        self.assertTrue(correo.es_automatico(msg(From="MAILER-DAEMON@mx.es")))
        self.assertFalse(correo.es_automatico(msg(Auto_Submitted="no")))

    def test_las_operaciones_externas_tienen_vista_para_quien_aprueba(self):
        from cerebro.herramientas import base
        h = base._REGISTRO["correo"]
        self.assertEqual(h.externas, frozenset({"responder", "enviar"}))
        self.assertEqual(set(h.vistas), set(h.externas))

    def test_vista_de_enviar_muestra_texto_y_destinatario(self):
        v = ejecutar(correo.vista_enviar("finanzas", "cliente@ejemplo.es", "Factura", "Adjunto su factura."))
        campos = dict(v["campos"])
        self.assertEqual(campos["Para"], "cliente@ejemplo.es")
        self.assertIn("Adjunto su factura.", campos["Mensaje"])
        self.assertIn("Administración", campos["Mensaje"])          # firma del buzón
        self.assertEqual(campos["De"], "administracion@101.cat")

    def test_la_vista_respeta_el_buzon_del_departamento(self):
        with self.assertRaises(PermissionError):
            ejecutar(correo.vista_enviar("personas", "a@x.es", "Hola", "Hola", buzon="administracion"))

    def test_comercial_lleva_pie(self):
        v = ejecutar(correo.vista_enviar("comercial", "a@x.es", "Oferta", "Hola", buzon="comercial", comercial=True))
        self.assertIn("BAJA", dict(v["campos"])["Mensaje"])


@unittest.skipUnless(HOST, "sin servidor de pruebas (CEREBRO_PRUEBA_CORREO)")
class TestConServidor(Base):
    def entregar(self, a, de="Ana <ana@ejemplo.es>", asunto="Consulta", cuerpo="Necesito información.", mid="<m1@ejemplo.es>", **cab):
        m = EmailMessage()
        m["From"], m["To"], m["Subject"], m["Message-ID"] = de, a, asunto, mid
        for k, v in cab.items():
            m[k.replace("_", "-")] = v
        m.set_content(cuerpo)
        with smtplib.SMTP(HOST, 3025) as s:
            s.send_message(m, from_addr=m["From"].split("<")[-1].strip(">"), to_addrs=[a])

    def setUp(self):
        super().setUp()
        self.suf = os.urandom(3).hex()
        # buzones distintos en cada prueba para no depender del orden
        for i, b in CONFIG["buzones"].items():
            b["direccion"] = f"{i}{self.suf}@101.cat"
        with open(self.f.name, "w", encoding="utf-8") as fh:
            yaml.safe_dump(CONFIG, fh)
        B.limpiar_cache()

    def tearDown(self):
        for i, b in CONFIG["buzones"].items():
            b["direccion"] = f"{i}@101.cat"
        super().tearDown()

    def test_leer_y_aislamiento(self):
        self.entregar(f"rrhh{self.suf}@101.cat")
        r = ejecutar(correo.leer_bandeja("personas"))
        self.assertEqual(len(r["mensajes"]), 1)
        self.assertEqual(r["mensajes"][0]["asunto"], "Consulta")
        self.assertIn("no órdenes", r["aviso"])
        self.assertFalse(r["mensajes"][0]["automatico"])
        self.assertNotIn("_contestar_a", r["mensajes"][0])
        self.assertEqual(ejecutar(correo.leer_bandeja("finanzas"))["mensajes"], [])           # el otro buzón no lo ve
        self.assertEqual(len(ejecutar(correo.leer_bandeja("personas"))["mensajes"]), 1)       # leer no marca como leído

    def test_responder_contesta_al_remitente_una_sola_vez(self):
        self.entregar(f"rrhh{self.suf}@101.cat", asunto="Vacaciones", mid="<v1@ejemplo.es>")
        v = ejecutar(correo.vista_responder("personas", "<v1@ejemplo.es>", "Claro, queda anotado."))
        self.assertEqual(dict(v["campos"])["Para"], "ana@ejemplo.es")
        self.assertEqual(dict(v["campos"])["Asunto"], "Re: Vacaciones")
        r = ejecutar(correo.responder("personas", "<v1@ejemplo.es>", "Claro, queda anotado."))
        self.assertEqual(r["para"], "ana@ejemplo.es")
        # la respuesta llegó al buzón de Ana (GreenMail la crea en su buzón) con las cabeceras de hilo
        import imaplib
        con = imaplib.IMAP4(HOST, 3143)
        con.login("ana@ejemplo.es", "x")
        con.select("INBOX")
        _, d = con.search(None, "ALL")
        _, p = con.fetch(d[0].split()[-1], "(RFC822)")
        txt = p[0][1].decode()
        con.logout()
        self.assertIn("In-Reply-To: <v1@ejemplo.es>", txt)
        self.assertIn("Claro, queda anotado.", txt)
        # segunda vez: ya está contestado
        with self.assertRaises(PermissionError) as e:
            ejecutar(correo.vista_responder("personas", "<v1@ejemplo.es>", "otra vez"))
        self.assertIn("contestado", str(e.exception))
        self.assertTrue(ejecutar(correo.leer_bandeja("personas", no_leidos=False))["mensajes"][0]["respondido"])

    def test_no_se_contesta_a_automaticos(self):
        self.entregar(f"rrhh{self.suf}@101.cat", mid="<a1@ejemplo.es>", Auto_Submitted="auto-generated")
        with self.assertRaises(PermissionError) as e:
            ejecutar(correo.vista_responder("personas", "<a1@ejemplo.es>", "hola"))
        self.assertIn("automático", str(e.exception))

    def test_responder_a_mensaje_inexistente(self):
        with self.assertRaises(LookupError):
            ejecutar(correo.vista_responder("personas", "<no-existe@x.es>", "hola"))

    def test_responder_a_un_mensaje_de_otro_buzon_no_se_puede(self):
        self.entregar(f"administracion{self.suf}@101.cat", mid="<ad1@ejemplo.es>")
        with self.assertRaises(LookupError):
            ejecutar(correo.vista_responder("personas", "<ad1@ejemplo.es>", "hola"))

    def test_responder_a_remitente_interno_se_rechaza(self):
        self.entregar(f"rrhh{self.suf}@101.cat", de=f"Comercial <comercial{self.suf}@101.cat>", mid="<i1@101.cat>")
        with self.assertRaises(ValueError):
            ejecutar(correo.vista_responder("personas", "<i1@101.cat>", "hola"))

    def test_borrador_queda_en_la_carpeta(self):
        r = ejecutar(correo.preparar_borrador("personas", "cand@ejemplo.es", "Entrevista", "Te proponemos el martes."))
        self.assertEqual(r["carpeta"], "Drafts")
        import imaplib
        con = imaplib.IMAP4(HOST, 3143)
        con.login(f"rrhh{self.suf}@101.cat", "x")
        self.assertEqual(con.select("Drafts")[0], "OK")
        _, d = con.search(None, "ALL")
        self.assertEqual(len(d[0].split()), 1)
        con.logout()

    def test_enviar_llega_y_se_archiva(self):
        ejecutar(correo.enviar("finanzas", "cli@ejemplo.es", "Factura 1", "Adjunto la factura."))
        import imaplib
        con = imaplib.IMAP4(HOST, 3143)
        con.login("cli@ejemplo.es", "x")
        con.select("INBOX")
        _, d = con.search(None, "SUBJECT", '"Factura 1"')
        self.assertTrue(d[0].split())
        con.logout()

    def test_contrasena_incorrecta_se_nota_en_el_error(self):
        del os.environ["CORREO_RRHH_CLAVE"]
        with self.assertRaises(PermissionError):
            ejecutar(correo.leer_bandeja("personas"))


try:
    from cerebro.grafo import nodos
    from cerebro.registro import registro
    HAY_GRAFO = True
except ImportError:
    HAY_GRAFO = False


@unittest.skipUnless(HAY_GRAFO, "requiere las dependencias del contenedor")
class TestAprobacionDeCorreo(Base):
    """Un correo saliente nunca se ejecuta sin que una persona lo vea, aunque el agente sea de autonomía «libre» y bautice la acción como quiera."""

    def preparar(self, operacion, argumentos, aprobacion="libre"):
        import dataclasses
        from unittest import mock
        ficha = next(f for f in registro().fichas.values() if f.departamento == "finanzas" and "correo" in f.herramientas)
        libre = dataclasses.replace(ficha, aprobacion=aprobacion)
        creadas = []

        async def crear(hilo, agente, departamento, accion, nivel, aprobadores, voz, datos):
            creadas.append({"nivel": nivel, "datos": datos})
            return "sid-1"
        estado = {"agente": ficha.id, "acciones": [{"accion": "algo_inventado", "herramienta": "correo", "operacion": operacion,
                                                    "resumen": "r", "argumentos": argumentos}]}
        with mock.patch.dict(registro().fichas, {ficha.id: libre}), mock.patch.object(nodos.bandeja, "crear", crear):
            r = ejecutar(nodos.registrar_aprobaciones(estado, {"configurable": {"thread_id": "h"}}))
        return r["acciones"][0], creadas

    def test_enviar_va_a_la_bandeja_con_el_texto_completo(self):
        a, creadas = self.preparar("enviar", {"para": "cli@ejemplo.es", "asunto": "Factura", "cuerpo": "Adjunto la factura 123."})
        self.assertEqual(a["estado"], "pendiente")
        self.assertEqual(creadas[0]["nivel"], "simple")
        campos = dict(creadas[0]["datos"]["vista"]["campos"])
        self.assertEqual(campos["Para"], "cli@ejemplo.es")
        self.assertIn("factura 123", campos["Mensaje"])

    def test_enviar_a_un_buzon_ajeno_no_llega_a_la_bandeja(self):
        a, creadas = self.preparar("enviar", {"para": "cli@ejemplo.es", "asunto": "x", "cuerpo": "y", "buzon": "rrhh"})
        self.assertEqual(a["estado"], "error")
        self.assertEqual(creadas, [])
        self.assertIn("rrhh", a["resultado"])

    def test_responder_a_un_mensaje_inexistente_no_pide_aprobacion(self):
        from unittest import mock
        with mock.patch.object(correo, "_imap", side_effect=PermissionError("sin servidor")):
            a, creadas = self.preparar("responder", {"message_id": "<no@x>", "cuerpo": "hola"})
        self.assertEqual(a["estado"], "error")
        self.assertEqual(creadas, [])


if __name__ == "__main__":
    unittest.main()
