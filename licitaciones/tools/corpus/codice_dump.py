"""Vuelca una o varias entradas de un feed ATOM/CODICE como «ruta = valor [atributos]».

Uso: python3 -I codice_dump.py FICHERO.atom ID_NUMERICO [ID ...] [--no-docs]
(ID_NUMERICO = último segmento de <id> de la entrada).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safexml import iterparse_safe, short  # noqa: E402

ATOM = "{http://www.w3.org/2005/Atom}"
DOCS = ("DocumentReference", "GeneralDocument", "TenderingTerms/cac:TendererQualificationRequest",
        "ContractExecutionRequirement", "LocatedContractingParty/cac-place-ext:ParentLocatedParty/cac-place-ext:ParentLocatedParty")


def dump(el, prefix, out, nodocs):
    p = f"{prefix}/{short(el.tag)}" if prefix else short(el.tag)
    p = p.replace("cac-place-ext:ContractFolderStatus", "CFS")
    if nodocs and any(d in p for d in DOCS):
        return
    txt = (el.text or "").strip()
    attrs = " ".join(f"@{k.split('}')[-1]}={v}" for k, v in el.attrib.items() if not k.endswith("listURI"))
    if txt or attrs:
        out.append(f"{p} = {txt[:120]!r} {attrs}".rstrip())
    for c in el:
        dump(c, p, out, nodocs)


def main():
    path, *ids = sys.argv[1:]
    nodocs = "--no-docs" in ids
    ids = {i for i in ids if not i.startswith("--")}
    depth = 0
    for ev, el in iterparse_safe(path):
        if ev == "start":
            depth += 1
            continue
        depth -= 1
        if el.tag == ATOM + "entry" and depth == 1:
            eid = (el.findtext(ATOM + "id") or "").rsplit("/", 1)[-1]
            if eid in ids:
                out = []
                for c in el:
                    dump(c, "", out, nodocs)
                print(f"===== {eid}")
                print("\n".join(out))
            el.clear()


if __name__ == "__main__":
    main()
