#!/usr/bin/env bash
# Gera os ícones das duas plataformas a partir de brand/icon.svg e brand/icon-small.svg (16–32 px) — rasteriza com o
# rsvg-convert (ou, sem ele, com o Google Chrome):
#   macos/AppIcon.icns · macos/MenuIcon.png (+@2x, barra de menus) · windows/Codeck/app.ico · brand/icon.png
# brand/logo.svg (só a marca, sem fundo) vai direto para o instalador do Windows: só <path> + gradiente, sem
# filtros — o ThomSoft Setup cai no logo de demonstração quando não consegue desenhar o SVG.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TMP="$(mktemp -d)"
shot() {   # shot <svg> <px> <png> — rsvg-convert (brew install librsvg) quando tem; senão o Chrome sem cabeça
  if command -v rsvg-convert >/dev/null; then rsvg-convert -w "$2" -h "$2" "$1" -o "$3"; return; fi
  printf '<html><head><style>html,body{margin:0;width:%spx;height:%spx;overflow:hidden;background:transparent}svg{display:block;width:100%%;height:100%%}</style></head><body>%s</body></html>' \
    "$2" "$2" "$(cat "$1")" > "$TMP/r.html"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --default-background-color=00000000 \
    --window-size="$2,$2" --screenshot="$3" "file://$TMP/r.html" >/dev/null 2>&1
}
shot "$ROOT/brand/icon.svg" 1024 "$TMP/icon.png"
shot "$ROOT/brand/icon-small.svg" 1024 "$TMP/small.png"
cp "$TMP/icon.png" "$ROOT/brand/icon.png"
# barra de menus do macOS: imagem "template" de 18 pt (o app marca isTemplate — o sistema pinta claro/escuro)
shot "$ROOT/brand/menubar.svg" 18 "$ROOT/macos/MenuIcon.png"
shot "$ROOT/brand/menubar.svg" 36 "$ROOT/macos/MenuIcon@2x.png"
mkdir -p "$TMP/AppIcon.iconset"
for s in 16 32 128 256 512; do
  src="$TMP/icon.png"; [ $s -le 32 ] && src="$TMP/small.png"   # 16/32 (e os @2x deles): a variante sem detalhe
  sips -z $s $s "$src" --out "$TMP/AppIcon.iconset/icon_${s}x${s}.png" >/dev/null
  src2="$TMP/icon.png"; [ $s -le 16 ] && src2="$TMP/small.png"
  sips -z $((s*2)) $((s*2)) "$src2" --out "$TMP/AppIcon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/AppIcon.iconset" -o "$ROOT/macos/AppIcon.icns"
# .ico no formato clássico: BMP 32 bits (com alfa) até 128 px e PNG só no de 256 — é o que o Explorer, a barra de
# tarefas e o System.Drawing.Icon leem sem surpresa (PNG em tamanho pequeno às vezes sai em branco ou é ignorado).
python3 - "$TMP/icon.png" "$ROOT/windows/Codeck/app.ico" "$TMP/small.png" <<'PY'
import os, struct, subprocess, sys, tempfile, zlib
src, dst, small = sys.argv[1], sys.argv[2], sys.argv[3]

def read_png(path):
    data = open(path, "rb").read()
    pos, w, h, idat, ctype = 8, 0, 0, b"", 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", chunk[:10])
            assert depth == 8 and ctype in (2, 6), "PNG precisa ser RGB/RGBA 8 bits"
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + n
    bpp = 4 if ctype == 6 else 3
    raw, stride, rows, prev = zlib.decompress(idat), w * bpp, [], bytearray(w * bpp)
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], prev[i - bpp] if i >= bpp else 0
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p_ = a + b - c; pa, pb, pc = abs(p_ - a), abs(p_ - b), abs(p_ - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line if bpp == 4 else bytearray(v for i in range(w) for v in (*line[i*3:i*3+3], 255)))
        prev = line
    return w, h, rows

def bmp_entry(w, h, rows):
    head = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = b"".join(bytes(v for i in range(w) for v in (r[i*4+2], r[i*4+1], r[i*4], r[i*4+3])) for r in reversed(rows))
    mask_row = ((w + 31) // 32) * 4
    return head + pixels + b"\0" * (mask_row * h)

sizes, entries = [16, 20, 24, 32, 40, 48, 64, 128, 256], []
with tempfile.TemporaryDirectory() as d:
    for s in sizes:
        out = os.path.join(d, f"{s}.png")
        # até 32 px (bandeja, Explorer em lista): a variante sem detalhe, que não vira borrão
        subprocess.run(["sips", "-z", str(s), str(s), small if s <= 32 else src, "--out", out], check=True, capture_output=True)
        entries.append(open(out, "rb").read() if s == 256 else bmp_entry(*read_png(out)))
off, dirs = 6 + 16 * len(sizes), b""
for s, data in zip(sizes, entries):
    dirs += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), off)
    off += len(data)
open(dst, "wb").write(struct.pack("<HHH", 0, 1, len(sizes)) + dirs + b"".join(entries))
PY
rm -rf "$TMP"
echo "✓ macos/AppIcon.icns, macos/MenuIcon(@2x).png, windows/Codeck/app.ico, brand/icon.png"
