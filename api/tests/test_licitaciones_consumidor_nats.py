"""El consumidor de extremo a extremo: un servidor NATS con JetStream de verdad y PostgreSQL de verdad (el motor se simula).

Necesita CEREBRO_TEST_PG y CEREBRO_TEST_NATS_BIN (ruta del ejecutable nats-server, p. ej. el que se compila con
`go build -o /tmp/nats-server github.com/nats-io/nats-server/v2` desde licitaciones/); sin ellos se omite."""
import asyncio
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _sin_servicios  # noqa: F401

try:
    import nats
    import psycopg
    from cerebro.licitaciones import alertas, consumidor, embudo
except ImportError as e:      # pragma: no cover
    raise unittest.SkipTest(str(e))

URL, SERVIDOR = os.environ.get("CEREBRO_TEST_PG"), os.environ.get("CEREBRO_TEST_NATS_BIN")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema.sql"
ID = "0b1f7a3e-1111-4222-8333-444444444444"
ORIGEN = "https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/12345"
CFG = {"pesos": {"cpv": 40, "zona": 20, "importe": 15, "plazo": 15, "procedimiento": 10}, "importe_max": 1_000_000,
       "cpv": [{"codigo": "32000000", "area": "Videovigilancia"}], "zona": {"prioritaria": "ES51", "pais": "ES"}, "embudo": {"encaje_min": 60}}


def licitacion(**kw):
    x = {"id": ID, "version_entidad": 1, "expediente": "2026/045", "titulo": "Videovigilancia del puerto", "comprador": {"nombre": "Girona"}, "estado": "abierta",
         "procedimiento": "abierto", "cpv": ["32323500"], "nuts": ["ES512"], "plazo_presentacion": "2026-12-20T10:00:00Z",
         "importe": {"valor": "200000.00", "moneda": "EUR"}}
    x.update(kw)
    return x


def evento(tipo, version=1, id="e", origen=ORIGEN):
    return json.dumps({"id": id, "tipo": f"licitacion.{tipo}", "fuente": "placsp-643", "id_origen": origen, "version": version,
                       "sha256_original": "ab", "clave_original": "k"}).encode()


@unittest.skipUnless(URL and SERVIDOR and os.path.exists(SERVIDOR or ""), "sin CEREBRO_TEST_PG o CEREBRO_TEST_NATS_BIN")
class TestConNatsReal(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = f"t_cons_{time.time_ns()}"
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"CREATE SCHEMA {self.schema}")
            c.execute(f"SET search_path = {self.schema}")
            t = ESQUEMA.read_text(encoding="utf-8")
            c.execute(t[t.index("-- Licitaciones\nCREATE TABLE IF NOT EXISTS licitaciones"):t.index("-- Resumen diario de licitaciones")])
        sep = "&" if "?" in URL else "?"
        self.parches = [
            mock.patch.object(embudo, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}", zona_horaria="Europe/Madrid")),
            mock.patch.object(alertas, "ajustes", SimpleNamespace(database_url=f"{URL}{sep}options=-csearch_path%3D{self.schema}")),
            mock.patch.object(embudo.resumen_mod, "config", lambda: CFG),
            mock.patch.object(consumidor, "ESPERAS", (1,)),          # reintentos rápidos para la prueba
            mock.patch.dict(os.environ, {"LICITACIONES_NATS_URL": "", "LICITACIONES_ENCAJE_MIN": "60"}),
        ]
        for p in self.parches:
            p.start()
        s = socket.socket(); s.bind(("127.0.0.1", 0)); self.puerto = s.getsockname()[1]; s.close()
        self.dir = tempfile.mkdtemp()
        self.proc = subprocess.Popen([SERVIDOR, "-js", "-a", "127.0.0.1", "-p", str(self.puerto), "-sd", self.dir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.environ["LICITACIONES_NATS_URL"] = f"nats://127.0.0.1:{self.puerto}"
        for _ in range(100):                # esperar a que el servidor escuche, sin ensuciar la salida con reintentos de conexión
            with socket.socket() as sk:
                if sk.connect_ex(("127.0.0.1", self.puerto)) == 0:
                    break
            await asyncio.sleep(0.1)
        self.nc = await nats.connect(os.environ["LICITACIONES_NATS_URL"])
        self.js = self.nc.jetstream()
        await self.js.add_stream(name=consumidor.STREAM, subjects=["licitacion.>"])

    async def asyncTearDown(self):
        await self.nc.close()
        self.proc.terminate()
        self.proc.wait(10)
        shutil.rmtree(self.dir, ignore_errors=True)
        for p in reversed(self.parches):          # al revés de como se pusieron
            p.stop()
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {self.schema} CASCADE")

    async def publicar(self, tipo, **kw):
        await self.js.publish(f"licitacion.{tipo}.placsp-643", evento(tipo, **kw), headers={"Nats-Msg-Id": f"{tipo}-{kw.get('version', 1)}-{kw.get('id', 'e')}-{time.time_ns()}"})

    async def esperar(self, condicion, segundos=20):
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            filas = await embudo.listar()
            if condicion(filas):
                return filas
            await asyncio.sleep(0.2)
        self.fail(f"no se cumplió la condición; filas: {await embudo.listar()}")

    async def test_de_los_eventos_al_embudo(self):
        estado = {"motor": [licitacion(version_entidad=1)]}

        async def motor_falso(ruta, params=None):
            assert ruta == "/tenders" and params["fuente"] == "placsp" and params["id_origen"] == ORIGEN
            return {"items": estado["motor"]}

        parar = asyncio.Event()
        with mock.patch.object(consumidor.motor, "_get", motor_falso):
            tarea = asyncio.create_task(consumidor.ejecutar(parar))
            try:
                # 1. Mensaje roto: se descarta sin tumbar nada. 2. Nueva abierta con buen encaje: entra como detectada.
                await self.js.publish("licitacion.nueva.placsp-643", b"basura")
                await self.publicar("nueva")
                filas = await self.esperar(lambda f: len(f) == 1)
                self.assertEqual((filas[0]["estado"], filas[0]["estado_motor"], filas[0]["motor_id"], filas[0]["organismo"]), ("detectada", "abierta", ID, "Girona"))

                # 3. Reentrega del mismo evento: no duplica.
                await self.publicar("nueva")
                await asyncio.sleep(1.5)
                self.assertEqual(len(await embudo.listar()), 1)

                # 4. Una persona la pasa a estudio; después el motor la adjudica: se anota el estado del motor, la decisión de la persona se respeta.
                fila = (await embudo.listar())[0]
                await embudo.cambiar_estado(fila["id"], "en_estudio")
                estado["motor"] = [licitacion(version_entidad=2, estado="adjudicada")]
                await self.publicar("adjudicada", version=2)
                filas = await self.esperar(lambda f: f[0]["estado_motor"] == "adjudicada")
                self.assertEqual(filas[0]["estado"], "en_estudio")

                # 5. Un evento cuyo expediente el motor aún no tiene se reintenta y entra cuando aparece.
                estado["motor"] = []
                otro = "https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/999"

                async def motor_tardio(ruta, params=None):
                    if params["id_origen"] == ORIGEN:
                        return {"items": estado["motor"]}
                    return {"items": [licitacion(id="11111111-2222-4333-8444-555555555555", expediente="X-9")] if estado.get("aparece") else []}

                with mock.patch.object(consumidor.motor, "_get", motor_tardio):
                    await self.js.publish("licitacion.nueva.placsp-643", evento("nueva", id="t", origen=otro), headers={"Nats-Msg-Id": "tardio"})
                    await asyncio.sleep(1.5)
                    self.assertEqual(len(await embudo.listar()), 1)            # todavía no está en el motor
                    estado["aparece"] = True
                    await self.esperar(lambda f: len(f) == 2)
            finally:
                parar.set()
                await asyncio.wait_for(tarea, 15)

    async def test_las_alertas_de_los_eventos_al_aviso(self):
        usuario = SimpleNamespace(id="albert", roles={"usuario"}, departamentos={"licitaciones"})
        await alertas.crear(usuario, {"nombre": "Videovigilancia", "ambito": "personal", "filtro": {"cpv": ["32"]}, "eventos": ["licitacion.nueva"], "canal": "panel"})
        await alertas.crear(usuario, {"nombre": "Obras", "ambito": "personal", "filtro": {"cpv": ["45"]}, "eventos": ["licitacion.nueva"], "canal": "panel"})
        ahora = datetime.now(timezone.utc).isoformat()
        preguntas = []

        async def motor_juez(ruta, params=None):                      # el motor hace de juez: solo cumple el filtro de CPV 32
            preguntas.append(params)
            item = licitacion(actualizada_en=ahora)
            if set(params) == {"fuente", "id_origen", "limit"}:
                return {"items": [item]}
            return {"items": [item] if params["cpv"] == ["32"] else []}

        parar = asyncio.Event()
        with mock.patch.object(consumidor.motor, "_get", motor_juez):
            tarea = asyncio.create_task(consumidor.ejecutar(parar))
            try:
                await self.publicar("nueva", id="n1")
                await self.publicar("nueva", id="n1")          # reentrega del mismo evento
                for _ in range(100):
                    r = await alertas.listar_avisos(usuario)
                    if r["items"]:
                        break
                    await asyncio.sleep(0.2)
                await asyncio.sleep(1.5)
                r = await alertas.listar_avisos(usuario)
                self.assertEqual([(x["alerta"], x["motor_id"], x["tipo"], x["leido"]) for x in r["items"]], [("Videovigilancia", ID, "licitacion.nueva", False)])
                self.assertEqual(r["sin_leer"], 1)
                ultimas = {a["nombre"]: a["ultima_entrega"] for a in await alertas.listar(usuario)}
                self.assertIsNotNone(ultimas["Videovigilancia"])
                self.assertIsNone(ultimas["Obras"])               # la que no cumple el filtro no recibe nada
                # Un tipo de evento que ninguna alerta pide no genera ninguna consulta de filtro al motor (el consumidor del embudo sí busca el expediente).
                antes = len(preguntas)
                await self.publicar("adjudicada", id="a1", version=2)
                await asyncio.sleep(1.5)
                self.assertTrue(all(set(p) == {"fuente", "id_origen", "limit"} for p in preguntas[antes:]), preguntas[antes:])
                self.assertEqual((await alertas.listar_avisos(usuario))["sin_leer"], 1)
            finally:
                parar.set()
                await asyncio.wait_for(tarea, 15)

    async def test_el_consumidor_duradero_conserva_el_avance_entre_reinicios(self):
        async def motor_falso(ruta, params=None):
            return {"items": [licitacion()]}

        with mock.patch.object(consumidor.motor, "_get", motor_falso):
            for ronda in range(2):
                parar = asyncio.Event()
                tarea = asyncio.create_task(consumidor.ejecutar(parar))
                try:
                    if ronda == 0:
                        await self.publicar("nueva")
                        await self.esperar(lambda f: len(f) == 1)
                    await asyncio.sleep(1)
                finally:
                    parar.set()
                    await asyncio.wait_for(tarea, 15)
            info = await self.js.consumer_info(consumidor.STREAM, consumidor.DURABLE)
            self.assertEqual((info.num_pending, info.num_ack_pending), (0, 0))
            self.assertEqual(info.delivered.stream_seq, 1)                  # el segundo arranque no volvió a recibir lo ya confirmado


if __name__ == "__main__":
    unittest.main()
