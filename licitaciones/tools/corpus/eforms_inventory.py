"""Inventario de rutas de anuncios eForms (TED) con su cobertura y valores de tipo código.

Para cada fichero XML (un anuncio eForms) calcula el conjunto de rutas (desde la raíz, con prefijos
cortos) y atributos; luego muestra en cuántos anuncios aparece cada ruta, separando por elemento raíz
(ContractNotice, ContractAwardNotice, PriorInformationNotice). En las rutas con pocos valores
distintos, lista los valores (útil para schemeName, listName, códigos).

Las extensiones eForms (`ext:UBLExtensions/.../efext:EformsExtension/...`) se muestran con el
prefijo `EXT/` para acortar.

Uso: python3 -I eforms_inventory.py [--max-distinct N] [--grep TEXTO] FICHERO.xml [...]
"""
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safexml import iterparse_safe, short  # noqa: E402

EXT_PREFIX = "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/efext:EformsExtension"


def paths(path):
    stack, out, vals = [], set(), defaultdict(Counter)
    root = None
    for ev, el in iterparse_safe(path):
        if ev == "start":
            stack.append(short(el.tag))
            if root is None:
                root = stack[0].split(":")[-1]
            continue
        p = "/".join(stack[1:]).replace(EXT_PREFIX, "EXT")
        p = p.replace("/" + EXT_PREFIX, "/EXT")
        out.add(p)
        txt = (el.text or "").strip()
        if txt:
            vals[p][txt[:60]] += 1
        for k, v in el.attrib.items():
            k = k.split("}")[-1]
            out.add(f"{p}/@{k}")
            vals[f"{p}/@{k}"][v[:60]] += 1
        stack.pop()
    return root, out, vals


def main():
    args = sys.argv[1:]
    maxd, grep = 12, None
    if "--max-distinct" in args:
        i = args.index("--max-distinct")
        maxd = int(args[i + 1])
        del args[i:i + 2]
    if "--grep" in args:
        i = args.index("--grep")
        grep = args[i + 1]
        del args[i:i + 2]
    by_root = defaultdict(list)
    allvals = defaultdict(Counter)
    for f in args:
        root, ps, vals = paths(f)
        by_root[root].append(ps)
        for k, c in vals.items():
            allvals[k].update(c)
    roots = sorted(by_root)
    print("# " + "  ".join(f"{r}: n={len(by_root[r])}" for r in roots))
    every = set().union(*(s for r in roots for s in by_root[r]))
    for p in sorted(every):
        if grep and grep not in p:
            continue
        cov = "\t".join(f"{sum(1 for s in by_root[r] if p in s)}/{len(by_root[r])}" for r in roots)
        c = allvals.get(p)
        v = ""
        if c:
            v = ("; ".join(f"{x}×{n}" for x, n in c.most_common()) if len(c) <= maxd
                 else f"[{len(c)} valores; ej. {next(iter(c))!r}]")
        print(f"{cov}\t{p}\t{v}")


if __name__ == "__main__":
    main()
