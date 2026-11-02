# Marque GmailBridge

<img src="gmailbridge-lockup.svg" height="72" alt="GmailBridge">

Un pont suspendu au lever du soleil. Les pylônes et le câble porteur (une parabole)
dessinent un **M**, qui est aussi le rabat d'une enveloppe. Le tablier sert d'horizon, et le
soleil, c'est-à-dire le courrier qui arrive, se lève derrière le pont. La charte complète est dans
[`gmailbridge-charte.svg`](gmailbridge-charte.svg).

| Fichier | Usage |
|---|---|
| `gmailbridge-mark.svg` | symbole détaillé, 48 px et plus |
| `gmailbridge-mark-small.svg` | symbole simplifié, 40 px et moins (barre des tâches, notification) |
| `gmailbridge-glyph.svg` | symbole monochrome sans fond, suit `currentColor` |
| `gmailbridge-wordmark(-dark).svg` | logotype seul, fond clair (sombre) |
| `gmailbridge-lockup(-dark).svg` | symbole, logotype et signature |
| `gmailbridge-banner.svg` | bannière 1200 × 360 (en-tête du README) |
| `icons/*.svg` | pictogrammes de l'interface (grille 24, trait 1,75) |
| `../gmailbridge.ico` | icône Windows, 10 tailles de 16 à 256 px |

## Règles

* **Zone de protection** : autour du symbole, laisser au moins un quart de sa largeur.
* **Taille minimale** : 16 px pour le symbole simplifié, 48 px pour le détaillé, 14 px de hauteur
  pour le logotype.
* **Couleurs** : nuit `#141A3F`, ciel `#3A2E7E`, soleil `#FFD37A` → `#FF8A4C` → `#F2535B`,
  acier `#FFF3E8`, papier `#F4F1EC`. Les états de l'interface respectent le contraste WCAG AA
  (voir `docs/redesign/contrastes_wcag.csv`).
* **À éviter** : déformer le symbole, recolorer le soleil, séparer le soleil du « i » du logotype,
  poser le symbole détaillé sous 48 px.

## Régénérer

Toute la marque est produite par du code : rien n'est dessiné à la main dans un éditeur.

```powershell
uv run --with fonttools python tools/build_brand.py
```

`mailbridge/icon.py` est l'unique source du symbole : il écrit les SVG et rastérise l'icône `.ico`
en Python pur. `tools/build_brand.py` ajoute le logotype (police Sora vectorisée, licence SIL OFL),
les compositions, la bannière, la charte et `mailbridge/web/icons.js`.

> **Nom de marque** : « Gmail » est une marque de Google. Pour un usage personnel, aucun souci. Pour une
> diffusion publique, les règles de Google déconseillent d'utiliser leurs marques dans un nom de produit
> qui suggère une affiliation. Le symbole évite volontairement les couleurs et la forme du logo Gmail.
