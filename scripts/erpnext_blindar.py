"""Segunda barrera dentro de ERPNext: los usuarios técnicos del Cerebro (cerebro.*@…) no pueden validar, cancelar
ni borrar documentos contables o de stock, aunque su rol lo permita (p. ej. «Accounts User» puede validar facturas).

La política del Cerebro ya prohíbe validar documentos del ERP y su conector no ofrece esa operación; esto lo impone
también el propio ERP, por si una clave se filtra o hay un fallo. Crea un «Server Script» por documento y evento y
activa los guiones de servidor del sitio. Es idempotente.

Uso:  python scripts/erpnext_blindar.py [--url http://localhost:8081] [--env .env]
Después, reiniciad backend y workers de ERPNext una vez (la primera vez que se activan los guiones de servidor):
      docker compose -f erpnext/docker-compose.yml --env-file .env restart backend queue-short queue-long
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from erpnext_usuario_tecnico import Cliente  # noqa: E402

DOCUMENTOS = ["Sales Invoice", "Purchase Invoice", "Journal Entry", "Payment Entry", "Sales Order", "Purchase Order",
              "Quotation", "Supplier Quotation", "Delivery Note", "Purchase Receipt", "Stock Entry", "Material Request",
              "Stock Reconciliation"]
EVENTOS = {"Before Submit": "validar", "Before Cancel": "cancelar", "Before Delete": "borrar"}
SCRIPT = ('if frappe.session.user.startswith("cerebro."):\n'
          '    frappe.throw("El Cerebro no puede {accion} documentos de este tipo: lo hace siempre una persona.")\n')


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:8081")
    p.add_argument("--env", default=str(Path(__file__).resolve().parent.parent / ".env"))
    p.add_argument("--compose", default=str(Path(__file__).resolve().parent.parent / "erpnext" / "docker-compose.yml"))
    a = p.parse_args()
    env = Path(a.env).read_text(encoding="utf-8")
    clave = re.search(r"^ERPNEXT_ADMIN_PASSWORD=(.+)$", env, re.M)
    if not clave:
        p.error("falta ERPNEXT_ADMIN_PASSWORD en el .env")
    # Los guiones de servidor vienen desactivados en ERPNext: se activan en la configuración común del sitio
    subprocess.run(["docker", "compose", "-f", a.compose, "--env-file", a.env, "exec", "-T", "backend", "bench", "set-config", "-g",
                    "server_script_enabled", "1"], check=True, capture_output=True)
    c = Cliente(a.url)
    if c.llamar("POST", "/api/method/login", {"usr": "Administrator", "pwd": clave.group(1)})[0] != 200:
        print("No se pudo entrar en ERPNext como Administrator")
        return 1
    creados = existentes = 0
    for doc in DOCUMENTOS:
        for evento, accion in EVENTOS.items():
            nombre = f"Cerebro: no {accion} {doc}"
            if c.llamar("GET", f"/api/resource/Server Script/{nombre}")[0] == 200:
                existentes += 1
                continue
            st, r = c.llamar("POST", "/api/resource/Server Script", {
                "name": nombre, "script_type": "DocType Event", "reference_doctype": doc, "doctype_event": evento,
                "disabled": 0, "script": SCRIPT.format(accion=accion)})
            if st >= 300:
                print(f"No se pudo crear «{nombre}»: {r}")
                return 1
            creados += 1
    print(f"Guiones de servidor: {creados} creados, {existentes} ya existían ({len(DOCUMENTOS)} documentos × {len(EVENTOS)} eventos)")
    print("Reiniciad backend y workers de ERPNext si es la primera vez (ver cabecera del script).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
