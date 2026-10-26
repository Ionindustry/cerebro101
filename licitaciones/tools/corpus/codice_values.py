"""Valores observados por ruta en uno o varios feeds ATOM/CODICE (para el inventario de campos).

Para cada ruta (relativa a la entrada) cuenta sus valores de texto y de atributos. Solo muestra las rutas
«de tipo código» (pocas variantes distintas): esquemas de identificadores, códigos de resultado, de
procedimiento, de estado, unidades, etc. Las rutas con muchos valores (nombres, importes) se resumen
con el número de valores distintos y un ejemplo.

Uso: python3 -I codice_values.py [--max-distinct N] FICHERO.atom [...]
"""
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safexml import iterparse_safe, short  # noqa: E402

ATOM = "{http://www.w3.org/2005/Atom}"
TOMB = "{http://purl.org/atompub/tombstones/1.0}"
CAP = 200  # valores distintos máximos que se guardan por ruta


def walk(el, prefix, vals):
    p = f"{prefix}/{short(el.tag)}" if prefix else short(el.tag)
    p = p.replace("cac-place-ext:ContractFolderStatus", "CFS")
    txt = (el.text or "").strip()
    if txt:
        c = vals[p]
        if len(c) < CAP or txt in c:
            c[txt] += 1
    for k, v in el.attrib.items():
        k = k.split("}")[-1]
        if k == "listURI":
            continue
        c = vals[f"{p}/@{k}"]
        if len(c) < CAP or v in c:
            c[v] += 1
    for ch in el:
        walk(ch, p, vals)


def main():
    args = sys.argv[1:]
    maxd = 25
    if "--max-distinct" in args:
        i = args.index("--max-distinct")
        maxd = int(args[i + 1])
        del args[i:i + 2]
    vals = defaultdict(Counter)
    tomb = Counter()
    n = 0
    for path in args:
        depth = 0
        for ev, el in iterparse_safe(path):
            if ev == "start":
                depth += 1
                continue
            depth -= 1
            if depth == 1 and el.tag == ATOM + "entry":
                n += 1
                for ch in el:
                    if short(ch.tag) in ("atom:id", "atom:title", "atom:summary", "atom:updated"):
                        continue
                    walk(ch, "", vals)
                el.clear()
            elif depth == 1 and el.tag == TOMB + "deleted-entry":
                c = el.find(TOMB + "comment")
                tomb[None if c is None else c.get("type")] += 1
                el.clear()
    print(f"# entradas={n} borradas={dict(tomb)}")
    for p in sorted(vals):
        c = vals[p]
        if len(c) <= maxd:
            print(f"{p}\t" + "; ".join(f"{v[:60]}×{k}" for v, k in c.most_common()))
        else:
            ex = next(iter(c))
            print(f"{p}\t[{'≥' if len(c) >= CAP else ''}{len(c)} valores distintos; ej.: {ex[:60]!r}]")


if __name__ == "__main__":
    main()
