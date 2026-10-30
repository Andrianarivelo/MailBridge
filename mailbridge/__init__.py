# -*- coding: utf-8 -*-
"""
MailBridge
==========
Rassemble plusieurs boîtes mail (Exchange universitaire, Inserm / Microsoft 365 via
Outlook, Yahoo, iCloud, Orange…) dans une seule boîte Gmail, et copie les calendriers
Outlook dans Google Agenda. Une seule application, aucun outil tiers.

Modules
    config          réglages, comptes et calendriers (data/config.json)
    credentials     coffre d'identifiants Windows (aucun mot de passe en clair)
    engine          moteur : une passe = mails de chaque compte -> Gmail, puis agendas
    outlook_source  lecture des comptes configurés dans Outlook (sans mot de passe)
    gcal            connexion OAuth et API Google Agenda (bibliothèque standard seulement)
    calendar_sync   synchronisation Outlook -> Google Agenda (création, mise à jour, suppression)
    icon            icône de l'application, dessinée en Python pur
    ui              fenêtre de contrôle (HTML/CSS animé dans une fenêtre native)
"""

from pathlib import Path

__version__ = "2.0.0"

PACKAGE_DIR = Path(__file__).resolve().parent
BASE_DIR = PACKAGE_DIR.parent                 # dossier d'installation
DATA_DIR = BASE_DIR / "data"                  # config, état, journaux (jamais versionné)
WEB_DIR = PACKAGE_DIR / "web"                 # interface HTML / CSS / JS
ASSETS_DIR = BASE_DIR / "assets"
