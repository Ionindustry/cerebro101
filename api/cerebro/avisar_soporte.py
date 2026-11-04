"""Avisa por correo a soporte@ de un fallo del sistema que ocurre FUERA de los contenedores (p. ej. la copia de seguridad nocturna, que se lanza desde el servidor).

    docker compose exec -T api python -m cerebro.avisar_soporte "Asunto" "Cuerpo del aviso"

Usa el buzón y los destinatarios de siempre (config/licitaciones.yaml → vigilante.destinatarios; buzón de config/buzones.yaml → avisos): las mismas direcciones que los fallos del motor.
Sale con código 0 si se envió a todos, 1 si no. Es un mensaje automático: no lee nada ni acepta órdenes."""
from __future__ import annotations

import sys

from .licitaciones import vigilante


def avisar(asunto: str, cuerpo: str, enviar=None, cfg: dict | None = None) -> tuple[int, int]:
    """(enviados, fallidos). Asunto y cuerpo se recortan: es texto que viene de un script."""
    destinatarios = vigilante.configuracion(cfg)["destinatarios"]
    if not destinatarios:
        return 0, 0
    asunto = " ".join(str(asunto).split())[:150] or "Aviso del Cerebro"
    return vigilante._enviar_a(destinatarios, asunto, str(cuerpo)[:4000] + "\n\nMensaje automático del Cerebro.", enviar)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Uso: python -m cerebro.avisar_soporte \"Asunto\" \"Cuerpo\"", file=sys.stderr)
        return 2
    ok, mal = avisar(argv[0], argv[1] if len(argv) > 1 else "")
    print(f"avisos enviados: {ok}; fallidos: {mal}")
    return 0 if ok and not mal else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
