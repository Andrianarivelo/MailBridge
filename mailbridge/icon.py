# -*- coding: utf-8 -*-
"""
icon.py
=======
Symbole de GmailBridge : un pont suspendu au lever du soleil.

    Les deux pylônes et le câble porteur (une vraie parabole) dessinent un « M »,
    qui est aussi le rabat d'une enveloppe ; le tablier sert d'horizon, le soleil
    (le courrier qui arrive) se lève derrière le pont et se reflète dans l'eau.

Ce module est l'UNIQUE source de vérité du symbole. La même description en calques
(LAYERS_LARGE, LAYERS_SMALL) sert à :
    * écrire les SVG de la marque  (mark_svg)          -> assets/brand/*.svg
    * calculer les pixels de l'icône Windows, sans aucune bibliothèque d'image
      (render_rgba : chaque pixel est obtenu par « distance signée » aux formes,
      d'où des bords lisses à toutes les tailles)          -> assets/gmailbridge.ico

Deux dessins : le détaillé (suspentes, reflets, étoiles) à partir de 48 px, et un
dessin simplifié aux traits épais pour 16 à 32 px (barre des tâches, zone de
notification), comme le font les familles d'icônes professionnelles.

    python -m mailbridge.icon      # écrit l'icône .ico et les deux SVG du symbole
"""

from __future__ import annotations

import base64
import math
import struct
import zlib
from pathlib import Path

# ----------------------------- Paramètres ------------------------------------
ROOT = Path(__file__).resolve().parent.parent
ICO_PATH = ROOT / "assets" / "gmailbridge.ico"
BRAND_DIR = ROOT / "assets" / "brand"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
SMALL_MAX = 40                  # en dessous ou égal : dessin simplifié
VIEW = 256                      # repère de dessin 256 x 256

# Palette « crépuscule sur le pont » (reprise par web/style.css)
INK = "#141A3F"                 # nuit
STEEL = ("#FFFFFF", "#FFE9DA")  # acier du pont (blanc vers crème chaud)

# Pont du dessin détaillé : pylônes x = 66 et 190, câble de y = 70 (sommets) à 148 (milieu)
TOWER_L, TOWER_R, TOWER_TOP, CABLE_LOW, DECK_Y = 66, 190, 70, 148, 168
HANGERS_X = (82, 97, 112, 144, 159, 174)
# -----------------------------------------------------------------------------


def cable_y(x: float, x0=TOWER_L, x1=TOWER_R, top=TOWER_TOP, low=CABLE_LOW) -> float:
    """Hauteur du câble porteur (parabole) à l'abscisse x."""
    mid, half = (x0 + x1) / 2, (x1 - x0) / 2
    return low - (low - top) * ((x - mid) / half) ** 2


# Description des calques.  Formes : rect, halfdisc (disque coupé à l'horizon),
# circle, seg (trait à bouts ronds), parabola (câble).  Peinture : couleur "#RRGGBB"
# ou dégradé ("lin", y0, y1, arrêts) / ("rad", cx, cy, r, arrêts) ; arrêt = (t, couleur, opacité).
def _steel(y0, y1):
    return ("lin", y0, y1, ((0, STEEL[0], 1), (1, STEEL[1], 1)))


LAYERS_LARGE = {
    "tile": (8, 8, 240, 240, 60),
    "layers": [
        (("rect", 0, 0, 256, DECK_Y), ("lin", 8, DECK_Y, ((0, "#232A72", 1), (.7, "#3A2E7E", 1), (1, "#6A3A86", 1))), 1),
        (("rect", 0, DECK_Y, 256, 256), ("lin", DECK_Y, 248, ((0, "#1A1A52", 1), (1, "#0B0D2C", 1))), 1),
        (("rect", 0, 0, 256, 256), ("rad", 128, DECK_Y, 112, ((0, "#FF8A5B", .7), (.5, "#E0527A", .22), (1, "#E0527A", 0))), 1),
        (("halfdisc", 128, DECK_Y, 56), ("lin", 112, DECK_Y, ((0, "#FFE08A", 1), (.5, "#FF9A4D", 1), (1, "#F4545C", 1))), 1),
        # reflets du soleil, de plus en plus courts et pâles
        *[(("seg", x0, y, x1, y, w), ("lin", 180, 222, ((0, "#FF8F52", 1), (1, "#E0527A", 1))), o)
          for x0, x1, y, w, o in ((90, 120, 184, 6, 1), (130, 168, 184, 6, 1), (100, 118, 198, 5, .7),
                                  (127, 157, 198, 5, .7), (112, 144, 211, 4, .45), (121, 135, 223, 3, .25))],
        (("circle", 56, 46, 2.4), "#FFFFFF", .7),
        (("circle", 206, 58, 1.7), "#FFFFFF", .5),
        (("circle", 178, 34, 1.2), "#FFFFFF", .4),
        # suspentes, du câble au tablier
        *[(("seg", x, round(cable_y(x), 1), x, DECK_Y, 4), _steel(64, 184), .8) for x in HANGERS_X],
        (("seg", TOWER_L, TOWER_TOP, TOWER_L, 184, 13), _steel(64, 184), 1),
        (("seg", TOWER_R, TOWER_TOP, TOWER_R, 184, 13), _steel(64, 184), 1),
        (("parabola", TOWER_L, TOWER_R, TOWER_TOP, CABLE_LOW, 9.5), _steel(64, 184), 1),
        (("seg", 30, DECK_Y, 226, DECK_Y, 11), _steel(64, 184), 1),
    ],
}

LAYERS_SMALL = {
    "tile": (8, 8, 240, 240, 56),
    "layers": [
        (("rect", 0, 0, 256, 166), ("lin", 8, 166, ((0, "#262C78", 1), (1, "#4A3285", 1))), 1),
        (("rect", 0, 166, 256, 256), ("lin", 166, 248, ((0, "#16174A", 1), (1, "#0D0F31", 1))), 1),
        (("halfdisc", 128, 170, 62), ("lin", 110, 172, ((0, "#FFD978", 1), (1, "#FF6A52", 1))), 1),
        (("seg", 98, 206, 158, 206, 16), "#FF7A55", 1),
        (("seg", 60, 60, 60, 186, 26), "#FFFFFF", 1),
        (("seg", 196, 60, 196, 186, 26), "#FFFFFF", 1),
        (("parabola", 60, 196, 60, 148, 22), "#FFFFFF", 1),
        (("seg", 28, 170, 228, 170, 22), "#FFFFFF", 1),
    ],
}


# =============================================================================
# SVG
# =============================================================================

def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def mark_svg(small: bool = False, prefix: str = "gb") -> str:
    """Symbole en SVG autonome. `prefix` évite les collisions d'identifiants
    quand plusieurs symboles sont intégrés dans une même page."""
    spec = LAYERS_SMALL if small else LAYERS_LARGE
    defs, body = [], []

    def paint(p, n):
        if isinstance(p, str):
            return p
        gid = f"{prefix}{'s' if small else 'l'}{n}"
        stops = "".join(f'<stop offset="{_fmt(t)}" stop-color="{c}"' + (f' stop-opacity="{_fmt(o)}"' if o < 1 else "") + "/>"
                        for t, c, o in p[-1])
        if p[0] == "lin":
            defs.append(f'<linearGradient id="{gid}" x1="0" y1="{_fmt(p[1])}" x2="0" y2="{_fmt(p[2])}" '
                        f'gradientUnits="userSpaceOnUse">{stops}</linearGradient>')
        else:
            defs.append(f'<radialGradient id="{gid}" cx="{_fmt(p[1])}" cy="{_fmt(p[2])}" r="{_fmt(p[3])}" '
                        f'gradientUnits="userSpaceOnUse">{stops}</radialGradient>')
        return f"url(#{gid})"

    for n, (shape, p, op) in enumerate(spec["layers"]):
        kind, *a = shape
        col = paint(p, n)
        o = f' opacity="{_fmt(op)}"' if op < 1 else ""
        if kind == "rect":
            body.append(f'<rect x="{_fmt(a[0])}" y="{_fmt(a[1])}" width="{_fmt(a[2] - a[0])}" height="{_fmt(a[3] - a[1])}" fill="{col}"{o}/>')
        elif kind == "halfdisc":
            cx, cy, r = a
            body.append(f'<path d="M{_fmt(cx - r)} {_fmt(cy)}a{_fmt(r)} {_fmt(r)} 0 0 1 {_fmt(2 * r)} 0Z" fill="{col}"{o}/>')
        elif kind == "circle":
            body.append(f'<circle cx="{_fmt(a[0])}" cy="{_fmt(a[1])}" r="{_fmt(a[2])}" fill="{col}"{o}/>')
        elif kind == "seg":
            body.append(f'<path d="M{_fmt(a[0])} {_fmt(a[1])}L{_fmt(a[2])} {_fmt(a[3])}" stroke="{col}" '
                        f'stroke-width="{_fmt(a[4])}" stroke-linecap="round"{o}/>')
        elif kind == "parabola":
            x0, x1, top, low, w = a
            body.append(f'<path d="M{_fmt(x0)} {_fmt(top)}Q{_fmt((x0 + x1) / 2)} {_fmt(2 * low - top)} {_fmt(x1)} {_fmt(top)}" '
                        f'fill="none" stroke="{col}" stroke-width="{_fmt(w)}" stroke-linecap="round"{o}/>')
    tx, ty, tw, th, tr = spec["tile"]
    clip = f"{prefix}{'s' if small else 'l'}clip"
    defs.append(f'<clipPath id="{clip}"><rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="{tr}"/></clipPath>')
    title = "GmailBridge"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW} {VIEW}" role="img" aria-label="{title}">'
            f'<title>{title}</title><defs>{"".join(defs)}</defs>'
            f'<g clip-path="url(#{clip})">{"".join(body)}</g></svg>\n')


# =============================================================================
# Rastérisation (distance signée + composition « over », pur Python)
# =============================================================================

def _clamp(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _rgb(h: str):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _sd_round_box(px, py, x, y, w, h, r) -> float:
    """Distance signée au rectangle arrondi (négative à l'intérieur)."""
    qx = abs(px - (x + w / 2)) - (w / 2 - r)
    qy = abs(py - (y + h / 2)) - (h / 2 - r)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def _d_segment(px, py, ax, ay, bx, by) -> float:
    """Distance au segment [a, b]."""
    pax, pay, bax, bay = px - ax, py - ay, bx - ax, by - ay
    h = _clamp((pax * bax + pay * bay) / (bax * bax + bay * bay or 1e-9))
    return math.hypot(pax - bax * h, pay - bay * h)


def _d_parabola(px, py, x0, x1, top, low) -> float:
    """Distance au câble : approximation du premier ordre |f| / |grad f| (exacte au
    voisinage du trait, là où se joue l'anticrénelage), puis bouts ronds aux sommets."""
    mid, half = (x0 + x1) / 2, (x1 - x0) / 2
    a = (low - top) / (half * half)
    xc = min(max(px, x0), x1)
    slope = -2 * a * (xc - mid)
    d = abs(py - (low - a * (xc - mid) ** 2)) / math.sqrt(1 + slope * slope)
    if px != xc:      # au-delà des sommets : distance à l'extrémité
        d = math.hypot(px - xc, py - top)
    return d


def _coverage(shape, px, py, s) -> float:
    """Couverture (0..1) d'un pixel centré en (px, py) ; s = pixels par unité."""
    kind, *a = shape
    if kind == "rect":
        x0, y0, x1, y1 = a
        d = max(x0 - px, px - x1, y0 - py, py - y1)
    elif kind == "halfdisc":
        cx, cy, r = a
        d = max(math.hypot(px - cx, py - cy) - r, py - cy)
    elif kind == "circle":
        d = math.hypot(px - a[0], py - a[1]) - a[2]
    elif kind == "seg":
        w = max(a[4], 1.0 / s)           # jamais plus fin qu'un pixel
        d = _d_segment(px, py, *a[:4]) - w / 2
    else:  # parabola
        w = max(a[4], 1.0 / s)
        d = _d_parabola(px, py, *a[:4]) - w / 2
    return _clamp(0.5 - d * s)


def _bbox(shape):
    """Boîte englobante (pour ne calculer que les pixels utiles)."""
    kind, *a = shape
    if kind == "rect":
        return a[0], a[1], a[2], a[3]
    if kind in ("halfdisc", "circle"):
        return a[0] - a[2], a[1] - a[2], a[0] + a[2], a[1] + (0 if kind == "halfdisc" else a[2])
    if kind == "seg":
        w = a[4] / 2 + 2
        return min(a[0], a[2]) - w, min(a[1], a[3]) - w, max(a[0], a[2]) + w, max(a[1], a[3]) + w
    w = a[4] / 2 + 2
    return a[0] - w, a[2] - w, a[1] + w, a[3] + w


def _paint_at(p, px, py):
    """Couleur (r, g, b) et opacité du dégradé au point (px, py)."""
    if isinstance(p, str):
        return _rgb(p), 1.0
    if p[0] == "lin":
        t = _clamp((py - p[1]) / (p[2] - p[1]))
    else:
        t = _clamp(math.hypot(px - p[1], py - p[2]) / p[3])
    stops = p[-1]
    for (t0, c0, o0), (t1, c1, o1) in zip(stops, stops[1:]):
        if t <= t1:
            k = 0 if t1 == t0 else (t - t0) / (t1 - t0)
            c0, c1 = _rgb(c0), _rgb(c1)
            return tuple(c0[i] + (c1[i] - c0[i]) * k for i in range(3)), o0 + (o1 - o0) * k
    return _rgb(stops[-1][1]), stops[-1][2]


def render_rgba(size: int) -> bytes:
    """Pixels RGBA (size x size) de l'icône, dessin choisi selon la taille."""
    spec = LAYERS_SMALL if size <= SMALL_MAX else LAYERS_LARGE
    s = size / VIEW
    layers = [(sh, p, op, _bbox(sh)) for sh, p, op in spec["layers"]]
    out = bytearray()
    for y in range(size):
        py = (y + 0.5) / s
        for x in range(size):
            px = (x + 0.5) / s
            a_tile = _clamp(0.5 - _sd_round_box(px, py, *spec["tile"]) * s)
            if a_tile <= 0.0:
                out += b"\0\0\0\0"
                continue
            c = [0.0, 0.0, 0.0]
            for shape, p, op, (bx0, by0, bx1, by1) in layers:
                if px < bx0 or px > bx1 or py < by0 or py > by1:
                    continue
                cov = _coverage(shape, px, py, s)
                if cov <= 0.0:
                    continue
                rgb, o = _paint_at(p, px, py)
                k = cov * o * op
                c = [c[i] + (rgb[i] - c[i]) * k for i in range(3)]
            out += bytes((int(c[0] + .5), int(c[1] + .5), int(c[2] + .5), int(a_tile * 255 + .5)))
    return bytes(out)


def png_bytes(size: int) -> bytes:
    """Encode l'icône en PNG (RGBA 8 bits) avec zlib, sans bibliothèque externe."""
    raw = render_rgba(size)
    stride = size * 4
    data = b"".join(b"\x00" + raw[y * stride:(y + 1) * stride] for y in range(size))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(data, 9))
            + chunk(b"IEND", b""))


def photo_data(size: int) -> bytes:
    """PNG en base64, directement utilisable par tkinter.PhotoImage(data=...)."""
    return base64.b64encode(png_bytes(size))


def write_ico(path: Path = ICO_PATH, sizes=ICO_SIZES) -> Path:
    """Écrit un .ico multi-tailles (images PNG intégrées, format Windows Vista et +)."""
    pngs = [png_bytes(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, p in zip(sizes, pngs):
        dim = s if s < 256 else 0  # 0 signifie 256 dans le format ICO
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(p), offset)
        offset += len(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + b"".join(pngs))
    return path


def write_mark_svgs(folder: Path = BRAND_DIR) -> list[Path]:
    """Écrit les deux dessins du symbole en SVG."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / "gmailbridge-mark.svg", folder / "gmailbridge-mark-small.svg"]
    paths[0].write_text(mark_svg(False), encoding="utf-8")
    paths[1].write_text(mark_svg(True), encoding="utf-8")
    return paths


if __name__ == "__main__":
    print(f"Icône écrite : {write_ico()}")
    for p in write_mark_svgs():
        print(f"SVG écrit : {p}")
