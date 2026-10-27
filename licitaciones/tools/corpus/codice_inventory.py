"""Inventario de rutas y resumen por entrada de un feed ATOM/CODICE de PLACSP.

Uso:  python3 -I codice_inventory.py FICHERO.atom [--entries] [--paths] [--json SALIDA]

--entries  una línea por entrada: id, estado, nº lotes, resultados, adjudicatarios, ofertas
--paths    cobertura: en cuántas entradas aparece cada ruta (relativa a la entrada)
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safexml import iterparse_safe, short  # noqa: E402

ATOM = "{http://www.w3.org/2005/Atom}"
TOMB = "{http://purl.org/atompub/tombstones/1.0}"


def summarize(entry):
    """Resumen de una entrada <entry> ya construida."""
    def first(path):
        for el in entry.iter():
            if short(el.tag) == path:
                return (el.text or "").strip()
        return None

    def all_(path):
        return [(el.text or "").strip() for el in entry.iter() if short(el.tag) == path]

    results = []
    for tr in entry.iter():
        if short(tr.tag) != "cac:TenderResult":
            continue
        r = {}
        for el in tr.iter():
            t = short(el.tag)
            if t in ("cbc:ResultCode", "cbc:AwardDate", "cbc:ReceivedTenderQuantity",
                     "cbc:LowerTenderAmount", "cbc:HigherTenderAmount", "cbc:SMEAwardedIndicator",
                     "cbc:AbnormallyLowTendersIndicator"):
                r.setdefault(t.split(":")[1], (el.text or "").strip())
        names = [(el.text or "").strip() for el in tr.iter() if short(el.tag) == "cbc:Name"]
        ids = [(el.text or "").strip() for el in tr.iter() if short(el.tag) == "cbc:ID"]
        r["names"] = names
        r["ids"] = ids
        results.append(r)
    return {
        "id": first("atom:id"),
        "updated": first("atom:updated"),
        "folder": first("cbc:ContractFolderID"),
        "status": first("cbc-place-ext:ContractFolderStatusCode"),
        "type": first("cbc:TypeCode"),
        "lots": len([e for e in entry.iter() if short(e.tag) == "cac:ProcurementProjectLot"]),
        "notices": all_("cbc:NoticeTypeCode"),
        "party": first("cbc:Name"),
        "cpv": all_("cbc:ItemClassificationCode")[:3],
        "results": results,
        "bytes": len(__import__("xml.etree.ElementTree", fromlist=["x"]).tostring(entry)),
    }


def paths_of(entry):
    out = set()

    def walk(el, prefix):
        p = f"{prefix}/{short(el.tag)}" if prefix else short(el.tag)
        out.add(p)
        for k in el.attrib:
            out.add(f"{p}/@{k}")
        for c in el:
            walk(c, p)

    for c in entry:
        walk(c, "")
    return out


def run(path, want_entries, want_paths):
    entries, deleted = [], []
    cov = Counter()
    stack = []
    for ev, el in iterparse_safe(path):
        if ev == "start":
            stack.append(el)
            continue
        stack.pop()
        if el.tag == ATOM + "entry" and len(stack) == 1:
            entries.append(summarize(el))
            cov.update(paths_of(el))
            el.clear()
        elif el.tag == TOMB + "deleted-entry" and len(stack) == 1:
            c = el.find(TOMB + "comment")
            deleted.append({"ref": el.get("ref"), "when": el.get("when"),
                            "comment": None if c is None else c.get("type")})
            el.clear()
    return entries, deleted, cov


def main():
    args = sys.argv[1:]
    path = args[0]
    entries, deleted, cov = run(path, "--entries" in args, "--paths" in args)
    print(f"# {path}: {len(entries)} entradas, {len(deleted)} borradas")
    print("# estados:", dict(Counter(e["status"] for e in entries)))
    print("# borradas:", dict(Counter(d["comment"] for d in deleted)))
    if "--entries" in args:
        for e in entries:
            res = ";".join(f"{r.get('ResultCode')}|ofertas={r.get('ReceivedTenderQuantity')}|{r['names'][:2]}"
                           for r in e["results"])
            print(f"{e['id'].rsplit('/', 1)[-1]}\t{e['status']}\tlotes={e['lots']}\t{e['notices']}\t{e['bytes']}B\t{res[:200]}")
    if "--paths" in args:
        n = len(entries)
        for p, c in sorted(cov.items()):
            print(f"{c}/{n}\t{p}")
    if "--json" in args:
        out = args[args.index("--json") + 1]
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"entries": entries, "deleted": deleted, "paths": cov}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
