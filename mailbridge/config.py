# -*- coding: utf-8 -*-
"""
config.py
=========
Réglages de MailBridge et liste des comptes sources, stockés dans data/config.json.
Les mots de passe n'y sont JAMAIS : chaque compte pointe vers une entrée du
Gestionnaire d'identifiants Windows (champ « cred »).

Structure du fichier
--------------------
{
  "gmail":    {"cred": "MailBridge/gmail"},
  "accounts": [ {id, name, preset, type, host, port, folders, label, enabled, cred | store,
                 expects_redirect}, ... ],
  "settings": {interval_minutes, backfill_days, min_age_minutes, max_messages_per_run,
               max_retries, mirror_seen, dedup_window_minutes, calendar_sync}
}

type = "imap"    : le compte est lu en IMAP (hôte, port, identifiant + mot de passe).
type = "outlook" : le compte est lu dans Outlook installé sur ce PC (Microsoft 365, Inserm…),
                   sans mot de passe ; « store » = nom du compte dans Outlook.
"""

from __future__ import annotations

import copy
import json
import os
import re

from . import DATA_DIR

CONFIG_FILE = DATA_DIR / "config.json"

# Fournisseurs proposés dans l'écran « Ajouter un compte ».
# color : couleur de la pastille du compte dans l'interface.
PRESETS = {
    "u-paris": {
        "name": "Université Paris Cité", "type": "imap", "host": "imap.u-paris.fr", "port": 993,
        "label": "U-Paris", "color": "#8B5CF6",
        "hint": "Votre mot de passe ENT. Identifiant : adresse complète (ou identifiant ENT seul).",
    },
    "outlook": {
        "name": "Compte Outlook (Inserm, Microsoft 365…)", "type": "outlook", "label": "Outlook",
        "color": "#0EA5E9",
        "hint": "Aucun mot de passe : MailBridge lit le compte dans Outlook installé sur ce PC. "
                "Outlook doit être ouvert.",
    },
    "yahoo": {
        "name": "Yahoo Mail", "type": "imap", "host": "imap.mail.yahoo.com", "port": 993,
        "label": "Yahoo", "color": "#7C3AED",
        "hint": "Mot de passe d'application Yahoo : Sécurité du compte > Générer un mot de passe d'application.",
    },
    "icloud": {
        "name": "iCloud Mail", "type": "imap", "host": "imap.mail.me.com", "port": 993,
        "label": "iCloud", "color": "#3B82F6",
        "hint": "Mot de passe pour app : appleid.apple.com > Connexion et sécurité.",
    },
    "orange": {
        "name": "Orange", "type": "imap", "host": "imap.orange.fr", "port": 993,
        "label": "Orange", "color": "#F97316", "hint": "Mot de passe de votre messagerie Orange.",
    },
    "free": {
        "name": "Free", "type": "imap", "host": "imap.free.fr", "port": 993,
        "label": "Free", "color": "#EF4444", "hint": "Mot de passe de votre messagerie Free.",
    },
    "gmx": {
        "name": "GMX", "type": "imap", "host": "imap.gmx.net", "port": 993,
        "label": "GMX", "color": "#1D4ED8",
        "hint": "Activez d'abord l'accès IMAP dans les paramètres GMX.",
    },
    "imap": {
        "name": "Autre (IMAP)", "type": "imap", "host": "", "port": 993,
        "label": "Mail", "color": "#64748B",
        "hint": "Serveur IMAP chiffré (SSL, port 993 en général) et mot de passe du compte.",
    },
}

DEFAULT_SETTINGS = {
    "interval_minutes": 5,        # fréquence de la tâche planifiée
    "backfill_days": 30,          # 1re passe d'un compte : rattrapage des N derniers jours
    "min_age_minutes": 3,         # laisse une redirection éventuelle livrer avant de copier
    "max_messages_per_run": 300,  # plafond par dossier et par passe
    "max_retries": 3,             # au-delà, un message en échec est abandonné (et journalisé)
    "mirror_seen": False,         # True : un message déjà lu arrive « lu » dans Gmail
    "dedup_window_minutes": 30,   # tolérance horaire de la reconnaissance des doublons
    "dedup_probe_size": 30,       # messages sondés avant un rattrapage (comptes redirigés)
    "calendar_interval_minutes": 15,  # fréquence de la synchro des agendas Outlook -> Google
    "calendar_past_days": 30,     # fenêtre synchronisée : N jours passés…
    "calendar_future_days": 180,  # … et M jours à venir
}

DEFAULT_CONFIG = {"gmail": {"cred": "MailBridge/gmail"}, "accounts": [], "calendars": [],
                  "settings": DEFAULT_SETTINGS}


def slugify(text: str) -> str:
    """'Université Paris Cité' -> 'universite-paris-cite' (identifiant de compte stable)."""
    table = str.maketrans("àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ", "aaaeeeeiioouuucAAAEEEEIIOOUUUC")
    slug = re.sub(r"[^a-z0-9]+", "-", text.translate(table).lower()).strip("-")
    return slug or "compte"


def new_account(preset_key: str, **overrides) -> dict:
    """Compte complet à partir d'un fournisseur prédéfini (valeurs modifiables)."""
    p = PRESETS.get(preset_key, PRESETS["imap"])
    acc = {
        "id": "", "name": p["name"], "preset": preset_key, "type": p["type"],
        "host": p.get("host", ""), "port": p.get("port", 993), "folders": ["INBOX"],
        "label": p["label"], "enabled": True, "expects_redirect": False,
        "cred": "", "store": "",
    }
    acc.update({k: v for k, v in overrides.items() if v is not None})
    if acc["type"] == "outlook" and acc["folders"] == ["INBOX"]:
        acc["folders"] = ["Inbox"]   # dossier par défaut d'Outlook (boîte de réception)
    return acc


def _migrate_v1() -> dict:
    """Première version (un seul compte u-paris) : on reprend ses identifiants existants."""
    from . import credentials  # import tardif : config doit rester importable partout
    conf = copy.deepcopy(DEFAULT_CONFIG)
    if credentials.exists("MailBridge/u-paris"):
        acc = new_account("u-paris", id="u-paris", cred="MailBridge/u-paris", expects_redirect=True)
        conf["accounts"].append(acc)
    return conf


def load() -> dict:
    """Charge la configuration (crée / migre si nécessaire) en complétant les valeurs manquantes."""
    try:
        conf = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        conf = _migrate_v1()
        save(conf)
    conf.setdefault("gmail", {"cred": "MailBridge/gmail"})
    conf.setdefault("accounts", [])
    conf.setdefault("calendars", [])
    settings = dict(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in conf.get("settings", {}).items() if k in DEFAULT_SETTINGS})
    conf["settings"] = settings
    for acc in conf["accounts"]:
        base = new_account(acc.get("preset", "imap"))
        base.update(acc)
        acc.update(base)
    return conf


def save(conf: dict) -> None:
    """Écrit la configuration de façon atomique."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(conf, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)


def unique_id(conf: dict, wanted: str) -> str:
    """Identifiant libre dérivé de `wanted` (ajoute -2, -3… si déjà pris)."""
    taken = {a["id"] for a in conf["accounts"]}
    base = slugify(wanted)
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def get_account(conf: dict, account_id: str) -> dict | None:
    return next((a for a in conf["accounts"] if a["id"] == account_id), None)


def new_calendar(conf: dict, store: str, label: str, target_id: str = "", target_name: str = "") -> dict:
    """Source calendrier : le calendrier principal d'un compte Outlook, copié vers un agenda Google."""
    taken = {c["id"] for c in conf["calendars"]}
    base = "cal-" + slugify(label or store)
    cid, n = base, 2
    while cid in taken:
        cid, n = f"{base}-{n}", n + 1
    return {"id": cid, "store": store, "label": label or store, "target_id": target_id,
            "target_name": target_name, "enabled": True}


def get_calendar(conf: dict, cal_id: str) -> dict | None:
    return next((c for c in conf["calendars"] if c["id"] == cal_id), None)
