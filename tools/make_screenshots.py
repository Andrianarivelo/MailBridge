# -*- coding: utf-8 -*-
"""
make_screenshots.py
===================
Captures d'écran du README (docs/screenshots/), prises dans le MODE DÉMO de l'interface :
données fictives uniquement, aucune donnée personnelle ne peut apparaître.

    docs/screenshots/01-dashboard-light.png ... 07-settings.png   étapes d'utilisation
    docs/screenshots/hero.png                                     trois fenêtres sur la bannière
    docs/screenshots/sync.gif                                     clic sur « Synchroniser », animé

Outil de développement (Chrome installé + Playwright, sans téléchargement de navigateur) :
    uv run --with playwright --with pillow python tools/make_screenshots.py
"""

from __future__ import annotations

import base64
import io
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

# ----------------------------- Paramètres ------------------------------------
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
APP = (ROOT / "mailbridge" / "web" / "index.html").as_uri()
WINDOW = {"width": 420, "height": 730}   # taille logique de la fenêtre (ui.WINDOW_SIZE)
SCALE = 2                                # captures nettes sur écrans haute densité
SETTLE_MS = 2600                         # fin des animations d'entrée
GIF_SCALE, GIF_CROP_H = 1.5, 236         # GIF : zoom et hauteur gardée (en-tête + carte principale)
# Étapes : (fichier, thème, ancre démo, action facultative)
STEPS = [
    ("01-dashboard-light", "light", "demo", None),
    ("01-dashboard-dark", "dark", "demo", None),
    ("02-gmail", "light", "demo", lambda pg: pg.click("#targets [data-k=gmail]")),
    ("03-add-account", "light", "demo-add", None),
    ("04-account-form", "dark", "demo-form", lambda pg: (pg.fill("#fUser", "first.last@yahoo.com"),
                                                         pg.fill("#fPass", "correct-horse"))),
    ("05-calendar-setup", "light", "demo-calsetup", None),
    ("06-calendar-connected", "dark", "demo-cal", None),
    ("07-settings", "light", "demo-settings", None),
]
# -----------------------------------------------------------------------------


def shoot_steps(browser) -> None:
    """Une capture par étape d'utilisation."""
    for name, scheme, anchor, action in STEPS:
        ctx = browser.new_context(viewport=WINDOW, device_scale_factor=SCALE, color_scheme=scheme)
        pg = ctx.new_page()
        pg.goto(f"{APP}#{anchor}")
        pg.wait_for_timeout(SETTLE_MS)
        if action:
            action(pg)
            pg.wait_for_timeout(900)
        pg.screenshot(path=str(OUT / f"{name}.png"))
        ctx.close()
        print(f"  {name}.png")


def shoot_gif(browser) -> None:
    """Le soleil se lève sur le bouton, clic, le courrier traverse le pont, notification."""
    ctx = browser.new_context(viewport=WINDOW, device_scale_factor=GIF_SCALE, color_scheme="dark")
    pg = ctx.new_page()
    pg.goto(f"{APP}#demo")
    pg.wait_for_timeout(SETTLE_MS)
    frames, stamps = [], []

    def grab(seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            png = pg.screenshot(clip={"x": 0, "y": 0, "width": WINDOW["width"], "height": GIF_CROP_H})
            frames.append(Image.open(io.BytesIO(png)).convert("RGB"))
            stamps.append(time.perf_counter())

    grab(0.6)                              # repos
    pg.hover("#btnSync")
    grab(1.0)                              # le soleil se lève sous le bouton
    pg.click("#btnSync")
    grab(3.6)                              # synchronisation (2,2 s en démo) puis notification
    pg.mouse.move(10, 700)
    grab(0.8)
    ctx.close()
    durations = [max(40, int((b - a) * 1000)) for a, b in zip(stamps, stamps[1:])] + [1600]
    pal = [f.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE) for f in frames]  # FASTOCTREE garde les petites touches de couleur (signaux d état)
    pal[0].save(OUT / "sync.gif", save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True)
    print(f"  sync.gif ({len(frames)} images, {(OUT / 'sync.gif').stat().st_size / 1e6:.1f} Mo)")


def shoot_hero(browser) -> None:
    """Trois fenêtres de l'application posées sur la bannière de la marque."""
    def data(name, w=None):
        im = Image.open(OUT / f"{name}.png").convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    # Scène sans texte : ciel de nuit, soleil levant sur l'horizon, silhouette du pont
    hangers = "".join(f"M{x} {600 - 0.003 * (x - 800) ** 2:.0f}V640" for x in range(430, 1180, 30))
    scene = (f'<svg viewBox="0 0 1600 900" preserveAspectRatio="none" style="position:absolute;inset:0;width:100%;height:100%">'
             f'<defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#171C55"/>'
             f'<stop offset=".68" stop-color="#3A2E7E"/><stop offset=".71" stop-color="#6E3B88"/><stop offset=".71" stop-color="#191950"/>'
             f'<stop offset="1" stop-color="#090B26"/></linearGradient><radialGradient id="g" cx="800" cy="640" r="700" '
             f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#FF8A5B" stop-opacity=".55"/><stop offset="1" '
             f'stop-color="#E0527A" stop-opacity="0"/></radialGradient><linearGradient id="u" x1="0" y1="0" x2="0" y2="1">'
             f'<stop offset="0" stop-color="#FFE08A"/><stop offset=".5" stop-color="#FF9A4D"/><stop offset="1" stop-color="#F4545C"/>'
             f'</linearGradient></defs><rect width="1600" height="900" fill="url(#s)"/><rect width="1600" height="900" fill="url(#g)"/>'
             f'<path d="M560 640a240 240 0 0 1 480 0Z" fill="url(#u)" opacity=".9"/>'
             f'<g fill="none" stroke="#FFF3E8" stroke-linecap="round" opacity=".4"><path d="{hangers}" stroke-width="3"/>'
             f'<path d="M400 120Q800 1080 1200 120M400 120Q260 420 -20 640M1200 120Q1340 420 1620 640" stroke-width="7"/>'
             f'<path d="M400 90V700M1200 90V700" stroke-width="18"/><path d="M-20 640H1620" stroke-width="12"/></g>'
             f'<g stroke="#FF8F52" stroke-linecap="round" opacity=".5"><path d="M680 690h240" stroke-width="9"/>'
             f'<path d="M730 730h140" stroke-width="7"/></g></svg>')
    html = f"""<html><body style="margin:0;width:1600px;height:900px;overflow:hidden;position:relative;font-family:Segoe UI">
      {scene}
      <div style="position:absolute;left:0;right:0;top:84px;display:flex;justify-content:center;align-items:flex-start;gap:46px">
        <img src="{data('03-add-account')}" style="width:360px;border-radius:18px;transform:rotate(-5deg) translateY(70px);box-shadow:0 40px 80px -20px rgba(0,0,0,.7)">
        <img src="{data('01-dashboard-dark')}" style="width:400px;border-radius:20px;box-shadow:0 50px 100px -20px rgba(0,0,0,.8);position:relative;z-index:2">
        <img src="{data('06-calendar-connected')}" style="width:360px;border-radius:18px;transform:rotate(5deg) translateY(70px);box-shadow:0 40px 80px -20px rgba(0,0,0,.7)">
      </div></body></html>"""
    page_file = OUT / "_hero.html"
    page_file.write_text(html, encoding="utf-8")
    ctx = browser.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
    pg = ctx.new_page()
    pg.goto(page_file.as_uri())
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(OUT / "hero.png"))
    ctx.close()
    page_file.unlink()
    print("  hero.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--allow-file-access-from-files"])
        shoot_steps(browser)
        shoot_hero(browser)
        shoot_gif(browser)
        browser.close()


if __name__ == "__main__":
    main()
