"""Prueba de extremo a extremo de la doble aprobación, con la base de datos y el grafo reales.

Solo se sustituye el modelo de IA (para que la prueba sea rápida y repetible): el resto es el camino de producción:
petición -> grafo -> bandeja (PostgreSQL) -> endpoints /aprobaciones -> reanudación del grafo -> herramienta -> registro_acciones.

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
ANA = {"X-Usuario": "ana", "X-Roles": "responsable", "X-Departamentos": "comercial"}                  # responsable de comercial
LUIS = {"X-Usuario": "luis", "X-Roles": "responsable", "X-Departamentos": "licitaciones"}             # responsable de otro departamento
MARTA = {"X-Usuario": "marta", "X-Roles": "direccion", "X-Departamentos": ""}                         # dirección
CARLOS = {"X-Usuario": "carlos", "X-Roles": "responsable,direccion", "X-Departamentos": "comercial"}  # ambos roles, una sola persona

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


async def decidir(cli, sid, quien, aprobado=True, canal="panel"):
    return await cli.post(f"/aprobaciones/{sid}", headers=quien, json={"aprobado": aprobado, "canal": canal, "comentario": "prueba"})


async def principal() -> None:
    nodos.chat = modelo_simulado                       # único elemento simulado
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://prueba") as cli:
            print("\n== Camino feliz: responsable y después dirección ==")
            hilo, sid = await pedir(cli)
            lista = (await cli.get("/aprobaciones", headers=ANA)).json()
            mia = next((s for s in lista if str(s["id"]) == sid), None)
            comprobar(mia is not None and mia["nivel"] == "doble", "la responsable ve la solicitud y es de nivel doble")
            comprobar(mia is not None and mia["voz_permitida"] is False, "la voz no está permitida")
            comprobar(sid not in [str(s["id"]) for s in (await cli.get("/aprobaciones", headers=LUIS)).json()],
                      "un responsable de otro departamento no la ve")

            r = await decidir(cli, sid, PEDRO)
            comprobar(r.status_code == 403, "sin rol de responsable no se puede firmar (403)")
            r = await decidir(cli, sid, LUIS)
            comprobar(r.status_code == 403, "un responsable de otro departamento no puede firmar (403)")
            r = await decidir(cli, sid, ANA, canal="voz")
            comprobar(r.status_code == 403, "por voz no se puede firmar una doble (403)")

            r = await decidir(cli, sid, ANA)
            comprobar(r.status_code == 200 and r.json()["estado"] == "pendiente", "primera firma: sigue pendiente, falta la segunda")
            comprobar(filas_registro(hilo) == [], "con una sola firma NO se ejecuta nada")
            r = await decidir(cli, sid, ANA)
            comprobar(r.status_code == 403, "la misma persona no puede firmar dos veces (403)")
            r = await decidir(cli, sid, CARLOS, canal="voz")
            comprobar(r.status_code == 403, "la segunda firma tampoco vale por voz (403)")
            r = await decidir(cli, sid, LUIS)
            comprobar(r.status_code == 403, "ni un responsable ajeno puede dar la segunda (hace falta dirección)")

            r = await decidir(cli, sid, MARTA)
            d = r.json()
            comprobar(r.status_code == 200 and d["estado"] == "aprobada", "segunda firma de dirección: aprobada")
            comprobar(d.get("acciones", [{}])[0].get("estado") == "ejecutada", "el grafo se reanuda y ejecuta la acción")
            filas = filas_registro(hilo)
            comprobar(len(filas) == 1 and str(filas[0][3]) == sid and filas[0][4].startswith("OK"),
                      "queda una fila en registro_acciones ligada a la aprobación")
            r = await decidir(cli, sid, CARLOS)
            comprobar(r.status_code == 403, "una solicitud ya cerrada no admite más firmas (403)")
            comprobar(len(filas_registro(hilo)) == 1, "no se ejecuta dos veces")

            print("\n== Orden inverso: dirección primero, responsable después ==")
            hilo, sid = await pedir(cli)
            r = await decidir(cli, sid, MARTA)
            comprobar(r.json()["estado"] == "pendiente" and filas_registro(hilo) == [], "dirección firma primero: pendiente y sin ejecutar")
            r = await decidir(cli, sid, ANA)
            comprobar(r.json()["estado"] == "aprobada" and len(filas_registro(hilo)) == 1, "la responsable cierra: se ejecuta una vez")

            print("\n== Una sola persona con los dos roles no puede firmar sola ==")
            hilo, sid = await pedir(cli)
            r = await decidir(cli, sid, CARLOS)
            comprobar(r.json()["estado"] == "pendiente", "Carlos (responsable y dirección) firma una vez: sigue pendiente")
            r = await decidir(cli, sid, CARLOS)
            comprobar(r.status_code == 403 and filas_registro(hilo) == [], "no puede firmar la segunda: hace falta otra persona")
            r = await decidir(cli, sid, MARTA)
            comprobar(r.json()["estado"] == "aprobada" and len(filas_registro(hilo)) == 1, "con otra persona se completa")

            print("\n== Rechazo de la segunda firma ==")
            hilo, sid = await pedir(cli)
            await decidir(cli, sid, ANA)
            r = await decidir(cli, sid, MARTA, aprobado=False)
            d = r.json()
            comprobar(r.status_code == 200 and d["estado"] == "rechazada", "dirección rechaza: la solicitud queda rechazada")
            comprobar(d.get("acciones", [{}])[0].get("estado") != "ejecutada", "la acción no se ejecuta")
            comprobar(filas_registro(hilo) == [], "no hay fila en registro_acciones")
            r = await decidir(cli, sid, CARLOS)
            comprobar(r.status_code == 403, "tras el rechazo no se puede aprobar (403)")

            print("\n== Rechazo de la primera firma ==")
            hilo, sid = await pedir(cli)
            r = await decidir(cli, sid, ANA, aprobado=False)
            comprobar(r.json()["estado"] == "rechazada" and filas_registro(hilo) == [], "la responsable rechaza: cerrada sin ejecutar")

            print("\n== Concurrencia: las dos firmas llegan a la vez ==")
            hilo, sid = await pedir(cli)
            ra, rm = await asyncio.gather(decidir(cli, sid, ANA), decidir(cli, sid, MARTA))
            comprobar(sorted([ra.status_code, rm.status_code]) == [200, 200], "ambas firmas se aceptan (la fila se bloquea, no se pierde ninguna)")
            comprobar(len(filas_registro(hilo)) == 1, "la acción se ejecuta exactamente una vez")


if __name__ == "__main__":
    asyncio.run(principal())
    print(f"\n{len(fallos)} fallo(s)")
    sys.exit(1 if fallos else 0)
