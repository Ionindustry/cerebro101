"""Comprueba que cada buzón configurado conecta (IMAP y SMTP) con su contraseña, sin leer ni enviar ningún correo.

    python3 scripts/probar_buzones.py [--id rrhh]
    docker compose exec api python /app/scripts/probar_buzones.py      # desde el contenedor, igual que lo ve la API

Muestra para cada buzón: si tiene contraseña, si entra por IMAP y si entra por SMTP. Nunca imprime contraseñas.
Sale con código 1 si algún buzón activo falla.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "api"))

from cerebro.herramientas import buzones as B  # noqa: E402
from cerebro.herramientas import correo  # noqa: E402

if not Path("/run/secretos/buzones.env").exists():          # fuera del contenedor: los ficheros del repositorio
    B.RUTA_CONFIG = str(RAIZ / "config" / "buzones.yaml")
    B.RUTA_SECRETOS = str(RAIZ / "secretos" / "buzones.env")


def probar(ident: str) -> bool:
    if not B.activo(ident):
        print(f"  {ident:<16} sin contraseña (sin dar de alta: scripts/buzon_alta.py --id {ident})")
        return True
    estado = []
    smtp = B.servidor(ident, "smtp")
    print(f"  ({ident}: SMTP {smtp['host']}:{smtp['puerto']} {smtp['seguridad']}, certificado verificado contra «{smtp.get('tls_nombre') or smtp['host']}»)")
    try:
        con = correo._imap(ident)
        con.select("INBOX", readonly=True)
        correo._cerrar(con)
        estado.append("IMAP ok")
    except Exception as e:  # noqa: BLE001
        estado.append(f"IMAP FALLA ({type(e).__name__}: {str(e)[:300]})")
    try:
        with correo._smtp(ident):
            pass
        estado.append("SMTP ok")
    except Exception as e:  # noqa: BLE001
        estado.append(f"SMTP FALLA ({type(e).__name__}: {str(e)[:300]})")
    ok = all(" ok" in x for x in estado)
    print(f"  {ident:<16} {B.cargar()['buzones'][ident]['direccion']:<28} {' · '.join(estado)}")
    return ok


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--id")
    r = a.parse_args()
    ids = [r.id] if r.id else list(B.cargar().get("buzones") or {})
    resultados = [probar(i) for i in ids]
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
