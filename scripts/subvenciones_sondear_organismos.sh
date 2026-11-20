#!/usr/bin/env bash
# Sondea, con el servidor REAL, qué ofrece cada organismo español de ayudas (autonómicos y nacionales) para poder escribir sus conectores con datos reales y no con suposiciones.
# SOLO LECTURA: peticiones públicas (GET) sin claves ni datos de la empresa. Las direcciones son CANDIDATAS: que alguna falle también es información útil.
#
# Uso:  ./scripts/subvenciones_sondear_organismos.sh
# Resultado: un resumen corto (código HTTP, título, canales RSS/API y enlaces de convocatorias de cada web) y los ficheros completos en  subvenciones_muestras/organismos/
# Copia y pega ese resumen (solo eso) en el chat. Son datos públicos.
set -uo pipefail
cd "$(dirname "$0")/.."
command -v python3 >/dev/null || { echo "Hace falta python3 (viene con Ubuntu)." >&2; exit 1; }
SALIDA="subvenciones_muestras/organismos"
mkdir -p "$SALIDA"
export SALIDA
python3 - <<'PY'
import json, os, re, sys, urllib.parse, urllib.request, urllib.error
SALIDA = os.environ["SALIDA"]
UA = "ARES-FundingIntelligence/1.0 (+https://101.cat)"

def get(nombre, url, accept="*/*", maximo=400_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            datos, codigo, tipo = r.read(maximo), r.status, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        datos, codigo, tipo = e.read(2000) if hasattr(e, "read") else b"", e.code, ""
    except Exception as e:                      # noqa: BLE001
        datos, codigo, tipo = str(e).encode(), "sin_respuesta", ""
    open(os.path.join(SALIDA, nombre + ".txt"), "wb").write(datos)
    return codigo, tipo, datos.decode("utf-8", "replace")

def corto(t, n=300):
    return re.sub(r"\s+", " ", str(t))[:n]

def texto(v):
    """Un valor de la respuesta de datos.gob.es como texto: puede ser cadena, {_value: ...}, {value: ...}, {_about: ...} o una lista de esas cosas (se prefiere el castellano)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        elegidos = [x for x in v if isinstance(x, dict) and x.get("_lang") == "es"] or v
        return texto(elegidos[0]) if elegidos else ""
    if isinstance(v, dict):
        for k in ("_value", "value", "_about", "label", "name", "title"):
            if v.get(k):
                return texto(v[k])
        return ""
    return str(v)

print("=== 1. Catálogo nacional datos.gob.es: conjuntos de datos de subvenciones/ayudas/convocatorias ===")
for termino in ("subvenciones", "convocatorias", "ayudas"):
    c, t, cuerpo = get(f"catalogo_{termino}", f"https://datos.gob.es/apidata/catalog/dataset/title/{urllib.parse.quote(termino)}?_pageSize=30&_page=0&_sort=-issued", "application/json")
    print(f"── catálogo «{termino}» → HTTP {c} · {len(cuerpo)} bytes")
    try:
        items = json.loads(cuerpo)["result"]["items"]
    except Exception:                           # noqa: BLE001
        print("   (sin lista interpretable)", corto(cuerpo, 200)); continue
    if items:
        print("   (estructura del primer elemento:", corto(json.dumps(items[0], ensure_ascii=False), 700), ")")
    for it in items[:30]:
        try:
            dist = it.get("distribution") if isinstance(it, dict) else None
            dist = dist if isinstance(dist, list) else ([dist] if dist else [])
            formatos = sorted({texto(d.get("format")) for d in dist if isinstance(d, dict) and d.get("format")} - {""})
            url = next((texto(d.get("accessURL")) for d in dist if isinstance(d, dict) and d.get("accessURL")), "") or next((d for d in dist if isinstance(d, str)), "")
            print(f"   · {corto(texto(it.get('title')), 90)} | {','.join(formatos)} | {url} | {corto(texto(it.get('publisher')), 40)}")
        except Exception as e:          # noqa: BLE001
            print("   · (elemento no interpretable)", type(e).__name__, corto(json.dumps(it, ensure_ascii=False)[:160]))

print()
print("=== 2. Webs de organismos: título, canales RSS/API y enlaces de convocatorias ===")
WEBS = {
    "jcyl_opendata": "https://datosabiertos.jcyl.es/",
    "jcyl_api_catalogo": "https://analisis.datosabiertos.jcyl.es/api/explore/v2.1/catalog/datasets?where=search(title,%22subvenciones%22)&limit=10",
    "euskadi_opendata": "https://opendata.euskadi.eus/",
    "aragon_opendata": "https://opendata.aragon.es/",
    "cidoDiba": "https://cido.diba.cat/",
    "cdti": "https://www.cdti.es/",
    "idae": "https://www.idae.es/ayudas-y-financiacion",
    "icex": "https://www.icex.es/",
    "redes": "https://www.red.es/es/ayudas",
    "enisa": "https://www.enisa.es/",
    "plataformapyme": "https://plataformapyme.es/",
}
RE_ENLACE = re.compile(r'<a\s[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', re.I | re.S)
for nombre, url in WEBS.items():
    c, t, cuerpo = get(nombre, url, "text/html,application/json")
    titulo = re.search(r"<title[^>]*>(.*?)</title>", cuerpo, re.I | re.S)
    print(f"── {nombre} → HTTP {c} · {t.split(';')[0]} · {len(cuerpo)} bytes · {corto(titulo.group(1), 80) if titulo else ''}")
    if "json" in t:
        print("   ", corto(cuerpo, 500)); continue
    feeds = sorted(set(re.findall(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]*href="([^"]+)"', cuerpo, re.I)))[:4]
    if feeds:
        print("   RSS/Atom:", " | ".join(urllib.parse.urljoin(url, f) for f in feeds))
    apis = sorted(set(re.findall(r'href="([^"]*(?:/api|ckan|opendatasoft|sparql|\.csv|\.json|\.xml)[^"]*)"', cuerpo, re.I)))[:5]
    if apis:
        print("   Posible API/descargas:", " | ".join(urllib.parse.urljoin(url, a) for a in apis))
    vistos = set()
    for href, texto in RE_ENLACE.findall(cuerpo):
        txt = corto(re.sub(r"<[^>]+>", " ", texto), 70)
        if re.search(r"convocatoria|ayuda|subvenci|financiaci|pr[eé]stamo", txt, re.I) and href not in vistos and len(vistos) < 6:
            vistos.add(href)
            print(f"   · {txt} → {urllib.parse.urljoin(url, href)}")
print()
print(f"Muestras completas en {os.getcwd()}/{SALIDA}/. Pega solo este resumen en el chat (son datos públicos).")
PY
