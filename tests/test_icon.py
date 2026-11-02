# -*- coding: utf-8 -*-
"""Tests du symbole GmailBridge (mailbridge/icon.py) : SVG valides, icône Windows complète,
dessin adapté à la taille et fichiers de la marque à jour."""

import struct
import unittest
import xml.etree.ElementTree as ET

from mailbridge import icon


class MarkSvgTest(unittest.TestCase):
    def test_svg_bien_forme(self):
        """Les deux dessins sont du XML valide, au repère 256 x 256."""
        for small in (False, True):
            root = ET.fromstring(icon.mark_svg(small))
            self.assertEqual(root.get("viewBox"), "0 0 256 256")

    def test_identifiants_prefixes(self):
        """Deux symboles intégrés dans une même page ne partagent aucun identifiant."""
        a, b = icon.mark_svg(prefix="a"), icon.mark_svg(prefix="b")
        ids = lambda s: {e.get("id") for e in ET.fromstring(s).iter() if e.get("id")}
        self.assertFalse(ids(a) & ids(b))

    def test_svg_du_depot_a_jour(self):
        """assets/brand/*.svg correspond exactement à icon.py (relancer tools/build_brand.py sinon)."""
        self.assertEqual((icon.BRAND_DIR / "gmailbridge-mark.svg").read_text(encoding="utf-8"), icon.mark_svg(False))
        self.assertEqual((icon.BRAND_DIR / "gmailbridge-mark-small.svg").read_text(encoding="utf-8"), icon.mark_svg(True))


class RasterTest(unittest.TestCase):
    def test_taille_et_transparence(self):
        """16 px : 16 x 16 pixels RGBA, coins transparents, centre opaque."""
        px = icon.render_rgba(16)
        self.assertEqual(len(px), 16 * 16 * 4)
        self.assertEqual(px[3], 0)                              # coin haut gauche
        self.assertEqual(px[(8 * 16 + 8) * 4 + 3], 255)         # centre

    def test_dessin_simplifie_lisible_en_16px(self):
        """En 16 px, le « M » blanc ressort nettement du ciel de nuit (contraste de luminance)."""
        px = icon.render_rgba(16)
        lum = [0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2] for i in range(0, len(px), 4)]
        self.assertGreater(max(lum) - min(l for l, a in zip(lum, px[3::4]) if a == 255), 180)

    def test_ico_complet_et_a_jour(self):
        """L'icône du dépôt contient toutes les tailles et correspond à icon.py."""
        data = icon.ICO_PATH.read_bytes()
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind, count), (0, 1, len(icon.ICO_SIZES)))
        sizes = [data[6 + 16 * i] or 256 for i in range(count)]
        self.assertEqual(sizes, list(icon.ICO_SIZES))
        self.assertEqual(data[-200:], icon.png_bytes(icon.ICO_SIZES[-1])[-200:])


if __name__ == "__main__":
    unittest.main()
