# -*- coding: utf-8 -*-
"""
icon.py
=======
Dessine l'icône de MailBridge (enveloppe blanche sur carré arrondi indigo -> violet)
sans aucune bibliothèque d'image : chaque pixel est calculé par « distance signée »
aux formes, ce qui donne des bords lisses à n'importe quelle taille.

    python -m mailbridge.icon      # écrit assets/mailbridge.ico

Utilisé aussi par la fenêtre (photo_data) pour afficher l'icône nette quel que
soit le zoom d'affichage de Windows.
"""

from __future__ import annotations

import base64
import math
import struct
import zlib
from pathlib import Path

# ----------------------------- Paramètres ------------------------------------
TOP_COLOR = (99, 102, 241)      # indigo, haut du dégradé
BOTTOM_COLOR = (139, 92, 246)   # violet, bas du dégradé
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICO_PATH = Path(__file__).resolve().parent.parent / "assets" / "mailbridge.ico"
# Géométrie dans un repère 256 x 256
TILE = (128, 128, 120, 120, 54)          # centre x, y, demi-largeur, demi-hauteur, rayon
ENVELOPE = (128, 134, 74, 52, 12)
FLAP = ((58, 90), (128, 142), (198, 90))  # rabat en V
FLAP_HALF_WIDTH = 7
# -----------------------------------------------------------------------------


def _clamp(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _sd_round_box(px, py, cx, cy, hw, hh, r) -> float:
    """Distance signée d'un point à un rectangle arrondi (négative à l'intérieur)."""
    qx = abs(px - cx) - (hw - r)
    qy = abs(py - cy) - (hh - r)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def _sd_segment(px, py, a, b) -> float:
    """Distance d'un point au segment [a, b]."""
    pax, pay = px - a[0], py - a[1]
    bax, bay = b[0] - a[0], b[1] - a[1]
    h = _clamp((pax * bax + pay * bay) / (bax * bax + bay * bay))
    return math.hypot(pax - bax * h, pay - bay * h)


def render_rgba(size: int) -> bytes:
    """Pixels RGBA (size x size) de l'icône."""
    s = size / 256.0
    half_w = max(FLAP_HALF_WIDTH, 0.65 / s)   # trait toujours visible, même en 16 px
    out = bytearray()
    for y in range(size):
        py = (y + 0.5) / s
        t = py / 256.0
        grad = [TOP_COLOR[i] + (BOTTOM_COLOR[i] - TOP_COLOR[i]) * t for i in range(3)]
        for x in range(size):
            px = (x + 0.5) / s
            a_tile = _clamp(0.5 - _sd_round_box(px, py, *TILE) * s)
            if a_tile <= 0.0:
                out += b"\0\0\0\0"
                continue
            a_env = _clamp(0.5 - _sd_round_box(px, py, *ENVELOPE) * s)
            d_flap = min(_sd_segment(px, py, FLAP[0], FLAP[1]), _sd_segment(px, py, FLAP[1], FLAP[2])) - half_w
            a_flap = _clamp(0.5 - d_flap * s) * a_env
            c = [grad[i] * (1 - a_env) + 255 * a_env for i in range(3)]
            c = [c[i] * (1 - a_flap) + grad[i] * a_flap for i in range(3)]
            out += bytes((int(c[0] + 0.5), int(c[1] + 0.5), int(c[2] + 0.5), int(a_tile * 255 + 0.5)))
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


if __name__ == "__main__":
    print(f"Icône écrite : {write_ico()}")
