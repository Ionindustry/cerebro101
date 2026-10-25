"""Prueba de extremo a extremo de las aprobaciones (firma única de Dirección), con la base de datos y el grafo reales.

Solo se sustituye el modelo de IA (para que la prueba sea rápida y repetible): el resto es el camino de producción:
petición -> grafo -> bandeja (PostgreSQL) -> endpoints /aprobaciones -> reanudación del grafo -> herramienta -> registro_acciones -> historial.

    docker compose exec api python /app/scripts/probar_aprobacion_doble.py

Sale con código distinto de 0 si algún control falla. Necesita CEREBRO_MODO=desarrollo (identifica por cabeceras).
"""
from __future__ import annotations

import asyncio
import sys

import httpx
import psycopg

from cerebro.ajustes import ajustes
from cerebro.api.main import app
from cerebro.grafo import nodos

ACCION = {"accion": "enviar_presupuesto", "herramienta": "cotizador", "operacion": "cotizar",
          "argumentos": {"partidas": {"camara_exterior": 2}, "cuadrilla_tecnicos": "uno"},
          "resumen": "Presupuesto de 2 cámaras exteriores"}

# Personas: quién es quién para el panel (cabeceras del modo desarrollo)
PEDRO = {"X-Usuario": "pedro", "X-Roles": "", "X-Departamentos": "comercial"}                        # comercial sin rol de responsable
ANA = {"X-Usuario": "ana", "X-Roles": "responsable", "X-Departamentos": "comercial"}                  # responsable de comercial (no firma: la firma es de Dirección)
LUIS = {"X-Usuario": "luis", "X-Roles": "responsable", "X-Departamentos": "licitaciones"}             # responsable de otro departamento
MARTA = {"X-Usuario": "marta", "X-Roles": "direccion", "X-Departamentos": ""}                         # dirección
CARLOS = {"X-Usuario": "carlos", "X-Roles": "responsable,direccion", "X-Departamentos": "comercial"}  # también dirección

fallos: list[str] = []


def comprobar(cond: bool, texto: str) -> None:
    print(("  ok   " if cond else "  FALLA ") + texto)
    if not cond:
        fallos.append(texto)


async def modelo_simulado(asignacion, mensajes, esquema=None, **_):
    props = (esquema or {}).get("properties", {})
    if "departamento" in props:
        return {"departamento": "comercial", "motivo": "prueba"}
    if "agente" in props:
        return {"agente": "propuestas", "motivo": "prueba"}
    return {"tipo": "respuesta", "respuesta": "Te dejo el presupuesto preparado; necesita tu firma.", "acciones": [ACCION]}


def filas_registro(hilo: str) -> list[tuple]:
    with psycopg.connect(ajustes.database_url) as c:
        return c.execute("SELECT agente, herramienta, operacion, aprobacion, resultado FROM registro_acciones WHERE hilo=%s",
                         (hilo,)).fetchall()


async def pedir(cli: httpx.AsyncClient) -> tuple[str, str]:
    r = await cli.post("/jarvis/mensaje", headers=PEDRO, json={"texto": "Prepara un presupuesto de 2 cámaras exteriores"})
    d = r.json()
    comprobar(r.status_code == 200 and d["esperando_aprobacion"], "la petición queda esperando aprobación (no se ejecuta sola)")
    comprobar(d["acciones"][0]["estado"] == "pendiente", "la acción sale como «pendiente»")
    return d["hilo"], d["acciones"][0]["solicitud_id"]


async def decidir(cli, sid, quien, aprobado=True, canal="panel", comentario="prueba"):
    return await cli.post(f"/aprobaciones/{sid}", headers=quien, json={"aprobado": aprobado, "canal": canal, "comentario": comentario})


async def pendientes(cli, quien) -> list[str]:
    return [str(s["id"]) for s in (await cli.get("/aprobaciones", headers=quien)).json()]


async def historial(cli, quien, **params) -> dict:
    return (await cli.get("/aprobaciones/historial", headers=quien, params=params)).json()


async def principal() -> None:
    nodos.chat = modelo_simulado                       # único elemento simulado
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://prueba") as cli:
            print("\n== Una sola firma: la de Dirección ==")
            hilo, sid = await pedir(cli)
            lista = (await cli.get("/aprobaciones", headers=ANA)).json()
            mia = next((s for s in lista if str(s["id"]) == sid), None)
            comprobar(mia is not None and mia["aprobadores"] == ["direccion"], "el responsable de comercial la ve, y solo se pide la firma de dirección")
            comprobar(sid not in await pendientes(cli, LUIS), "un responsable de otro departamento no la ve")
            comprobar(sid in await pendientes(cli, MARTA), "dirección la ve")

            for quien, nombre in ((PEDRO, "sin rol"), (ANA, "responsable del departamento"), (LUIS, "responsable de otro departamento")):
                r = await decidir(cli, sid, quien)
                comprobar(r.status_code == 403, f"{nombre} no puede firmar (403)")
            r = await decidir(cli, sid, MARTA, canal="voz")
            comprobar(r.status_code == 403, "lo delicado no se firma por voz (403)")
            comprobar(filas_registro(hilo) == [], "sin firma NO se ejecuta nada")

            r = await decidir(cli, sid, MARTA, comentario="Todo correcto")
            d = r.json()
            comprobar(r.status_code == 200 and d["estado"] == "aprobada", "firma de dirección: aprobada con una sola firma")
            comprobar(d.get("acciones", [{}])[0].get("estado") == "ejecutada", "el grafo se reanuda y ejecuta la acción")
            filas = filas_registro(hilo)
            comprobar(len(filas) == 1 and str(filas[0][3]) == sid and filas[0][4].startswith("OK"), "queda una fila en registro_acciones ligada a la aprobación")
            r = await decidir(cli, sid, CARLOS)
            comprobar(r.status_code == 403, "una solicitud ya cerrada no admite más firmas (403)")
            comprobar(len(filas_registro(hilo)) == 1, "no se ejecuta dos veces")
            comprobar(sid not in await pendientes(cli, MARTA), "la aprobada sale de «pendientes»")

            print("\n== Rechazo ==")
            hilo2, sid2 = await pedir(cli)
            r = await decidir(cli, sid2, MARTA, aprobado=False, comentario="Precio no válido")
            comprobar(r.status_code == 200 and r.json()["estado"] == "rechazada", "dirección rechaza: la solicitud queda rechazada")
            comprobar(filas_registro(hilo2) == [], "no se ejecuta ni queda fila en registro_acciones")
            comprobar(sid2 not in await pendientes(cli, MARTA), "la rechazada sale de «pendientes»")
            r = await decidir(cli, sid2, CARLOS)
            comprobar(r.status_code == 403, "tras el rechazo no se puede aprobar (403)")

            print("\n== Historial: se guardan todas ==")
            h = await historial(cli, MARTA)
            por_id = {str(x["id"]): x for x in h["items"]}
            comprobar(sid in por_id and sid2 in por_id, "dirección ve en el historial la aprobada y la rechazada")
            comprobar(por_id[sid]["estado"] == "aprobada" and por_id[sid]["resultado"].startswith("OK"), "la aprobada guarda lo que se ejecutó")
            d0 = por_id[sid]["decisiones"][0]
            comprobar(d0["usuario"] == "marta" and d0["comentario"] == "Todo correcto" and d0.get("fecha"), "guarda quién, cuándo y con qué comentario decidió")
            comprobar(por_id[sid2]["estado"] == "rechazada" and por_id[sid2]["resultado"] is None, "la rechazada no tiene resultado de ejecución")
            h = await historial(cli, MARTA, decision="rechazada")
            comprobar(h["items"] and all(x["estado"] == "rechazada" for x in h["items"]), "el filtro por decisión funciona")
            h = await historial(cli, MARTA, q="enviar_presupuesto", limite=1)
            comprobar(h["total"] >= 2 and len(h["items"]) == 1, "la búsqueda y la paginación funcionan")
            comprobar(sid in {str(x["id"]) for x in (await historial(cli, ANA))["items"]}, "el departamento ve las suyas en el historial")
            comprobar(sid not in {str(x["id"]) for x in (await historial(cli, LUIS))["items"]}, "otro departamento no ve las ajenas")

            print("\n== Concurrencia: dos personas de dirección firman a la vez ==")
            hilo3, sid3 = await pedir(cli)
            r1, r2 = await asyncio.gather(decidir(cli, sid3, MARTA), decidir(cli, sid3, CARLOS))
            comprobar(sorted([r1.status_code, r2.status_code]) == [200, 403], "solo una de las dos firmas cuenta (la otra recibe 403)")
            comprobar(len(filas_registro(hilo3)) == 1, "la acción se ejecuta exactamente una vez")


if __name__ == "__main__":
    asyncio.run(principal())
    print(f"\n{len(fallos)} fallo(s)")
    sys.exit(1 if fallos else 0)
