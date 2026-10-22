#!/usr/bin/env python3
"""Gera a marca do Codeck a partir de um desenho só:

    brand/logo.svg        marca com gradiente, sem fundo (instalador do Windows, site)
    brand/icon.svg        ícone do app (macOS/Windows, 48 px para cima)
    brand/icon-small.svg  ícone para 16–32 px (bandeja do Windows, Finder em lista): sem os cartões de trás, traço mais grosso
    brand/menubar.svg     glifo monocromático da barra de menus do macOS (imagem "template": o sistema pinta)
    ui/public/favicon.svg a marca na aba do navegador
    ui/src/components/Mark.svelte  a marca dentro do app

A marca: um deck de cartões — cada cartão é um provedor (GitHub, Azure DevOps…) — e, no da frente, um grafo do git que
desenha o "C": a branch sai de um commit (embaixo), contorna e volta num merge (o anel verde, em cima).
Tudo sai como <path> PREENCHIDO de polígonos (traços e círculos viram contorno aqui): o ThomSoft Setup desenha o logo
com um renderizador que não aceita filtros e é instável com stroke, e quando falha mostra o logo de demonstração.

    python3 brand/make-logo.py && bash brand/make-icons.sh
"""
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def circle(cx, cy, r, n=96):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def rrect(x, y, w, h, r, n=16):
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def rotate(poly, deg, cx, cy, dx=0, dy=0):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(cx + (x - cx) * c - (y - cy) * s + dx, cy + (x - cx) * s + (y - cy) * c + dy) for x, y in poly]


def arc_band(cx, cy, r, w, a0, a1, n=120):
    """Faixa em arco (de a0 a a1 graus, horário na tela) com as pontas arredondadas."""
    ang = [math.radians(a0 + (a1 - a0) * i / n) for i in range(n + 1)]
    outer = [(cx + (r + w / 2) * math.cos(a), cy + (r + w / 2) * math.sin(a)) for a in ang]
    inner = [(cx + (r - w / 2) * math.cos(a), cy + (r - w / 2) * math.sin(a)) for a in ang][::-1]

    def cap(a, sign):   # meia-volta em torno da ponta, de fora para dentro
        px, py = cx + r * math.cos(a), cy + r * math.sin(a)
        return [(px + w / 2 * math.cos(a + sign * math.pi * i / 16), py + w / 2 * math.sin(a + sign * math.pi * i / 16)) for i in range(1, 16)]
    return outer + cap(ang[-1], 1) + inner + cap(ang[0], 1)


def polar(cx, cy, r, deg):
    return cx + r * math.cos(math.radians(deg)), cy + r * math.sin(math.radians(deg))


# ------------------------------------------------------------------ o desenho (unidades de 512)
CARD = (106, 92, 300, 352, 66)          # x, y, largura, altura, raio
PIV = (256, 540)                         # os cartões de trás giram em torno de um ponto abaixo do deck: leque curto
back2 = rotate(rrect(*CARD), 12, *PIV, 6, -6)
back1 = rotate(rrect(*CARD), 6, *PIV, 3, -3)
front = rrect(*CARD)
GC, GR, GW = (256, 268), 92, 40          # o "C": centro, raio, espessura
A0, A1 = 52, 308                         # abre à direita
c_band = arc_band(*GC, GR, GW, A0, A1)
top, bottom = polar(*GC, GR, A1), polar(*GC, GR, A0)
commit = circle(*bottom, 31)             # o commit de onde a branch sai
merge_ring, merge_hole = circle(*top, 37), circle(*top, 14)
# versão pequena: só o cartão da frente, maior, e o grafo mais grosso (lê bem em 16 px)
c_band_s = arc_band(*GC, GR, 54, A0, A1)
commit_s, merge_s = circle(*bottom, 38), circle(*top, 42)


def fit(polys, margin, size, anchor=None, pull=0.0):
    """Escala para caber em `size` com `margin`. Com `anchor` (o cartão da frente), o centro puxa `pull` em direção a
    ele: o leque fica para a direita sem o deck parecer torto no quadrado."""
    xs = [x for p in polys for x, _ in p]
    ys = [y for p in polys for _, y in p]
    k = (size - 2 * margin) / max(max(xs) - min(xs), max(ys) - min(ys))
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    if anchor:
        ax, ay = [sum(v) / len(v) for v in zip(*anchor)]
        cx, cy = cx + (ax - cx) * pull, cy + (ay - cy) * pull
    ox, oy = size / 2 - k * cx, size / 2 - k * cy
    return lambda p: [(ox + k * x, oy + k * y) for x, y in p]


def d(poly):
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in poly) + " Z"


def grads(size, gid="g"):
    return f'''<linearGradient id="{gid}" x1="0" y1="{size}" x2="{size}" y2="0" gradientUnits="userSpaceOnUse">
<stop stop-color="#6D4AF0"/>
<stop offset="1" stop-color="#2F8CF0"/>
</linearGradient>'''


def svg_logo(size=512, margin=14, gid="g"):
    """Sem fundo e sem opacidade/filtro (o instalador): cartões em cores sólidas, grafo branco no cartão da frente."""
    f = fit([back2, back1, front], margin, size)
    p = lambda poly, fill: f'<path d="{d(f(poly))}" fill="{fill}"/>'  # noqa: E731
    body = [p(back2, "#C3CEFB"), p(back1, "#8EA2F7"), p(front, f"url(#{gid})"), p(c_band, "#FFFFFF"), p(commit, "#FFFFFF"),
            p(merge_ring, "#22C38E"), p(merge_hole, "#FFFFFF")]
    return body, grads(size, gid)


def svg_icon(size=1024, small=False):
    """O ícone do app no gabarito da Apple: quadrado de 824/1024 com cantos de 185, em gradiente, com brilho no topo."""
    pad, side, rx = size * 100 / 1024, size * 824 / 1024, size * 185 / 1024
    if small:   # 16–32 px: sem cartões — só o "C" branco, grosso, ocupando o quadrado
        f = fit([c_band_s, commit_s, merge_s], size * 0.25, size)
        cards = []
        graph = [f'<path d="{d(f(c_band_s))}" fill="#FFFFFF"/>', f'<path d="{d(f(commit_s))}" fill="#FFFFFF"/>',
                 f'<path d="{d(f(merge_s))}" fill="#2BE0A0"/>']
        shadow = ""
    else:
        f = fit([back2, back1, front], size * 0.215, size, anchor=front, pull=0.45)
        cards = [f'<path d="{d(f(back2))}" fill="#FFFFFF" fill-opacity="0.30"/>', f'<path d="{d(f(back1))}" fill="#FFFFFF" fill-opacity="0.55"/>',
                 f'<path d="{d(f(front))}" fill="url(#card)"/>']
        graph = [f'<path d="{d(f(c_band))}" fill="url(#ink)"/>', f'<path d="{d(f(commit))}" fill="url(#ink)"/>',
                 f'<path d="{d(f(merge_ring))}" fill="#1FBF88"/>', f'<path d="{d(f(merge_hole))}" fill="#FFFFFF"/>']
        shadow = f'<path d="{d(f(front))}" fill="#1B0F6B" fill-opacity="0.35" filter="url(#sh)" transform="translate(0 {size * 0.012:.1f})"/>\n'
    s = size
    return f'''<svg width="{s}" height="{s}" viewBox="0 0 {s} {s}" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect x="{pad:.0f}" y="{pad:.0f}" width="{side:.0f}" height="{side:.0f}" rx="{rx:.0f}" fill="url(#bg)"/>
<rect x="{pad:.0f}" y="{pad:.0f}" width="{side:.0f}" height="{side:.0f}" rx="{rx:.0f}" fill="url(#gloss)"/>
<rect x="{pad + 1:.0f}" y="{pad + 1:.0f}" width="{side - 2:.0f}" height="{side - 2:.0f}" rx="{rx - 1:.0f}" stroke="#FFFFFF" stroke-opacity="0.14" stroke-width="{max(1, s / 512):.0f}"/>
{shadow}{chr(10).join(cards + graph)}
<defs>
<linearGradient id="bg" x1="{s * 0.1:.0f}" y1="{s * 0.9:.0f}" x2="{s * 0.9:.0f}" y2="{s * 0.1:.0f}" gradientUnits="userSpaceOnUse">
<stop stop-color="#4A2BC6"/>
<stop offset="0.55" stop-color="#4255E0"/>
<stop offset="1" stop-color="#2E8BF0"/>
</linearGradient>
<radialGradient id="gloss" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate({s * 0.5:.0f} {s * 0.02:.0f}) rotate(90) scale({s * 0.62:.0f} {s * 0.75:.0f})">
<stop stop-color="#FFFFFF" stop-opacity="0.22"/>
<stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
</radialGradient>
<linearGradient id="card" x1="0" y1="{s * 0.2:.0f}" x2="0" y2="{s * 0.8:.0f}" gradientUnits="userSpaceOnUse">
<stop stop-color="#FFFFFF"/>
<stop offset="1" stop-color="#EEF1FF"/>
</linearGradient>
<linearGradient id="ink" x1="{s * 0.3:.0f}" y1="{s * 0.75:.0f}" x2="{s * 0.7:.0f}" y2="{s * 0.25:.0f}" gradientUnits="userSpaceOnUse">
<stop stop-color="#5B34E8"/>
<stop offset="1" stop-color="#2E7EEA"/>
</linearGradient>
<filter id="sh" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="{s * 0.018:.1f}"/></filter>
</defs>
</svg>
'''


def svg_menubar(size=36):
    """Barra de menus do macOS: preto sobre transparente (o sistema pinta claro/escuro). Só o grafo em "C", grosso — em
    18 pt o deck vira borrão."""
    band = arc_band(*GC, GR, 48, A0, A1 - 30)   # termina antes do anel: o merge fica vazado
    f = fit([band, commit_s, merge_s], size * 0.08, size)
    return f'''<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="{d(f(band))}" fill="#000"/>
<path d="{d(f(commit_s))}" fill="#000"/>
<path fill-rule="evenodd" d="{d(f(circle(*top, 48)))} {d(f(circle(*top, 24)))}" fill="#000"/>
</svg>
'''


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


body, defs = svg_logo()
write(os.path.join(HERE, "logo.svg"), '<svg width="512" height="512" viewBox="0 0 512 512" fill="none" xmlns="http://www.w3.org/2000/svg">\n'
      + "\n".join(body) + f"\n<defs>\n{defs}\n</defs>\n</svg>\n")
write(os.path.join(HERE, "icon.svg"), svg_icon(1024))
write(os.path.join(HERE, "icon-small.svg"), svg_icon(1024, small=True))
write(os.path.join(HERE, "menubar.svg"), svg_menubar())
write(os.path.join(ROOT, "ui", "public", "favicon.svg"), svg_icon(64, small=True))

# a marca dentro do app: id do gradiente único por instância (várias marcas na mesma tela não se misturam)
mbody, mdefs = svg_logo(gid="__GID__")
mark = "\n".join(mbody).replace('"url(#__GID__)"', "{`url(#${gid})`}")
mdefs = mdefs.replace('id="__GID__"', "id={gid}")
write(os.path.join(ROOT, "ui", "src", "components", "Mark.svelte"), f'''<script lang="ts">
  // A marca do Codeck (deck de cartões + grafo em "C"): gerada por brand/make-logo.py — não edite à mão.
  let {{ size = 24 }}: {{ size?: number }} = $props();
  const gid = "mk" + Math.random().toString(36).slice(2, 7);
</script>

<svg width={{size}} height={{size}} viewBox="0 0 512 512" fill="none" aria-hidden="true">
{mark}
<defs>
{mdefs}
</defs>
</svg>
''')
print("✓ brand/logo.svg, icon.svg, icon-small.svg, menubar.svg · ui/public/favicon.svg · Mark.svelte")
