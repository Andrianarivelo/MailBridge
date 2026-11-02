# -*- coding: utf-8 -*-
"""
build_release.py
================
Compile et vérifie une release de GmailBridge, puis (avec --publish) la publie sur GitHub.

Étapes, chacune bloquante en cas d'échec :
    1. dépôt propre (rien de non commité) et version lue dans mailbridge/__init__.py
    2. tests hors ligne (unittest)
    3. compilation de tout le code Python (py_compile) et analyse syntaxique de install.ps1 (sans BOM)
    4. archive dist/GmailBridge-<version>.zip (git archive : seuls les fichiers versionnés,
       donc jamais data/ ni identifiants), contrôle de son contenu
    5. Install-GmailBridge.cmd, notes de version (extraites de CHANGELOG.md) et SHA256SUMS.txt

    .venv\\Scripts\\python tools/build_release.py              # compile et vérifie (dist/)
    .venv\\Scripts\\python tools/build_release.py --publish    # + tag vX.Y.Z et release GitHub (gh)
"""

from __future__ import annotations

import argparse
import hashlib
import py_compile
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# ----------------------------- Paramètres ------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
NAME = "GmailBridge"
RELEASE_TITLE = "GmailBridge {v} · Sunrise 🌅"
MUST_CONTAIN = ["GmailBridge.pyw", "install.ps1", "Install-GmailBridge.cmd", "Uninstall-GmailBridge.cmd",
                "requirements.txt", "mailbridge/engine.py", "mailbridge/web/index.html", "mailbridge/web/icons.js",
                "mailbridge/web/fonts/Sora-Variable.ttf", "assets/gmailbridge.ico", "assets/brand/gmailbridge-mark.svg"]
MUST_NOT_CONTAIN = ["data/", ".venv/", ".tools/", "NOTES_SESSION.md"]
# -----------------------------------------------------------------------------


def step(text: str) -> None:
    print(f"\n> {text}")


def run(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace", **kw)


def fail(text: str) -> None:
    print(f"  ÉCHEC : {text}")
    sys.exit(1)


def version() -> str:
    m = re.search(r'__version__ = "([^"]+)"', (ROOT / "mailbridge" / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1)


def release_notes(v: str) -> str:
    """Section de CHANGELOG.md pour cette version (titre exclu)."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(v)}\][^\n]*\n(.*?)(?=^## \[|^\[)", text, re.S | re.M)
    if not m:
        fail(f"aucune section [{v}] dans CHANGELOG.md")
    return m.group(1).strip() + "\n"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description="Compile (et publie) une release de GmailBridge.")
    ap.add_argument("--publish", action="store_true", help="crée le tag et la release GitHub (gh)")
    ap.add_argument("--allow-dirty", action="store_true", help="accepte des modifications non commitées")
    args = ap.parse_args()
    v = version()
    tag = f"v{v}"
    print(f"{NAME} {v}")

    step("1. Dépôt")
    dirty = run(["git", "status", "--porcelain"]).stdout.strip()
    if dirty and not args.allow_dirty:
        fail("modifications non commitées :\n" + dirty)
    commit = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    print(f"  commit {commit}, tag {tag}")

    step("2. Tests hors ligne")
    t = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"])
    summary = [l for l in t.stderr.splitlines() if l.startswith(("Ran ", "OK", "FAILED"))]
    print("  " + " · ".join(summary))
    if t.returncode:
        print(t.stderr[-3000:])
        fail("des tests échouent")

    step("3. Compilation et syntaxe")
    files = [ROOT / f for f in run(["git", "ls-files", "*.py", "*.pyw"]).stdout.split()]
    for f in files:
        try:
            py_compile.compile(str(f), doraise=True, cfile=str(DIST / "_pyc" / (f.name + "c")))
        except py_compile.PyCompileError as exc:
            fail(str(exc))
    shutil.rmtree(DIST / "_pyc", ignore_errors=True)
    print(f"  {len(files)} fichiers Python compilés")
    ps1 = ROOT / "install.ps1"
    if ps1.read_bytes().startswith(b"\xef\xbb\xbf"):
        fail("install.ps1 commence par un BOM (casse « irm | iex »)")
    parse = run(["powershell", "-NoProfile", "-Command",
                 f"$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('{ps1}',[ref]$null,[ref]$e); $e.Count"])
    if parse.stdout.strip() != "0":
        fail(f"install.ps1 : erreurs de syntaxe ({parse.stdout.strip()} {parse.stderr.strip()})")
    print("  install.ps1 : syntaxe valide, sans BOM")

    step("4. Archive")
    DIST.mkdir(exist_ok=True)
    zpath = DIST / f"{NAME}-{v}.zip"
    a = run(["git", "archive", "--format=zip", f"--prefix={NAME}-{v}/", "-o", str(zpath), "HEAD"])
    if a.returncode:
        fail(a.stderr)
    with zipfile.ZipFile(zpath) as z:
        names = [n.split("/", 1)[1] for n in z.namelist() if "/" in n]
    missing = [m for m in MUST_CONTAIN if m not in names]
    leaked = [n for n in names if any(n.startswith(x) or n == x for x in MUST_NOT_CONTAIN)]
    if missing or leaked:
        fail(f"contenu inattendu : manquants {missing}, interdits {leaked}")
    print(f"  {zpath.name} : {len(names)} fichiers, {zpath.stat().st_size / 1e6:.1f} Mo, contenu vérifié")

    step("5. Fichiers joints")
    shutil.copy2(ROOT / "Install-GmailBridge.cmd", DIST / "Install-GmailBridge.cmd")
    notes = DIST / "RELEASE_NOTES.md"
    install = (f"### 📦 Install

"
               f"* **Easiest:** download `{NAME}-{v}.zip`, unzip it where the app should live, double-click "
               f"`Install-GmailBridge.cmd`.
"
               f"* **Or** download just `Install-GmailBridge.cmd` and run it: it fetches the latest version for you.
"
               f"* **Or** in PowerShell: `irm https://raw.githubusercontent.com/Andrianarivelo/MailBridge/main/install.ps1 | iex`

"
               f"Windows 10 / 11, no admin rights. Checksums are in `SHA256SUMS.txt`.

")
    notes.write_text(install + release_notes(v), encoding="utf-8")
    assets = [zpath, DIST / "Install-GmailBridge.cmd"]
    sums = DIST / "SHA256SUMS.txt"
    sums.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in assets), encoding="utf-8")
    for p in assets + [sums, notes]:
        print(f"  {p.relative_to(ROOT)}")

    if not args.publish:
        print(f"\nRelease prête dans dist/. Pour publier : python tools/build_release.py --publish")
        return

    step("6. Publication GitHub")
    if run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"]).returncode == 0:
        fail(f"le tag {tag} existe déjà")
    ahead = run(["git", "rev-list", "--count", "origin/main..HEAD"]).stdout.strip()
    if ahead != "0":
        fail(f"{ahead} commit(s) non poussé(s) : poussez main d'abord")
    for cmd in (["git", "tag", "-a", tag, "-m", RELEASE_TITLE.format(v=v)], ["git", "push", "origin", tag]):
        r = run(cmd)
        if r.returncode:
            fail(r.stderr)
    r = run(["gh", "release", "create", tag, *map(str, assets + [sums]), "--title", RELEASE_TITLE.format(v=v),
             "--notes-file", str(notes), "--latest"])
    if r.returncode:
        fail(r.stderr)
    print(f"  {r.stdout.strip()}")


if __name__ == "__main__":
    main()
