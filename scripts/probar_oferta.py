"""Revisión previa («pre-vuelo») de «Preparar la oferta con los agentes» para una licitación: comprueba, SIN cambiar nada ni llamar a ningún modelo, que están los ingredientes
y dice qué falta. Sirve para probar la oferta de punta a punta con una licitación real sin perder una pasada de los agentes por un dato que faltaba.

    docker compose exec api python /app/scripts/probar_oferta.py                  # elige la licitación «en estudio» con mejor encaje
    docker compose exec api python /app/scripts/probar_oferta.py <id del motor>   # una licitación concreta (el UUID de la ficha)

Comprueba: la licitación en el embudo, la ficha del motor, la sociedad del ERP y sus datos, el DEUC base, los pliegos descargados, los requisitos (y la aptitud según el perfil de la
empresa), las plantillas y la última ejecución de los agentes. Sale con código 1 si hay algo que bloquea. Es de solo lectura: no escribe en la base ni en el ERP.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "api"))

from cerebro.licitaciones import aptitud, embudo, empresa, ofertas, pliegos, plantillas, redaccion  # noqa: E402

BLOQUEOS: list[str] = []
AVISOS: list[str] = []


def ok(t: str):
    print(f"  ✔ {t}")


def aviso(t: str):
    AVISOS.append(t)
    print(f"  ! {t}")


def bloqueo(t: str):
    BLOQUEOS.append(t)
    print(f"  ✘ {t}")


async def elegir_licitacion(motor_id: str | None) -> dict | None:
    if motor_id:
        filas = await embudo.listar(motor_id=motor_id, limite=1)
        return filas[0] if filas else {"motor_id": motor_id, "titulo": "(no está en el embudo)", "estado": None, "encaje": None}
    filas = await embudo.listar("en_estudio", None, 200)
    return max(filas, key=lambda f: f.get("encaje") or 0) if filas else None


async def revisar(motor_id: str, fila: dict) -> None:
    print(f"\nLicitación: {fila.get('titulo')}\n  id del motor: {motor_id} · estado en el embudo: {fila.get('estado') or 'no está'} · encaje: {fila.get('encaje')}")

    print("\n1. Ficha en el motor")
    try:
        ficha = await plantillas.ficha_del_motor(motor_id)
        if ficha:
            ok(f"El motor devuelve la ficha ({len(pliegos.documentos_de(ficha))} documentos en el pliego)")
        else:      # ficha_del_motor no lanza si el motor no responde: devuelve una ficha vacía (y lo deja en el registro)
            bloqueo("El motor no devuelve la ficha de esta licitación (¿motor caído, sin token LICITACIONES_API_TOKEN o id equivocado?)")
    except Exception as e:      # noqa: BLE001
        ficha = {}
        bloqueo(f"No se puede leer la ficha en el motor: {type(e).__name__}: {e}")

    print("\n2. Sociedad que presenta la oferta (ERP)")
    nombre = None
    try:
        nombre = await empresa.elegir(None)
        ok(f"Sociedad: {nombre}")
    except empresa.VariasEmpresas as e:
        aviso("Hay varias empresas en el ERP: hay que elegir con cuál se presenta en la tarjeta «Documentación administrativa» de la oferta (" + ", ".join(x["razon_social"] for x in e.empresas) + ")")
        nombre = e.empresas[0]["nombre"]
    except Exception as e:      # noqa: BLE001
        bloqueo(f"El ERP no da la sociedad: {type(e).__name__}: {e}")
    if nombre:
        try:
            d = await plantillas.claves_disponibles(nombre, ficha, motor_id)
            falta = {k: v for k, v in d["faltan"].items() if not k.startswith("oferta.")}
            ok(f"{len(d['disponibles'])} datos disponibles para las plantillas")
            for k, donde in falta.items():
                aviso(f"Falta el dato «{k}»: {donde}")
        except Exception as e:      # noqa: BLE001
            aviso(f"No se han podido comprobar los datos de la sociedad: {type(e).__name__}: {e}")
        try:
            dd = await empresa.deuc_base(nombre)
            ok(f"DEUC base: «{dd[0]}» ({dd[2]})") if dd else aviso("No hay DEUC base de esta sociedad: súbelo a Jarvis (agente Administrativo: «Guarda este documento como DEUC base»)")
        except Exception as e:      # noqa: BLE001
            aviso(f"No se ha podido comprobar el DEUC base: {type(e).__name__}: {e}")

    print("\n3. Pliegos")
    try:
        docs = (await pliegos.documentos(motor_id))["documentos"]
        limpios = [d for d in docs if (d.get("descarga") or {}).get("estado") in ("limpio", "con_macros")]
        ok(f"{len(limpios)} de {len(docs)} documentos descargados y analizados") if limpios else aviso(
            f"Ningún documento del pliego está descargado y analizado ({len(docs)} en la ficha): «Descargar y analizar» en la ficha del expediente")
    except Exception as e:      # noqa: BLE001
        aviso(f"No se han podido comprobar los pliegos: {type(e).__name__}: {e}")

    print("\n4. Requisitos y aptitud según el perfil de la empresa")
    try:
        reqs = (await pliegos.requisitos(motor_id))["requisitos"]
        cuenta = {e: sum(1 for r in reqs if r["estado"] == e) for e in ("confirmado", "borrador", "rechazado")}
        ok(f"{len(reqs)} requisitos: {cuenta['confirmado']} confirmados, {cuenta['borrador']} en borrador, {cuenta['rechazado']} rechazados") if reqs else aviso(
            "No hay requisitos anotados: pide al Analista de Pliegos que los extraiga antes de preparar la oferta")
        if cuenta["borrador"]:
            aviso(f"Hay {cuenta['borrador']} requisitos en borrador sin revisar")
        r = aptitud.resumen(aptitud.con_sugerencias([x for x in reqs if x["estado"] != "rechazado"]))
        if r["bloqueos"]:
            aviso(f"Según el perfil de la empresa, {r['bloqueos']} requisitos probablemente NO se cumplen (mira las sugerencias en la ficha): valora si compensa seguir")
    except Exception as e:      # noqa: BLE001
        aviso(f"No se han podido comprobar los requisitos: {type(e).__name__}: {e}")

    print("\n5. Oferta y última pasada de los agentes")
    try:
        o = await ofertas.leer(motor_id, con_contenido=False)
        ok(f"La oferta existe: {len(o.get('secciones') or [])} secciones") if o.get("existe", True) and o.get("secciones") else aviso(
            "La oferta aún no tiene secciones: se crean al pulsar «Preparar la oferta» (a partir de los criterios y requisitos del pliego)")
        e = await redaccion.ultima(motor_id)
        if not e:
            ok("Aún no se ha lanzado ninguna pasada de los agentes")
        else:
            print(f"     última pasada: #{e['id']} · {e['estado']} · {e.get('error') or 'sin error'}")
            for p in e.get("pasos") or []:
                print(f"       - {p.get('titulo') or p.get('id')}: {p.get('estado')}")
            if e["estado"] == "en_curso":
                aviso("Hay una pasada «en curso»: si lleva más de 3 horas sin avanzar se sustituye sola; si acabas de reiniciar el worker, se cortó y hay que repetirla")
    except Exception as e:      # noqa: BLE001
        aviso(f"No se ha podido leer la oferta: {type(e).__name__}: {e}")


async def main() -> int:
    motor_id = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        fila = await elegir_licitacion(motor_id)
    except Exception as e:      # noqa: BLE001
        print(f"No se ha podido leer el embudo: {type(e).__name__}: {e}")
        return 1
    if not fila:
        print("No hay ninguna licitación «en estudio» en el embudo: pasa una a «en estudio» desde Jarvis (o indica su id).")
        return 1
    await revisar(str(fila["motor_id"]), fila)
    print()
    if BLOQUEOS:
        print(f"RESULTADO: hay {len(BLOQUEOS)} cosas que bloquean; arréglalas antes de lanzar a los agentes.")
        return 1
    print(f"RESULTADO: se puede lanzar «Preparar la oferta con los agentes»" + (f" (con {len(AVISOS)} avisos que conviene mirar)." if AVISOS else "."))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
