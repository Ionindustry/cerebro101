"""Lectura en streaming de un ZIP por sus cabeceras locales (sin directorio central).

Sirve también con un ZIP truncado (descarga incompleta): extrae las entradas completas
que haya. Límites contra bombas ZIP y nombres saneados (sin zip slip).

Uso:
  python3 -I zip_stream.py ZIP --list
  python3 -I zip_stream.py ZIP --extract DESTINO [NOMBRE ...]   (sin nombres: todas)
"""
import os
import re
import struct
import sys
import zlib

MAX_ENTRY = 512 * 1024 * 1024    # tamaño descomprimido máximo por entrada
MAX_RATIO = 200                  # descomprimido/comprimido máximo
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,200}$")
LFH = b"PK\x03\x04"


def entries(f):
    """Genera (nombre, datos) de cada entrada completa leyendo en secuencia."""
    while True:
        sig = f.read(4)
        if sig != LFH:
            return  # directorio central, fin o truncado
        hdr = f.read(26)
        if len(hdr) < 26:
            return
        (_ver, flags, method, _t, _d, _crc, csize, usize, nlen, xlen) = struct.unpack("<HHHHHIIIHH", hdr)
        name = f.read(nlen).decode("utf-8", "replace")
        f.read(xlen)
        if method not in (0, 8):
            raise ValueError(f"{name}: método {method} no admitido")
        if flags & 0x08 or csize == 0xFFFFFFFF:
            # tamaño desconocido: descomprimir hasta fin de flujo deflate
            if method != 8:
                raise ValueError(f"{name}: data descriptor sin deflate")
            d = zlib.decompressobj(-15)
            out, consumed = [], 0
            total = 0
            while not d.eof:
                chunk = f.read(65536)
                if not chunk:
                    return  # truncado
                consumed += len(chunk)
                piece = d.decompress(chunk, MAX_ENTRY - total + 1)
                total += len(piece)
                if total > MAX_ENTRY:
                    raise ValueError(f"{name}: supera {MAX_ENTRY} bytes")
                out.append(piece)
            # rebobinar lo leído de más y saltar el data descriptor
            extra = len(d.unused_data)
            f.seek(-extra, os.SEEK_CUR)
            dd = f.read(4)
            if dd == b"PK\x07\x08":
                f.read(12)
            else:
                f.read(8)
            data = b"".join(out)
        else:
            comp = f.read(csize)
            if len(comp) < csize:
                return  # truncado
            if usize > MAX_ENTRY or (csize and usize / csize > MAX_RATIO):
                raise ValueError(f"{name}: tamaño/ratio sospechoso ({csize}->{usize})")
            data = comp if method == 0 else zlib.decompress(comp, -15, bufsize=max(usize, 1))
            if len(data) != usize:
                raise ValueError(f"{name}: tamaño descomprimido inesperado")
        yield name, data


def main():
    path = sys.argv[1]
    with open(path, "rb") as f:
        if "--list" in sys.argv:
            for name, data in entries(f):
                print(f"{len(data)}\t{name}")
        elif "--extract" in sys.argv:
            i = sys.argv.index("--extract")
            dest = sys.argv[i + 1]
            wanted = set(sys.argv[i + 2:])
            os.makedirs(dest, exist_ok=True)
            for name, data in entries(f):
                base = os.path.basename(name)
                if not SAFE_NAME.match(base):
                    print(f"omitido (nombre no seguro): {name!r}", file=sys.stderr)
                    continue
                if wanted and base not in wanted:
                    continue
                with open(os.path.join(dest, base), "wb") as o:
                    o.write(data)
                print(f"{len(data)}\t{base}")


if __name__ == "__main__":
    main()
