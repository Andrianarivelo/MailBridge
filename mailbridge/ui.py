# -*- coding: utf-8 -*-
"""
ui.py
=====
Fenêtre de contrôle de MailBridge : interface HTML / CSS animée (dossier web/) affichée
dans une fenêtre Windows native grâce à pywebview (moteur Edge WebView2, déjà présent sur
Windows 10 / 11).

La classe Api expose à JavaScript les actions possibles (pywebview.api.<méthode>) :
état, comptes, Gmail, synchronisation, démarrage automatique… Chaque méthode renvoie un
dictionnaire simple, converti en JSON.

Lancement :  pythonw MailBridge.pyw            (raccourci Bureau / menu Démarrer)
             pythonw MailBridge.pyw --demo     (données fictives, pour captures d'écran)
"""

from __future__ import annotations

import csv
import ctypes
import os
import re
import subprocess
import sys
import webbrowser
import winreg
from datetime import datetime, timedelta

from . import ASSETS_DIR, BASE_DIR, WEB_DIR, __version__, config, credentials, engine, gcal
from .background import TASK_NAME, ensure_tray, task_enabled

# ----------------------------- Paramètres ------------------------------------
APP_TITLE = "MailBridge"
WINDOW_SIZE = (420, 730)       # px logiques (mis à l'échelle par Windows)
RECENT_ROWS = 3
ACTIONS_SHOWN = {"copié": "copié", "abandonné": "abandonné", "erreur": "erreur",
                 "ignoré_rebond_redirection": "ignoré"}
BG = {"dark": "#0B0C11", "light": "#F4F5FA"}   # doit suivre web/style.css (--bg)
# -----------------------------------------------------------------------------

_NO_WINDOW = 0x08000000


def dark_mode() -> bool:
    """Vrai si Windows est réglé en mode sombre pour les applications."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def _run(args, timeout=30):
    return subprocess.run(args, capture_output=True, creationflags=_NO_WINDOW, timeout=timeout)


def python_console() -> str:
    """python.exe à côté de pythonw.exe (pour lancer le moteur sans fenêtre)."""
    exe = sys.executable
    return exe[:-5] + ".exe" if exe.lower().endswith("w.exe") else exe


class Api:
    """Méthodes appelées par l'interface (web/app.js)."""

    def __init__(self):
        self._ledger_cache = {}
        self._window = None          # fenêtre pywebview (boîte « ouvrir un fichier »)

    # ---- lecture de l'état -------------------------------------------------
    def _ledger(self) -> list:
        """Lignes des journaux (actuel + ancien format), mises en cache par date de modification."""
        rows = []
        for path in (engine.LEDGER_FILE.with_name("journal_copies_v1.csv"), engine.LEDGER_FILE):
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue
            cached = self._ledger_cache.get(path)
            if not cached or cached[0] != mtime:
                with open(path, encoding="utf-8-sig", newline="") as fh:
                    cached = (mtime, list(csv.DictReader(fh, delimiter=";")))
                self._ledger_cache[path] = cached
            rows.extend(cached[1])
        return rows

    def snapshot(self) -> dict:
        conf = config.load()
        state = engine.load_state()
        rows = self._ledger()
        today = datetime.now().strftime("%Y-%m-%d")
        name_of = {a["id"]: a["name"] for a in conf["accounts"]}
        default_name = name_of.get("u-paris", "Université Paris Cité")
        color_of = {a["name"]: config.PRESETS.get(a.get("preset"), config.PRESETS["imap"])["color"]
                    for a in conf["accounts"]}
        copied = [r for r in rows if r.get("action") == "copié"]

        accounts = []
        for a in conf["accounts"]:
            st = state.get("accounts", {}).get(a["id"], {})
            last = st.get("last") or {}
            user = credentials.read(a["cred"])[0] if a["type"] == "imap" and a["cred"] and credentials.exists(a["cred"]) else ""
            n_today = sum(1 for r in copied if (r.get("compte") or default_name) == a["name"]
                          and r.get("horodatage", "").startswith(today))
            if not a.get("enabled", True):
                level, sub = "muted", "En pause"
            elif a["type"] == "imap" and not user:
                level, sub = "warn", "Mot de passe à saisir"
            elif last.get("error"):
                level, sub = "err", engine.friendly_error(last["error"])
            elif last.get("note"):
                level, sub = "warn", "Outlook fermé : en attente"
            else:
                level = "ok" if last else "muted"
                sub = user or (f"Via Outlook · {a['store']}" if a["type"] == "outlook" else a.get("host", ""))
            accounts.append({**{k: a.get(k) for k in ("id", "name", "preset", "type", "label", "enabled", "host",
                                                     "port", "store", "expects_redirect")},
                             "user": user, "color": color_of.get(a["name"], "#64748B"),
                             "level": level, "sub": sub, "today": n_today})

        gmail_user = credentials.read(conf["gmail"]["cred"])[0] if credentials.exists(conf["gmail"]["cred"]) else ""
        last_pass = state.get("last_pass") or {}
        autostart = task_enabled()
        interval = conf["settings"]["interval_minutes"]
        next_in = None
        if last_pass.get("time"):
            t = datetime.fromisoformat(last_pass["time"])
            nxt = t + timedelta(minutes=interval)
            while nxt < datetime.now():
                nxt += timedelta(minutes=interval)
            next_in = int((nxt - datetime.now()).total_seconds())

        # État général
        outcome = last_pass.get("outcome", "ok")
        if autostart is None:
            status = ("err", "Non installé", "Relancez l'installation de MailBridge.")
        elif autostart is False:
            status = ("muted", "En pause", "Le démarrage automatique est désactivé.")
        elif not gmail_user:
            status = ("warn", "À configurer", "Renseignez la destination Gmail.")
        elif not conf["accounts"]:
            status = ("warn", "À configurer", "Ajoutez un premier compte.")
        elif outcome != "ok":
            status = ("err", "Erreur", outcome)
        elif any(a["level"] == "err" for a in accounts):
            status = ("warn", "À vérifier", "Un compte a rencontré une erreur.")
        elif last_pass.get("time"):
            when = datetime.fromisoformat(last_pass["time"])
            label = when.strftime("%H:%M") if when.date() == datetime.now().date() else when.strftime("%d/%m %H:%M")
            status = ("ok", "Actif", f"Dernière passe à {label} · toutes les {interval} min")
        else:
            status = ("muted", "En attente", "Première passe dans quelques minutes.")

        recent = []
        for r in reversed(rows):
            if r.get("action") in ACTIONS_SHOWN and len(recent) < RECENT_ROWS:
                acc_name = r.get("compte") or default_name
                sender = (r.get("expediteur") or "").split("<")[0].strip(' "') or r.get("expediteur", "")
                recent.append({"key": f"{r.get('horodatage')}|{r.get('uid')}|{acc_name}",
                               "time": (r.get("horodatage") or "")[11:16], "color": color_of.get(acc_name, "#8B5CF6"),
                               "sender": sender, "subject": r.get("objet", ""), "action": ACTIONS_SHOWN[r["action"]]})
        calendar = self._calendar_snapshot(conf, state)
        return {
            "status": dict(zip(("level", "title", "detail"), status)),
            "stats": {"today": sum(1 for r in copied if r.get("horodatage", "").startswith(today)),
                      "total": len(copied)},
            "interval": interval, "next_in": next_in, "version": __version__,
            "gmail": {"address": gmail_user}, "accounts": accounts,
            "calendar": calendar, "recent": recent, "autostart": bool(autostart),
        }

    def _calendar_snapshot(self, conf: dict, state: dict) -> dict:
        """État de la synchro des agendas pour la ligne « Google Agenda » et son panneau."""
        has_client, is_connected = gcal.load_client() is not None, gcal.connected()
        sources = []
        for c in conf.get("calendars", []):
            last = state.get("calendars", {}).get(c["id"], {}).get("last") or {}
            stats = last.get("stats") or {}
            sources.append({**c, "error": last.get("error"), "count": last.get("count"),
                            "changes": sum(v for k, v in stats.items() if k != "inchangé")})
        info = state.get("calendar_pass") or {}
        if not has_client:
            level, text = "warn", "À connecter : accès Google à créer (5 min)"
        elif not is_connected:
            level, text = "warn", "À connecter : connexion Google"
        elif not sources:
            level, text = "warn", f"Connecté ({gcal.account_email()}) : ajoutez un calendrier"
        elif info.get("error") or any(s["error"] for s in sources):
            level, text = "err", info.get("error") or next(s["error"] for s in sources if s["error"])
        elif info.get("note"):
            level, text = "warn", "Outlook fermé : en attente"
        elif info.get("time"):
            when = datetime.fromisoformat(info["time"]).strftime("%H:%M")
            n = sum(s["count"] or 0 for s in sources)
            text = f"{len(sources)} calendrier{'s' if len(sources) > 1 else ''} · {n} événements · {when}"
            level = "ok"
        else:
            level, text = "muted", "Première synchro dans quelques minutes"
        return {"level": level, "text": engine.friendly_error(text), "client": has_client,
                "connected": is_connected, "email": gcal.account_email(), "sources": sources}

    # ---- Google Agenda -----------------------------------------------------
    def google_import_client(self) -> dict:
        """Boîte « Ouvrir » : importe le fichier client_secret_….json téléchargé depuis Google Cloud."""
        import webview
        kind = webview.FileDialog.OPEN if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG
        paths = self._window.create_file_dialog(kind, file_types=("Fichier client Google (*.json)",))
        if not paths:
            return {"ok": False, "message": ""}
        try:
            with open(paths[0], encoding="utf-8") as fh:
                gcal.save_client_from_json(fh.read())
            return {"ok": True, "message": "Accès Google importé"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def google_save_client(self, client_id: str, client_secret: str) -> dict:
        try:
            gcal.save_client(client_id, client_secret)
            return {"ok": True, "message": "Accès Google enregistré"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def google_connect(self) -> dict:
        """Ouvre la connexion Google dans le navigateur et attend (5 min max)."""
        try:
            email = gcal.authorize()
            return {"ok": True, "message": f"Connecté : {email}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def google_disconnect(self) -> dict:
        gcal.disconnect()
        return {"ok": True}

    def google_calendars(self) -> dict:
        try:
            return {"ok": True, "calendars": gcal.GoogleCalendar().calendars()}
        except Exception as exc:
            return {"ok": False, "calendars": [], "message": str(exc)}

    def save_calendar(self, data: dict) -> dict:
        """Ajoute ou modifie une source : calendrier d'un compte Outlook -> agenda Google."""
        conf = config.load()
        store, label = (data.get("store") or "").strip(), (data.get("label") or "").strip()
        if not store:
            return {"ok": False, "message": "Choisissez le compte Outlook (Outlook doit être ouvert)."}
        target_id = data.get("target_id") or ""
        target_name = data.get("target_name") or ""
        src = config.get_calendar(conf, data.get("id") or "")
        if src is None:
            src = config.new_calendar(conf, store, label, target_id, target_name)
            conf["calendars"].append(src)
        else:
            src.update(store=store, label=label or src["label"], target_id=target_id, target_name=target_name)
        config.save(conf)
        return {"ok": True, "message": "Calendrier enregistré : première synchro en cours…", "id": src["id"]}

    def delete_calendar(self, cal_id: str) -> dict:
        conf = config.load()
        src = config.get_calendar(conf, cal_id)
        if src:
            conf["calendars"].remove(src)
            config.save(conf)
        return {"ok": True}

    def sync_calendars_now(self) -> dict:
        code, out = self._engine("--calendar-only", timeout=900)
        lines = re.findall(r"Agenda (\S+) : (.*)", out)
        problems = re.findall(r"WARNING\s+Agenda : (.*)", out)
        if problems:
            return {"ok": False, "message": engine.friendly_error(problems[-1])}
        created = sum(int(n) for _, s in lines for n in re.findall(r"créé=(\d+)", s))
        changed = sum(int(n) for _, s in lines for n in re.findall(r"(?:modifié|supprimé|adopté)=(\d+)", s))
        return {"ok": True, "message": f"Agendas à jour · {created} ajoutés, {changed} mis à jour"
                if lines else "Agendas à jour"}

    def presets(self) -> dict:
        return config.PRESETS

    def outlook_stores(self) -> dict:
        try:
            from . import outlook_source
            return {"ok": True, "stores": outlook_source.list_stores()}
        except Exception as exc:
            return {"ok": False, "stores": [], "message": str(exc)}

    # ---- comptes -----------------------------------------------------------
    def save_account(self, data: dict) -> dict:
        """Crée ou modifie un compte, enregistre son mot de passe, puis teste la connexion."""
        conf = config.load()
        acc = config.get_account(conf, data.get("id") or "")
        new = acc is None
        if new:
            acc = config.new_account(data.get("preset", "imap"))
            acc["id"] = config.unique_id(conf, data.get("name") or acc["name"])
        for key in ("name", "label", "host", "port", "store", "expects_redirect"):
            if data.get(key) not in (None, ""):
                acc[key] = data[key]
        acc["expects_redirect"] = bool(data.get("expects_redirect"))
        if acc["type"] == "imap":
            if not acc.get("host"):
                return {"ok": False, "message": "Indiquez le serveur IMAP."}
            user, password = (data.get("user") or "").strip(), data.get("password") or ""
            acc["cred"] = acc.get("cred") or f"MailBridge/acct/{acc['id']}"
            if not user:
                return {"ok": False, "message": "Indiquez l'identifiant."}
            if not password and credentials.exists(acc["cred"]):
                password = credentials.read(acc["cred"])[1]   # mot de passe inchangé
            if not password:
                return {"ok": False, "message": "Indiquez le mot de passe."}
            credentials.write(acc["cred"], user, password)
        elif not acc.get("store"):
            return {"ok": False, "message": "Choisissez le compte Outlook (Outlook doit être ouvert)."}
        if new:
            conf["accounts"].append(acc)
        config.save(conf)
        good, message = engine.test_account(acc)
        return {"ok": good, "message": message, "saved": True, "id": acc["id"]}

    def delete_account(self, account_id: str) -> dict:
        conf = config.load()
        acc = config.get_account(conf, account_id)
        if acc:
            conf["accounts"].remove(acc)
            config.save(conf)
            if acc.get("cred", "").startswith("MailBridge/acct/"):
                credentials.delete(acc["cred"])
        return {"ok": True}

    def set_account_enabled(self, account_id: str, enabled: bool) -> dict:
        conf = config.load()
        acc = config.get_account(conf, account_id)
        if acc:
            acc["enabled"] = bool(enabled)
            config.save(conf)
        return {"ok": bool(acc)}

    def save_gmail(self, address: str, password: str) -> dict:
        conf = config.load()
        address = (address or "").strip()
        if not address:
            return {"ok": False, "message": "Indiquez l'adresse Gmail."}
        if not password and credentials.exists(conf["gmail"]["cred"]):
            password = credentials.read(conf["gmail"]["cred"])[1]
        if not password:
            return {"ok": False, "message": "Collez le mot de passe d'application (16 lettres)."}
        credentials.write(conf["gmail"]["cred"], address, password)
        good, message = engine.test_gmail(conf)
        return {"ok": good, "message": message}

    # ---- actions -----------------------------------------------------------
    def _engine(self, *args, timeout=1800):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        r = subprocess.run([python_console(), "-m", "mailbridge.engine", *args], cwd=str(BASE_DIR),
                           capture_output=True, creationflags=_NO_WINDOW, env=env, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")

    def sync_now(self) -> dict:
        code, out = self._engine()
        copied = sum(int(n) for n in re.findall(r"copié=(\d+)", out))
        problems = re.findall(r"(?:ERROR|WARNING)\s+(.*)", out)
        if "déjà en cours" in out:
            return {"ok": True, "message": "Une passe est déjà en cours, patientez un instant."}
        if code == 0:
            msg = f"{copied} message{'s' if copied > 1 else ''} copié{'s' if copied > 1 else ''}" if copied \
                else "Tout est à jour"
            return {"ok": True, "message": msg + (f" · {problems[-1]}" if problems else "")}
        return {"ok": False, "message": engine.friendly_error(problems[-1] if problems else out.strip()[-200:])}

    def check(self) -> dict:
        code, out = self._engine("--check", timeout=300)
        return {"ok": code == 0, "message": out.strip()}

    def set_autostart(self, enabled: bool) -> dict:
        r = _run(["schtasks", "/Change", "/TN", TASK_NAME, "/ENABLE" if enabled else "/DISABLE"])
        return {"ok": r.returncode == 0}

    def open_journal(self) -> dict:
        os.startfile(str(engine.LEDGER_FILE if engine.LEDGER_FILE.exists() else engine.DATA_DIR))
        return {}

    def open_folder(self) -> dict:
        os.startfile(str(BASE_DIR))
        return {}

    def open_url(self, url: str) -> dict:
        if url.startswith("https://"):
            webbrowser.open(url)
        return {}


# =============================================================================
# Fenêtre
# =============================================================================

def _style_window(dark: bool) -> None:
    """Barre de titre de la couleur du fond (Windows 11) et icône MailBridge."""
    user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    hwnd = user32.FindWindowW(None, APP_TITLE)
    if not hwnd:
        return
    bg = BG["dark" if dark else "light"].lstrip("#")
    colorref = ctypes.c_int(int(bg[4:6] + bg[2:4] + bg[0:2], 16))       # 0x00BBGGRR
    for attr, value in ((20, ctypes.c_int(1 if dark else 0)), (35, colorref)):  # mode sombre, couleur titre
        dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    ico = ASSETS_DIR / "mailbridge.ico"
    if ico.exists():
        for size, which in ((32, 1), (16, 0)):   # ICON_BIG, ICON_SMALL
            hicon = user32.LoadImageW(None, str(ico), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
            if hicon:
                user32.SendMessageW(hwnd, 0x80, which, hicon)              # WM_SETICON


def already_running() -> bool:
    """Une seule fenêtre : si elle existe déjà, on la ramène au premier plan."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    already_running.mutex = k32.CreateMutexW(None, False, "Local\\MailBridgeApp")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        hwnd = ctypes.windll.user32.FindWindowW(None, APP_TITLE)
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        return True
    return False


def main(argv=None) -> None:
    import webview  # pywebview

    argv = sys.argv[1:] if argv is None else argv
    demo = next((a[2:] for a in argv if a.startswith("--demo")), "")   # --demo, --demo-add, --demo-form
    if not demo:
        ensure_tray()
    if not demo and already_running():
        return
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Andrianarivelo.MailBridge")
    dark = dark_mode()
    url = (WEB_DIR / "index.html").as_uri() + (f"#{demo}" if demo else "")
    api = None if demo else Api()
    window = webview.create_window(APP_TITLE, url=url, js_api=api,
                                   width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], resizable=False,
                                   background_color=BG["dark" if dark else "light"])
    if api:
        api._window = window
    window.events.shown += lambda: _style_window(dark)
    webview.start(private_mode=True)
