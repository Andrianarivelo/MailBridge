# -*- coding: utf-8 -*-
"""
build_brand.py
==============
Génère tous les fichiers de la marque GmailBridge dans assets/brand/ :

    gmailbridge-mark.svg / -mark-small.svg   symbole (dessin détaillé / petites tailles)
    gmailbridge-glyph.svg                    symbole monochrome (currentColor), sans fond
    gmailbridge-wordmark(-dark).svg          logotype « GmailBridge » en contours
    gmailbridge-lockup(-dark).svg            symbole + logotype + signature
    gmailbridge-banner.svg                   bannière (en-tête du README)
    ../gmailbridge.ico, ../logo.png          icône Windows multi-tailles, aperçu 256 px

Le texte est converti en CONTOURS (police Sora, licence SIL OFL, fournie dans
mailbridge/web/fonts) : les SVG s'affichent à l'identique sans police installée.
Signature du logotype : le point du « i » de « Bridge » est le soleil levant du symbole.

Outil de développement uniquement (l'application n'en a pas besoin) :
    uv run --with fonttools python tools/build_brand.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mailbridge import icon  # noqa: E402  (source unique du symbole)

# ----------------------------- Paramètres ------------------------------------
FONT = ROOT / "mailbridge" / "web" / "fonts" / "Sora-Variable.ttf"
OUT = ROOT / "assets" / "brand"
WEIGHT_GMAIL, WEIGHT_BRIDGE, WEIGHT_TAG = 300, 640, 500   # graisses (axe wght)
TRACKING = -2.2                 # approche du logotype (unités pour un corps 100)
TAG_TEXT, TAG_TRACKING = "TOUS VOS MAILS, UN SEUL GMAIL", 15
SUN_GAP, SUN_R = 7.5, 14.5      # soleil du « i » : écart au fût et rayon (corps 100)
COLORS = {
    "light": {"text": icon.INK, "tag": "#6B6F8E"},
    "dark": {"text": "#F7F1EA", "tag": "#A9A6C4"},
}
SUN_STOPS = (("0", "#FFD37A"), (".55", "#FF8A4C"), ("1", "#F2535B"))
# -----------------------------------------------------------------------------

_fonts: dict[int, TTFont] = {}


def _font(wght: int) -> TTFont:
    """Instance statique de la police variable pour une graisse (mise en cache)."""
    if wght not in _fonts:
        _fonts[wght] = instantiateVariableFont(TTFont(FONT), {"wght": wght})
    return _fonts[wght]


def _bounds(gs, name):
    pen = BoundsPen(gs)
    gs[name].draw(pen)
    return pen.bounds


def text_path(text: str, wght: int, x: float = 0.0, size: float = 100, tracking: float = 0.0,
              sun_i: bool = False):
    """Contours SVG d'un texte (ligne de base y = 0). Renvoie (d, x_fin, soleil).
    Avec sun_i, chaque « i » perd son point (glyphe « ı ») et sa position est renvoyée."""
    f = _font(wght)
    gs, cmap, hmtx = f.getGlyphSet(), f.getBestCmap(), f["hmtx"]
    k = size / f["head"].unitsPerEm
    pen, sun = SVGPathPen(gs), None
    for ch in text:
        if ord(ch) not in cmap:          # caractère absent de la police : remplacé par une espace
            ch = " "
        name = cmap[0x131] if (sun_i and ch == "i") else cmap[ord(ch)]
        if sun_i and ch == "i":
            b = _bounds(gs, name)
            sun = {"cx": x + (b[0] + b[2]) / 2 * k, "stem_top": b[3] * k}
        gs[name].draw(TransformPen(pen, (k, 0, 0, -k, x, 0)))
        x += hmtx[name][0] * k + tracking
    return pen.getCommands(), x - tracking, sun


def wordmark_parts():
    """Contours de « Gmail » + « Bridge » et géométrie du soleil (corps 100)."""
    d_gmail, x_end, _ = text_path("Gmail", WEIGHT_GMAIL, 0, tracking=TRACKING)
    d_bridge, width, sun = text_path("Bridge", WEIGHT_BRIDGE, x_end + TRACKING + 1.0,
                                     tracking=TRACKING, sun_i=True)
    horizon = -(sun["stem_top"] + SUN_GAP)          # base du demi-soleil (y vers le bas)
    return d_gmail, d_bridge, width, sun["cx"], horizon


def _sun_defs(gid: str, horizon: float, r: float) -> str:
    stops = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in SUN_STOPS)
    return (f'<linearGradient id="{gid}" x1="0" y1="{horizon - r:.2f}" x2="0" y2="{horizon:.2f}" '
            f'gradientUnits="userSpaceOnUse">{stops}</linearGradient>')


def wordmark_group(theme: str, gid: str) -> tuple[str, str, float]:
    """Groupe SVG du logotype (corps 100, ligne de base 0) : (defs, éléments, largeur)."""
    d_gmail, d_bridge, width, cx, horizon = wordmark_parts()
    col = COLORS[theme]["text"]
    sun = f'<path d="M{cx - SUN_R:.2f} {horizon:.2f}a{SUN_R} {SUN_R} 0 0 1 {2 * SUN_R} 0Z" fill="url(#{gid})"/>'
    body = (f'<path d="{d_gmail}" fill="{col}"/><path d="{d_bridge}" fill="{col}"/>{sun}')
    return _sun_defs(gid, horizon, SUN_R), body, width


def write_wordmarks():
    for theme in ("light", "dark"):
        defs, body, width = wordmark_group(theme, "gbsun")
        top, bottom = -92, 26                  # du haut du soleil au bas du jambage du « g »
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-4 {top} {width + 8:.1f} {bottom - top}" '
               f'role="img" aria-label="GmailBridge"><title>GmailBridge</title><defs>{defs}</defs>{body}</svg>\n')
        name = "gmailbridge-wordmark.svg" if theme == "light" else "gmailbridge-wordmark-dark.svg"
        (OUT / name).write_text(svg, encoding="utf-8")


def _inner_mark(small=False, prefix="m") -> str:
    """Contenu du symbole (sans la balise <svg> englobante) pour l'imbriquer."""
    s = icon.mark_svg(small, prefix=prefix)
    return s[s.index(">") + 1:s.rindex("</svg>")].replace("<title>GmailBridge</title>", "")


def write_lockups():
    """Symbole à gauche, logotype et signature à droite."""
    mark, gap, scale = 128, 30, 0.70
    defs, body, width = wordmark_group("light", "gbsun")
    for theme in ("light", "dark"):
        defs, body, width = wordmark_group(theme, "gbsun")
        tag_d, tag_w, _ = text_path(TAG_TEXT, WEIGHT_TAG, 0, tracking=TAG_TRACKING)
        tag_scale = 0.125
        W = mark + gap + width * scale + 8
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.1f} {mark}" role="img" '
               f'aria-label="GmailBridge : tous vos mails, un seul Gmail"><title>GmailBridge</title>'
               f'<svg width="{mark}" height="{mark}" viewBox="0 0 256 256">{_inner_mark(prefix="lk" + theme[0])}</svg>'
               f'<defs>{defs}</defs>'
               f'<g transform="translate({mark + gap} 78) scale({scale})">{body}</g>'
               f'<path transform="translate({mark + gap + 2} 108) scale({tag_scale})" d="{tag_d}" '
               f'fill="{COLORS[theme]["tag"]}"/></svg>\n')
        name = "gmailbridge-lockup.svg" if theme == "light" else "gmailbridge-lockup-dark.svg"
        (OUT / name).write_text(svg, encoding="utf-8")


def write_glyph():
    """Symbole monochrome sans fond : suit la couleur du texte (currentColor)."""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" aria-label="GmailBridge">'
           '<title>GmailBridge</title>'
           '<path d="M70 172a58 58 0 0 1 116 0Z" fill="currentColor" opacity=".38"/>'
           '<path d="M100 204h56" stroke="currentColor" stroke-width="14" stroke-linecap="round" opacity=".38"/>'
           '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">'
           '<path d="M60 56v130M196 56v130" stroke-width="24"/>'
           '<path d="M60 56Q128 240 196 56" stroke-width="20"/>'
           '<path d="M24 172h208" stroke-width="20"/></g></svg>\n')
    (OUT / "gmailbridge-glyph.svg").write_text(svg, encoding="utf-8")


def write_banner():
    """Bannière 1200 x 360 : logotype clair à gauche, pont au crépuscule à droite."""
    W, H, HZ = 1200, 360, 262            # largeur, hauteur, horizon (tablier)
    tl, tr, top, low = 720, 1010, 70, 214  # pylônes et câble principal
    sun_cx, sun_r = (tl + tr) / 2, 112

    def cy(x):
        return icon.cable_y(x, tl, tr, top, low)

    hangers = "".join(f"M{x} {cy(x):.1f}V{HZ}" for x in range(tl + 18, tr - 10, 18))
    # travées latérales : câbles de retenue des pylônes vers les culées
    side = (f"M{tl} {top}Q{tl - 70} {HZ - 40} {tl - 170} {HZ}"
            f"M{tr} {top}Q{tr + 70} {HZ - 40} {tr + 170} {HZ}")
    side_hangers = "".join(
        f"M{x} {top + (HZ - top) * ((tl - x) / 170) ** 0.72:.1f}V{HZ}" for x in range(tl - 18, tl - 160, -18)
    ) + "".join(
        f"M{x} {top + (HZ - top) * ((x - tr) / 170) ** 0.72:.1f}V{HZ}" for x in range(tr + 18, tr + 160, 18))
    ripples = "".join(
        f'<path d="M{sun_cx - w / 2 + dx:.0f} {y}h{w}" stroke-width="{sw}" opacity="{o}"/>'
        for y, w, sw, o, dx in ((280, 150, 7, 1, -40), (280, 90, 7, 1, 85), (298, 110, 6, .7, 10),
                                (316, 70, 5, .45, -6), (332, 36, 4, .25, 4)))
    defs, body, width = wordmark_group("dark", "bnsun")
    tag_d, _, _ = text_path(TAG_TEXT, WEIGHT_TAG, 0, tracking=TAG_TRACKING)
    stars = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" opacity="{o}"/>' for x, y, r, o in
                    ((88, 48, 1.8, .6), (300, 34, 1.3, .45), (520, 70, 2, .55), (640, 30, 1.2, .4),
                     (1120, 52, 1.8, .55), (1160, 120, 1.2, .35), (420, 120, 1.1, .3)))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="GmailBridge : tous vos mails, un seul Gmail">
<title>GmailBridge</title>
<defs>
 <linearGradient id="bsky" x1="0" y1="0" x2="0" y2="{HZ}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#1D2363"/><stop offset=".7" stop-color="#352C7A"/><stop offset="1" stop-color="#6E3B88"/></linearGradient>
 <linearGradient id="bsea" x1="0" y1="{HZ}" x2="0" y2="{H}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#191950"/><stop offset="1" stop-color="#0A0C2A"/></linearGradient>
 <radialGradient id="bglow" cx="{sun_cx}" cy="{HZ}" r="360" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#FF8A5B" stop-opacity=".62"/><stop offset=".45" stop-color="#E0527A" stop-opacity=".2"/><stop offset="1" stop-color="#E0527A" stop-opacity="0"/></radialGradient>
 <linearGradient id="bsun" x1="0" y1="{HZ - sun_r}" x2="0" y2="{HZ}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#FFE08A"/><stop offset=".5" stop-color="#FF9A4D"/><stop offset="1" stop-color="#F4545C"/></linearGradient>
 <linearGradient id="brip" x1="0" y1="275" x2="0" y2="335" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#FF8F52"/><stop offset="1" stop-color="#E0527A"/></linearGradient>
 <clipPath id="bclip"><rect width="{W}" height="{H}" rx="28"/></clipPath>
 {defs}
</defs>
<g clip-path="url(#bclip)">
 <rect width="{W}" height="{HZ}" fill="url(#bsky)"/><rect y="{HZ}" width="{W}" height="{H - HZ}" fill="url(#bsea)"/>
 <rect width="{W}" height="{H}" fill="url(#bglow)"/>{stars}
 <path d="M{sun_cx - sun_r} {HZ}a{sun_r} {sun_r} 0 0 1 {2 * sun_r} 0Z" fill="url(#bsun)"/>
 <g stroke="url(#brip)" stroke-linecap="round" fill="none">{ripples}</g>
 <g fill="none" stroke="#FFF3E8" stroke-linecap="round" stroke-linejoin="round">
  <path d="{hangers}{side_hangers}" stroke-width="3" opacity=".7"/>
  <path d="{side}" stroke-width="5"/>
  <path d="M{tl} {top}Q{sun_cx} {2 * low - top} {tr} {top}" stroke-width="6"/>
  <path d="M{tl} {top - 4}V{HZ + 22}M{tr} {top - 4}V{HZ + 22}" stroke-width="12"/>
  <path d="M{tl - 220} {HZ}H{tr + 260}" stroke-width="8"/>
 </g>
 <g transform="translate(72 180) scale(.8)">{body}</g>
 <path transform="translate(75 224) scale(.128)" d="{tag_d}" fill="#C9C3E4"/>
</g></svg>
'''
    (OUT / "gmailbridge-banner.svg").write_text(svg, encoding="utf-8")


# =============================================================================
# Iconographie de l'interface
# =============================================================================
# Grille 24 x 24, trait 1,75 à bouts ronds. Signature : certains pictogrammes portent un
# « soleil » d'accent (class="acc"), rempli de corail par la feuille de style de l'interface.
ICON_STROKE = 1.75
ICON_ACCENT = "#FF7A45"         # couleur de l'accent dans les fichiers SVG autonomes
ICONS = {
    # réglages : trois curseurs, le bouton du milieu est le soleil
    "settings": '<path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h11M19 17h1"/><circle cx="15" cy="7" r="2"/>'
                '<circle class="acc" cx="9" cy="12" r="2.3"/><circle cx="17" cy="17" r="2"/>',
    # synchroniser : deux arcs fléchés autour d'un soleil
    "sync": '<path d="M4.5 11a7.5 7.5 0 0 1 13.2-4.7"/><path d="M18.2 2.9 17.7 6.3 14.3 6"/>'
            '<path d="M19.5 13a7.5 7.5 0 0 1-13.2 4.7"/><path d="M5.8 21.1 6.3 17.7 9.7 18"/>'
            '<circle class="acc" cx="12" cy="12" r="1.9"/>',
    "plus": '<path d="M12 5.5v13M5.5 12h13"/>',
    "ext": '<path d="M13.5 4.5h6v6"/><path d="M19.5 4.5 11 13"/>'
           '<path d="M17.5 14v3.5a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2H10"/>',
    "chev": '<path d="m9.5 6 6 6-6 6"/>',
    "back": '<path d="m14.5 6-6 6 6 6"/>',
    # courrier : le rabat de l'enveloppe est le câble du pont, le soleil se lève dans le creux
    "mail": '<rect x="3" y="5.5" width="18" height="13" rx="2.5"/><path d="M3.8 7Q12 17.5 20.2 7"/>'
            '<circle class="acc" cx="12" cy="8.6" r="1.6"/>',
    # agenda : un demi-soleil marque le jour
    "cal": '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M8 3v4M16 3v4M3.5 10h17"/>'
           '<path class="acc" d="M9 17.5a3 3 0 0 1 6 0Z"/>',
    "pulse": '<path d="M3 12.5h3.5l2.5-6 4 11 2.5-6.5 1.5 1.5H21"/>',
    "folder": '<path d="M3.5 7.5a2 2 0 0 1 2-2h3.6l2 2h7.4a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z"/>'
              '<path d="M3.5 10.5h17"/>',
    "doc": '<path d="M14 3.5H7.5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8Z"/><path d="M14 3.5V8h4.5"/>'
           '<path d="M9 13h6M9 16.5h4"/>',
    # le symbole lui-même, en pictogramme (À propos)
    "bridge": '<path class="acc" d="M7.6 16a4.4 4.4 0 0 1 8.8 0Z"/><path d="M5 6v12.5M19 6v12.5"/>'
              '<path d="M5 6Q12 21 19 6"/><path d="M2.5 16h19"/>',
    "download": '<path d="M12 4v11"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M4.5 19.5h15"/>',
}


def _icon_svg(body: str, standalone: bool) -> str:
    if standalone:   # fichier autonome : l'accent reçoit une vraie couleur
        body = body.replace('class="acc"', f'fill="{ICON_ACCENT}" stroke="none"')
    ns = ' xmlns="http://www.w3.org/2000/svg"' if standalone else ""
    return (f'<svg{ns} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{ICON_STROKE}" '
            f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


def write_icons():
    """assets/brand/icons/*.svg (autonomes) et mailbridge/web/icons.js (interface)."""
    folder = OUT / "icons"
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in ICONS.items():
        (folder / f"{name}.svg").write_text(_icon_svg(body, True) + "\n", encoding="utf-8")
    lines = [f"  {name}: '{_icon_svg(body, False)}'," for name, body in ICONS.items()]
    js = ("/* Iconographie GmailBridge : générée par tools/build_brand.py, ne pas modifier à la main.\n"
          "   Les éléments .acc (soleil d'accent) sont colorés par style.css. */\n\"use strict\";\n"
          "const ICON = {\n" + "\n".join(lines) + "\n"
          "  okmark: '<svg class=\"okmark\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" "
          "stroke-width=\"2.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"m5 12.5 4.5 4.5L19 7.5\"/></svg>',\n"
          "};\n")
    (ROOT / "mailbridge" / "web" / "icons.js").write_text(js, encoding="utf-8")


# =============================================================================
# Charte graphique (planche de signalétique)
# =============================================================================
PALETTE = [   # (nom, hex, rôle)
    ("Nuit", "#141A3F", "texte, boutons"), ("Ciel", "#3A2E7E", "fond du symbole"),
    ("Ambre", "#FFD37A", "soleil, haut"), ("Orangé", "#FF8A4C", "soleil, accent"),
    ("Corail", "#F2535B", "soleil, bas"), ("Acier", "#FFF3E8", "pont"),
    ("Papier", "#F4F1EC", "fond clair"), ("Nuit profonde", "#0B0D21", "fond sombre"),
]
STATES = [("Actif", "#0F7F5F"), ("À vérifier", "#C27A0E"), ("Erreur", "#D33A42"),
          ("En cours", "#5546C2"), ("En pause", "#8A8DA5")]


def _t(text, x, y, size, wght=400, fill=icon.INK, anchor="start", tracking=0.0, opacity=1.0):
    """Texte vectorisé (police Sora) placé à (x, y) = ligne de base."""
    d, w, _ = text_path(text, wght, 0, tracking=tracking * 100 / size)
    k = size / 100
    if anchor == "middle":
        x -= w * k / 2
    elif anchor == "end":
        x -= w * k
    o = f' opacity="{opacity}"' if opacity < 1 else ""
    return f'<path transform="translate({x:.1f} {y:.1f}) scale({k:.4f})" d="{d}" fill="{fill}"{o}/>'


def _section(n, title, y):
    return (_t(f"{n:02d}", 60, y, 13, 600, "#C9432B", tracking=1.5)
            + _t(title.upper(), 96, y, 13, 600, icon.INK, tracking=2.2)
            + f'<path d="M60 {y + 14}H1140" stroke="#141A3F" stroke-opacity=".1"/>')


def write_board():
    """assets/brand/gmailbridge-charte.svg : symbole, construction, tailles, couleurs,
    typographie, iconographie et signalétique, sur une seule planche."""
    W, H = 1200, 1840
    parts = [f'<rect width="{W}" height="{H}" fill="#F4F1EC"/>']
    # -- En-tête de nuit
    defs, wm, wm_w = wordmark_group("dark", "bdsun")
    parts.append(f'<defs>{defs}<linearGradient id="bdnight" x1="0" y1="0" x2="0" y2="230" gradientUnits="userSpaceOnUse">'
                 f'<stop offset="0" stop-color="#1D2363"/><stop offset="1" stop-color="#2E2770"/></linearGradient>'
                 f'<radialGradient id="bdglow" cx="980" cy="260" r="420" gradientUnits="userSpaceOnUse">'
                 f'<stop offset="0" stop-color="#FF8A5B" stop-opacity=".55"/><stop offset="1" stop-color="#E0527A" stop-opacity="0"/></radialGradient></defs>'
                 f'<rect width="{W}" height="230" fill="url(#bdnight)"/><rect width="{W}" height="230" fill="url(#bdglow)"/>'
                 f'<svg x="60" y="55" width="120" height="120" viewBox="0 0 256 256">{_inner_mark(prefix="bdm")}</svg>'
                 f'<g transform="translate(212 128) scale(.74)">{wm}</g>'
                 + _t("TOUS VOS MAILS, UN SEUL GMAIL", 214, 162, 12.5, 500, "#C9C3E4", tracking=2)
                 + _t("Charte graphique", 1140, 118, 26, 600, "#F7F1EA", "end")
                 + _t("Symbole, couleurs, typographie, signalétique · v3.0", 1140, 148, 13, 400, "#C9C3E4", "end"))

    # -- 01 Concept et construction
    y0 = 290
    parts.append(_section(1, "Concept et construction", y0))
    parts.append(f'<svg x="60" y="{y0 + 40}" width="300" height="300" viewBox="0 0 256 256">{_inner_mark(prefix="bdc")}</svg>')
    k, ox, oy = 300 / 256, 400, y0 + 40          # dessin de construction, même échelle
    P = lambda x, y: f"{ox + x * k:.1f} {oy + y * k:.1f}"
    grid = "".join(f"M{P(g, 8)}V{oy + 248 * k:.1f}M{P(8, g)}H{ox + 248 * k:.1f}" for g in range(40, 248, 32))
    L = icon
    parts.append(
        f'<rect x="{ox + 8 * k:.1f}" y="{oy + 8 * k:.1f}" width="{240 * k:.1f}" height="{240 * k:.1f}" rx="{60 * k:.1f}" '
        f'fill="#FFFFFF" stroke="#141A3F" stroke-opacity=".18"/>'
        f'<path d="{grid}" stroke="#141A3F" stroke-opacity=".06"/>'
        f'<circle cx="{ox + 128 * k:.1f}" cy="{oy + L.DECK_Y * k:.1f}" r="{56 * k:.1f}" fill="none" stroke="#FF8A4C" stroke-dasharray="4 4"/>'
        f'<path d="M{P(72, L.DECK_Y)}a{56 * k:.1f} {56 * k:.1f} 0 0 1 {112 * k:.1f} 0Z" fill="#FF8A4C" fill-opacity=".18"/>'
        f'<g fill="none" stroke="#141A3F" stroke-linecap="round">'
        f'<path d="M{P(L.TOWER_L, L.TOWER_TOP)}V{oy + 184 * k:.1f}M{P(L.TOWER_R, L.TOWER_TOP)}V{oy + 184 * k:.1f}" stroke-width="2.5"/>'
        f'<path d="M{P(L.TOWER_L, L.TOWER_TOP)}Q{P(128, 2 * L.CABLE_LOW - L.TOWER_TOP)} {P(L.TOWER_R, L.TOWER_TOP)}" stroke-width="2"/>'
        f'<path d="M{P(30, L.DECK_Y)}H{ox + 226 * k:.1f}" stroke-width="2.5"/>'
        f'<path d="M{P(L.TOWER_L, L.TOWER_TOP)}Q{P(128, 2 * L.CABLE_LOW - L.TOWER_TOP)} {P(L.TOWER_R, L.TOWER_TOP)}" '
        f'stroke="#C9432B" stroke-dasharray="2 5" stroke-width="1" transform="translate(0 0)"/></g>'
        f'<circle cx="{ox + 128 * k:.1f}" cy="{oy + L.CABLE_LOW * k:.1f}" r="3" fill="#C9432B"/>')
    # légendes de la construction
    notes = [(L.TOWER_L, L.TOWER_TOP, "pylônes = jambages du M"), (128, L.CABLE_LOW, "câble : parabole"),
             (226, L.DECK_Y, "tablier = horizon"), (150, 120, "soleil levant = le courrier")]
    for i, (x, y, txt) in enumerate(notes):
        ly = oy + 30 + i * 70
        parts.append(f'<path d="M{P(x, y)}L{ox + 318:.1f} {ly - 4:.1f}H{ox + 330:.1f}" fill="none" stroke="#C9432B" stroke-width="1"/>'
                     f'<circle cx="{ox + x * k:.1f}" cy="{oy + y * k:.1f}" r="2.5" fill="#C9432B"/>'
                     + _t(txt, ox + 336, ly, 13, 500, icon.INK))
    story = ["Un pont suspendu au lever du soleil.", "Pylônes et câble dessinent un M : Gmail,",
             "et le rabat d'une enveloppe.", "Le tablier est l'horizon ; le soleil, le",
             "courrier qui arrive, se lève derrière le pont."]
    for i, line in enumerate(story):
        parts.append(_t(line, 736, y0 + 312 + i * 19, 12, 400, "#61668A"))

    # -- 02 Tailles : dessin détaillé dès 48 px, simplifié en dessous
    y1 = y0 + 450
    parts.append(_section(2, "Tailles", y1))
    x = 60
    for s in (128, 64, 48, 32, 24, 16):
        small = s <= icon.SMALL_MAX
        parts.append(f'<svg x="{x}" y="{y1 + 40 + 128 - s}" width="{s}" height="{s}" viewBox="0 0 256 256">'
                     f'{_inner_mark(small, prefix=f"bds{s}")}</svg>'
                     + _t(f"{s} px", x + s / 2, y1 + 196, 11, 500, "#61668A", "middle"))
        x += s + 46
    parts.append(_t("Dès 48 px : suspentes, reflets, étoiles.", 700, y1 + 110, 13, 500, icon.INK)
                 + _t("Jusqu'à 40 px : traits épais, lisible dans la barre des tâches.", 700, y1 + 134, 13, 400, "#61668A"))

    # -- 03 Couleurs
    y2 = y1 + 250
    parts.append(_section(3, "Couleurs", y2))
    for i, (name, hx, role) in enumerate(PALETTE):
        cx, cy = 60 + i * 136, y2 + 40
        parts.append(f'<rect x="{cx}" y="{cy}" width="122" height="84" rx="14" fill="{hx}" stroke="#141A3F" stroke-opacity=".1"/>'
                     + _t(name, cx, cy + 106, 12.5, 600, icon.INK) + _t(hx, cx, cy + 124, 11, 400, "#61668A")
                     + _t(role, cx, cy + 140, 10.5, 400, "#8A8DA5"))
    parts.append(f'<rect x="60" y="{y2 + 196}" width="1080" height="10" rx="5" fill="url(#bdsungrad)"/>'
                 f'<defs><linearGradient id="bdsungrad"><stop offset="0" stop-color="#FFD37A"/><stop offset=".55" stop-color="#FF8A4C"/>'
                 f'<stop offset="1" stop-color="#F2535B"/></linearGradient></defs>'
                 + _t("dégradé « soleil » : ambre, orangé, corail", 60, y2 + 228, 11, 400, "#61668A"))

    # -- 04 Typographie
    y3 = y2 + 280
    parts.append(_section(4, "Typographie", y3))
    ldefs, lwm, _ = wordmark_group("light", "bdtype")
    parts.append(f'<defs>{ldefs}</defs><g transform="translate(60 {y3 + 92}) scale(.6)">{lwm}</g>'
                 + _t("Sora 300 + 640, approche serrée : logotype, titres, chiffres.", 520, y3 + 64, 13, 500, icon.INK)
                 + _t("Segoe UI Variable : texte courant de l'interface (police du système).", 520, y3 + 88, 13, 400, "#61668A")
                 + _t("Sora : SIL Open Font License 1.1, fournie dans mailbridge/web/fonts.", 520, y3 + 112, 11, 400, "#8A8DA5"))

    # -- 05 Iconographie
    y4 = y3 + 170
    parts.append(_section(5, "Iconographie", y4))
    for i, (name, body) in enumerate(ICONS.items()):
        cx = 60 + i * 84
        b = body.replace('class="acc"', f'fill="{ICON_ACCENT}" stroke="none"')
        parts.append(f'<rect x="{cx}" y="{y4 + 36}" width="64" height="64" rx="16" fill="#FFFFFF" stroke="#141A3F" stroke-opacity=".08"/>'
                     f'<svg x="{cx + 16}" y="{y4 + 52}" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#141A3F" '
                     f'stroke-width="{ICON_STROKE}" stroke-linecap="round" stroke-linejoin="round">{b}</svg>'
                     + _t(name, cx + 32, y4 + 120, 10.5, 500, "#61668A", "middle"))
    parts.append(_t("Grille 24, trait 1,75 à bouts ronds ; le soleil d'accent signe les pictogrammes clés.", 60, y4 + 150, 12, 400, "#61668A"))

    # -- 06 Signalétique : états et boutons
    y5 = y4 + 200
    parts.append(_section(6, "Signalétique", y5))
    for i, (name, hx) in enumerate(STATES):
        cx = 60 + i * 150
        op = "" if name != "En pause" else ' opacity=".9"'
        parts.append(f'<g transform="translate({cx} {y5 + 46}) scale(2.4)"{op}>'
                     f'<path d="M2.5 5.5a4.5 4.5 0 0 1 9 0Z" fill="{hx}"/><rect x="0" y="6.5" width="14" height="1.6" rx=".8" fill="{hx}" opacity=".5"/></g>'
                     + _t(name, cx + 44, y5 + 62, 12.5, 500, icon.INK))
    parts.append(_t("État : un demi-soleil posé sur l'horizon, de la couleur du niveau.", 60, y5 + 100, 12, 400, "#61668A"))
    by = y5 + 130
    parts.append(  # bouton principal : ciel de nuit, soleil levant sous l'horizon
        f'<defs><linearGradient id="bdbtn" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2B3076"/><stop offset="1" stop-color="#171B47"/></linearGradient>'
        f'<radialGradient id="bdbtnsun" cx=".5" cy="1" r=".7"><stop offset="0" stop-color="#FFD37A"/><stop offset=".5" stop-color="#FF8A4C" stop-opacity=".8"/>'
        f'<stop offset="1" stop-color="#F2535B" stop-opacity="0"/></radialGradient>'
        f'<clipPath id="bdbtnclip"><rect x="60" y="{by}" width="190" height="44" rx="13"/></clipPath></defs>'
        f'<g clip-path="url(#bdbtnclip)"><rect x="60" y="{by}" width="190" height="44" fill="url(#bdbtn)"/>'
        f'<ellipse cx="155" cy="{by + 47}" rx="72" ry="19" fill="url(#bdbtnsun)"/>'
        f'<path d="M72 {by + 43.5}H238" stroke="#FFD6AA" stroke-opacity=".7"/></g>'
        + _t("Synchroniser", 155, by + 28, 14, 600, "#FFF6EE", "middle")
        + f'<rect x="280" y="{by}" width="170" height="44" rx="13" fill="#FFFFFF" stroke="#141A3F" stroke-opacity=".16"/>'
        + _t("Secondaire", 365, by + 28, 14, 600, icon.INK, "middle")
        + f'<rect x="480" y="{by + 6}" width="132" height="32" rx="16" fill="none" stroke="#C9432B" stroke-opacity=".55" stroke-dasharray="3 3"/>'
        + _t("+  Ajouter", 546, by + 27, 13, 600, "#C9432B", "middle")
        + _t("Principal : ciel de nuit, le soleil se lève au survol. Secondaire : contour net.", 660, by + 18, 12, 400, "#61668A")
        + _t("Ajouter : emplacement libre en pointillés. Poignée des panneaux : un câble en U.", 660, by + 38, 12, 400, "#61668A"))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Charte graphique GmailBridge">'
           f'<title>Charte graphique GmailBridge</title>{"".join(parts)}</svg>\n')
    (OUT / "gmailbridge-charte.svg").write_text(svg, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_board()
    icon.write_mark_svgs(OUT)
    write_glyph()
    write_wordmarks()
    write_lockups()
    write_banner()
    write_icons()
    icon.write_ico()
    (ROOT / "assets" / "logo.png").write_bytes(icon.png_bytes(256))
    for p in sorted(OUT.glob("*.svg")):
        print(f"{p.relative_to(ROOT)}  ({p.stat().st_size / 1024:.1f} Ko)")


if __name__ == "__main__":
    main()
