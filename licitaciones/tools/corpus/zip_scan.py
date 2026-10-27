"""Recorre un ZIP mensual de PLACSP (o ficheros .atom sueltos) y mide estados, resultados
y cobertura de campos de adjudicación; propone entradas candidatas para el corpus.

Uso: python3 -I zip_scan.py SALIDA.json FICHERO.zip|FICHERO.atom [...]
"""
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safexml import iterparse_bytes, short  # noqa: E402
from zip_stream import entries as zip_entries  # noqa: E402

ATOM = "{http://www.w3.org/2005/Atom}"
TOMB = "{http://purl.org/atompub/tombstones/1.0}"
# CPV decididos por Dirección el 26/10/2026 (§12.1 del proyecto). Se compara por prefijo (CPV sin
# ceros finales), así un CPV hijo de uno de la lista también cuenta (propuesta de jerarquía, por validar).
OUR_CPV_LIST = ("72000000", "72200000", "72230000", "72262000", "72267000", "32323500", "32235000",
                "32234000", "35125300", "35120000", "34970000", "34923000", "34971000", "34972000",
                "63712710", "45316210", "42961000", "42961100", "32420000", "32441100")
OUR_CPV = tuple(sorted({c.rstrip("0") for c in OUR_CPV_LIST}))

TR_FIELDS = [
    "cbc:ResultCode", "cbc:AwardDate", "cbc:ReceivedTenderQuantity", "cbc:LowerTenderAmount",
    "cbc:HigherTenderAmount", "cbc:AbnormallyLowTendersIndicator", "cbc:StartDate",
    "cbc:SMEAwardedIndicator", "cbc:SMEsReceivedTenderQuantity", "cbc:Description",
    "cac:WinningParty/cac:PartyIdentification/cbc:ID", "cac:WinningParty/cac:PartyName/cbc:Name",
    "cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount",
    "cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:PayableAmount",
    "cac:AwardedTenderedProject/cbc:ProcurementProjectLotID",
    "cac:Contract/cbc:ID", "cac:Contract/cbc:IssueDate",
]


def rel_paths(el, prefix=""):
    for c in el:
        p = f"{prefix}/{short(c.tag)}" if prefix else short(c.tag)
        yield p, c
        yield from rel_paths(c, p)


def features(entry):
    f = {"id": (entry.findtext(ATOM + "id") or "").rsplit("/", 1)[-1],
         "updated": entry.findtext(ATOM + "updated")}
    notices, results, regions, cpvs = [], [], set(), set()
    lots = 0
    tr_cov = []
    flags = set()
    for p, el in rel_paths(entry):
        t = short(el.tag)
        txt = (el.text or "").strip()
        if t == "cbc-place-ext:ContractFolderStatusCode":
            f["status"] = txt
        elif t == "cbc-place-ext:NoticeTypeCode":
            notices.append(txt)
        elif t == "cbc:CountrySubentityCode" and "RealizedLocation" in p:
            regions.add(txt)
        elif t == "cbc:ItemClassificationCode":
            cpvs.add(txt)
        elif t == "cac:ProcurementProjectLot":
            lots += 1
        elif t == "cac:ContractModification":
            flags.add("modificacion")
        elif t == "cac:TenderResult":
            sub = {sp for sp, _ in rel_paths(el)}
            vals = {short(x.tag): (x.text or "").strip() for x in el}
            results.append(vals.get("cbc:ResultCode"))
            tr_cov.append({k: (k in sub) for k in TR_FIELDS})
            if vals.get("cbc:AbnormallyLowTendersIndicator") == "true":
                flags.add("baja_anormal")
            for x in el.iter():
                if short(x.tag) == "cbc:ID" and x.get("schemeName") == "UTE":
                    flags.add("ute")
    f.update(notices=notices, results=results, lots=lots, regions=sorted(regions), tr_cov=tr_cov,
             flags=sorted(flags), our_cpv=any(c.startswith(OUR_CPV) for c in cpvs))
    return f


def scan_bytes(name, data, acc):
    depth = 0
    for ev, el in iterparse_bytes(data):
        if ev == "start":
            depth += 1
            continue
        depth -= 1
        if depth == 1 and el.tag == ATOM + "entry":
            f = features(el)
            f["file"] = name
            acc["entries"].append(f)
            el.clear()
        elif depth == 1 and el.tag == TOMB + "deleted-entry":
            c = el.find(TOMB + "comment")
            acc["deleted"][None if c is None else c.get("type")] += 1
            el.clear()
    acc["files"] += 1


def main():
    out, *inputs = sys.argv[1:]
    acc = {"entries": [], "deleted": Counter(), "files": 0}
    for path in inputs:
        if path.endswith(".zip"):
            with open(path, "rb") as fh:
                for name, data in zip_entries(fh):
                    scan_bytes(name, data, acc)
        else:
            with open(path, "rb") as fh:
                scan_bytes(os.path.basename(path), fh.read(), acc)
    E = acc["entries"]
    print(f"ficheros={acc['files']} entradas={len(E)} borradas={dict(acc['deleted'])}")
    print("estados:", Counter(e.get("status") for e in E).most_common())
    print("resultados (por TenderResult):", Counter(r for e in E for r in e["results"]).most_common())
    print("anuncios:", Counter(n for e in E for n in e["notices"]).most_common())
    print("flags:", Counter(x for e in E for x in e["flags"]).most_common())
    print("con lotes:", sum(1 for e in E if e["lots"]), " CPV propios:", sum(1 for e in E if e["our_cpv"]),
          " Cataluña (ES51*):", sum(1 for e in E if any(r.startswith("ES51") for r in e["regions"])))
    ids = Counter(e["id"] for e in E)
    print("ids repetidos (misma licitación en varias entradas):", sum(1 for v in ids.values() if v > 1),
          "de", len(ids))
    # cobertura de campos de TenderResult por código de resultado
    cov = defaultdict(Counter)
    tot = Counter()
    for e in E:
        for r, c in zip(e["results"], e["tr_cov"]):
            tot[r] += 1
            for k, v in c.items():
                if v:
                    cov[r][k] += 1
    print("\ncobertura de campos de TenderResult por ResultCode:")
    codes = sorted(tot, key=lambda x: (x is None, x))
    print("campo\t" + "\t".join(f"RC{c}(n={tot[c]})" for c in codes))
    for k in TR_FIELDS:
        print(k + "\t" + "\t".join(str(cov[c][k]) for c in codes))
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"entries": E, "deleted": acc["deleted"]}, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()
