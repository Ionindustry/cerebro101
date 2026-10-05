"""Completa el asistente inicial de ERPNext por línea de comandos (empresa, moneda, plan contable, ejercicio).

Uso:  python scripts/erpnext_asistente.py --empresa "Razón Social SL" --abreviatura RS [--pais Spain] [--moneda EUR]
                                          [--idioma es] [--zona Europe/Madrid] [--plan "Standard with Numbers"] [--ejercicio 2026]
Es idempotente: si el asistente ya está completado, no hace nada. ERPNext no trae el Plan General Contable español:
el plan por defecto es genérico y numerado; la gestoría debe indicar cuál usar antes de contabilizar nada real.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def construir_args(empresa: str, abreviatura: str, pais: str = "Spain", moneda: str = "EUR", idioma: str = "es",
                   zona: str = "Europe/Madrid", plan: str = "Standard with Numbers", ejercicio: int = 2026) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9]{2,5}", abreviatura):
        raise ValueError("La abreviatura debe tener de 2 a 5 letras o cifras")
    if not empresa.strip():
        raise ValueError("Falta el nombre de la empresa")
    return {"args": {"language": idioma, "country": pais, "timezone": zona, "currency": moneda,
                     "company_name": empresa.strip(), "company_abbr": abreviatura.upper(), "chart_of_accounts": plan,
                     "fy_start_date": f"{ejercicio}-01-01", "fy_end_date": f"{ejercicio}-12-31", "bank_account": "Banco principal"}}


def main() -> int:
    raiz = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--empresa", required=True)
    p.add_argument("--abreviatura", required=True)
    p.add_argument("--pais", default="Spain")
    p.add_argument("--moneda", default="EUR")
    p.add_argument("--idioma", default="es")
    p.add_argument("--zona", default="Europe/Madrid")
    p.add_argument("--plan", default="Standard with Numbers")
    p.add_argument("--ejercicio", type=int, default=2026)
    p.add_argument("--env", default=str(raiz / ".env"))
    p.add_argument("--compose", default=str(raiz / "erpnext" / "docker-compose.yml"))
    a = p.parse_args()
    try:
        args = construir_args(a.empresa, a.abreviatura, a.pais, a.moneda, a.idioma, a.zona, a.plan, a.ejercicio)
    except ValueError as e:
        p.error(str(e))
    env = Path(a.env).read_text(encoding="utf-8")
    sitio = (re.search(r"^ERPNEXT_SITE=(.+)$", env, re.M) or [None, "erp.101.cat"])[1].strip()
    r = subprocess.run(["docker", "compose", "-f", a.compose, "--env-file", a.env, "exec", "-T", "backend", "bench", "--site", sitio,
                        "execute", "frappe.desk.page.setup_wizard.setup_wizard.setup_complete", "--kwargs", json.dumps(args)],
                       capture_output=True, text=True)
    if r.returncode != 0 or '"status": "ok"' not in r.stdout:
        print("El asistente no terminó bien:\n" + (r.stdout + r.stderr)[-800:])
        return 1
    print(f"Asistente de ERPNext completado para «{a.empresa}» ({sitio}). Plan contable: {a.plan}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
