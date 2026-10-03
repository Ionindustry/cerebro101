"""Permite importar las herramientas en un entorno sin las dependencias de red instaladas
(por ejemplo, en un portátil sin el contenedor). Solo crea módulos vacíos si faltan;
en el contenedor del Cerebro se usan los reales."""
import importlib.util
import sys
import types


def _falta(nombre: str) -> bool:
    return nombre not in sys.modules and importlib.util.find_spec(nombre) is None


if _falta("httpx"):
    sys.modules["httpx"] = types.ModuleType("httpx")
if _falta("psycopg"):
    psycopg = types.ModuleType("psycopg")
    filas = types.ModuleType("psycopg.rows")
    filas.dict_row = None
    psycopg.rows = filas
    sys.modules["psycopg"] = psycopg
    sys.modules["psycopg.rows"] = filas
