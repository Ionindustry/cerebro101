"""Recorta una página ATOM (PLACSP) a unas pocas entradas, conservando sus bytes EXACTOS.

El resultado es un feed válido: la cabecera original del <feed> (espacios de nombres, <link rel="next">,
<updated>...) hasta la primera entrada, las entradas elegidas copiadas byte a byte, y el cierre </feed>.
Así cada <entry> del extracto tiene el mismo contenido que en la página original y se puede comprobar
contra ella (se imprime el SHA-256 de cada fragmento <entry>…</entry>).

Las posiciones se obtienen con expat (CurrentByteIndex), sin DTD ni entidades (safexml.check_bytes).

Uso: python3 -I atom_extract.py PAGINA.atom SALIDA.atom ID_NUMERICO [ID ...]
     (ID_NUMERICO = último segmento de <id> de la entrada; «tomb:N» copia las N primeras <at:deleted-entry>)
"""
import hashlib
import os
import sys
import xml.parsers.expat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safexml import HostileXML, check_bytes  # noqa: E402

ATOM_NS = "http://www.w3.org/2005/Atom"
TOMB_NS = "http://purl.org/atompub/tombstones/1.0"


def spans(data):
    """Devuelve [(tipo, id, inicio, fin)] de cada hijo directo <entry>/<at:deleted-entry> del feed."""
    check_bytes(data)
    p = xml.parsers.expat.ParserCreate(namespace_separator=" ")
    out, state = [], {"depth": 0, "start": None, "kind": None, "in_id": False, "id": ""}

    def no_dtd(*_a, **_k):
        raise HostileXML("DOCTYPE no permitido")

    p.StartDoctypeDeclHandler = no_dtd
    p.EntityDeclHandler = no_dtd
    p.ExternalEntityRefHandler = lambda *a: False

    def start(name, attrs):
        state["depth"] += 1
        d = state["depth"]
        if d == 2 and name in (f"{ATOM_NS} entry", f"{TOMB_NS} deleted-entry"):
            state.update(start=p.CurrentByteIndex, kind=name.split(" ")[1], id=attrs.get("ref", ""))
        if d == 3 and state["kind"] == "entry" and name == f"{ATOM_NS} id":
            state["in_id"] = True

    def end(name):
        d = state["depth"]
        state["depth"] -= 1
        if d == 3:
            state["in_id"] = False
        if d == 2 and state["start"] is not None:
            # CurrentByteIndex apunta al inicio de la etiqueta de cierre
            close = data.index(b">", p.CurrentByteIndex) + 1
            out.append((state["kind"], state["id"].rsplit("/", 1)[-1], state["start"], close))
            state["start"] = None

    def chars(t):
        if state["in_id"]:
            state["id"] += t

    p.StartElementHandler = start
    p.EndElementHandler = end
    p.CharacterDataHandler = chars
    p.Parse(data, True)
    return out


def main():
    src, dst, *wanted = sys.argv[1:]
    data = open(src, "rb").read()
    sp = spans(data)
    if not sp:
        sys.exit("sin entradas")
    head = data[:sp[0][2]]
    tail_start = data.rindex(b"</feed>")
    ntomb = 0
    for w in wanted:
        if w.startswith("tomb:"):
            ntomb = int(w[5:])
    ids = [w for w in wanted if not w.startswith("tomb:")]
    chosen = []
    for kind, eid, a, b in sp:
        if kind == "entry" and eid in ids:
            chosen.append((kind, eid, a, b))
        elif kind == "deleted-entry" and ntomb > 0:
            chosen.append((kind, eid, a, b))
            ntomb -= 1
    missing = set(ids) - {e for k, e, _, _ in chosen if k == "entry"}
    if missing:
        sys.exit(f"no encontradas: {sorted(missing)}")
    with open(dst, "wb") as o:
        o.write(head)
        for kind, eid, a, b in chosen:
            frag = data[a:b]
            o.write(frag)
            o.write(b"\n    ")
            print(f"{kind}\t{eid}\t{len(frag)}B\tsha256={hashlib.sha256(frag).hexdigest()}")
        o.write(data[tail_start:])
    print(f"extracto: {len(chosen)} de {len(sp)} elementos; origen sha256={hashlib.sha256(data).hexdigest()}")


if __name__ == "__main__":
    main()
