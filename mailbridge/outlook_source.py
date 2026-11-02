# -*- coding: utf-8 -*-
"""
outlook_source.py
=================
Lecture des comptes déjà configurés dans Outlook (classique) sur ce PC, sans mot de passe.

Pourquoi ?
    Microsoft 365 (Inserm, UNIGE, beaucoup d'universités) a désactivé la connexion IMAP par
    mot de passe : un script ne peut plus lire ces boîtes en IMAP sans application déclarée
    par l'administrateur. Outlook, lui, y est déjà connecté. On lui demande donc les messages
    via son interface d'automatisation (COM), puis on reconstruit un e-mail standard (MIME).

Fonctionnement
    * Outlook doit être OUVERT : s'il est fermé, ces comptes sont simplement ignorés pendant la
      passe (on ne démarre jamais Outlook en cachette).
    * Lecture seule : aucun message n'est modifié, déplacé ni marqué comme lu.
    * Le message reconstruit garde les en-têtes Internet d'origine (De, À, Objet, Date,
      Message-ID…), le texte, la version HTML, les pièces jointes et les images intégrées.
"""

from __future__ import annotations

import mimetypes
import re
import subprocess
import tempfile
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import HeaderParser
from email.utils import format_datetime, make_msgid
from pathlib import Path

# Propriétés MAPI (identifiants numériques documentés par Microsoft)
PR_TRANSPORT_HEADERS = "http://schemas.microsoft.com/mapi/proptag/0x007D001F"
PR_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
PR_ATTACH_CONTENT_ID = "http://schemas.microsoft.com/mapi/proptag/0x3712001F"
PR_SMTP_ADDRESS = "http://schemas.microsoft.com/mapi/proptag/0x39FE001F"

OL_MAIL_ITEM = 43            # classe d'un e-mail (les invitations, rapports… sont ignorés)
OL_FORMAT_HTML = 2
OL_ATTACH_BY_VALUE = 1
KEPT_HEADERS = ("From", "Sender", "Reply-To", "To", "Cc", "Subject", "Date", "Message-ID",
                "In-Reply-To", "References")


class OutlookNotRunning(Exception):
    """Outlook est fermé : les comptes Outlook sont ignorés pour cette passe."""


def outlook_running() -> bool:
    """Vrai si OUTLOOK.EXE tourne (tasklist, sans fenêtre)."""
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq OUTLOOK.EXE", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, errors="replace", timeout=30, creationflags=0x08000000)
    return "outlook.exe" in out.stdout.lower()


def connect():
    """Espace MAPI d'Outlook déjà ouvert (lève OutlookNotRunning sinon).

    Outlook n'existe qu'en un exemplaire : s'il tourne, Dispatch s'y rattache. On vérifie d'abord
    qu'il tourne pour ne jamais le démarrer en cachette.
    """
    if not outlook_running():
        raise OutlookNotRunning("Outlook est fermé : comptes Outlook ignorés pour cette passe.")
    try:
        import pythoncom
        import win32com.client  # pywin32
        pythoncom.CoInitialize()          # nécessaire hors du fil principal (fenêtre GmailBridge)
        app = win32com.client.Dispatch("Outlook.Application")
        return app.GetNamespace("MAPI")
    except Exception as exc:
        raise OutlookNotRunning(f"Outlook ne répond pas : {exc}") from exc


def list_stores() -> list[str]:
    """Noms des comptes (magasins) visibles dans Outlook, pour l'écran « Ajouter un compte »."""
    ns = connect()
    return [s.DisplayName for s in ns.Stores]


def _find_folder(store, name: str):
    """Dossier `name` du compte ; 'Inbox' = boîte de réception quelle que soit la langue."""
    if name.lower() in ("inbox", "boîte de réception"):
        return store.GetDefaultFolder(6)          # olFolderInbox
    for folder in store.GetRootFolder().Folders:
        if folder.Name.lower() == name.lower():
            return folder
    raise KeyError(f"Dossier « {name} » introuvable dans {store.DisplayName}")


def get_folder(ns, store_name: str, folder_name: str):
    for store in ns.Stores:
        if store.DisplayName.lower() == store_name.lower():
            return _find_folder(store, folder_name)
    raise KeyError(f"Compte « {store_name} » introuvable dans Outlook")


def local_naive(dt) -> datetime:
    """Les dates COM arrivent marquées UTC alors qu'elles sont en heure locale : on retire le fuseau."""
    return datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def iter_items_since(folder, since: datetime):
    """Messages du dossier reçus depuis `since`, du plus ancien au plus récent.

    On parcourt la liste triée du plus récent au plus ancien et on s'arrête dès qu'on passe
    sous `since` : rapide même sur une grosse boîte, et indépendant de la langue de Windows.
    """
    items = folder.Items
    items.Sort("[ReceivedTime]", True)
    picked = []
    item = items.GetFirst()
    while item is not None:
        try:
            if item.Class == OL_MAIL_ITEM:
                received = local_naive(item.ReceivedTime)
                if received < since:
                    break
                picked.append((received, item.EntryID, item))
        except Exception:
            pass  # élément illisible (brouillon corrompu…) : on l'ignore
        item = items.GetNext()
    picked.sort(key=lambda t: t[0])
    return picked


def _unfold(value: str) -> str:
    return re.sub(r"\r?\n[ \t]+", " ", value).strip()


def _smtp_of(address_entry) -> str:
    """Adresse SMTP réelle d'un expéditeur Exchange (sinon son adresse telle quelle)."""
    try:
        if address_entry.Type == "EX":
            user = address_entry.GetExchangeUser()
            if user is not None:
                return user.PrimarySmtpAddress
            return address_entry.PropertyAccessor.GetProperty(PR_SMTP_ADDRESS)
        return address_entry.Address
    except Exception:
        return ""


def item_to_mime(item) -> bytes:
    """Reconstruit un e-mail standard (RFC 5322 / MIME) à partir d'un message Outlook."""
    pa = item.PropertyAccessor
    try:
        raw_headers = pa.GetProperty(PR_TRANSPORT_HEADERS) or ""
    except Exception:
        raw_headers = ""
    parsed = HeaderParser(policy=policy.default).parsestr(raw_headers) if raw_headers else None

    msg = EmailMessage()
    if parsed is not None:
        for name in KEPT_HEADERS:
            for value in parsed.get_all(name, []) or []:
                try:
                    msg[name] = _unfold(str(value))
                except Exception:
                    pass
    # Messages internes sans en-têtes Internet : on les complète depuis Outlook
    if "From" not in msg:
        sender = _smtp_of(item.Sender) if item.Sender is not None else ""
        msg["From"] = f'"{item.SenderName}" <{sender}>' if sender else item.SenderName or "inconnu"
    if "To" not in msg and item.To:
        msg["To"] = item.To
    if "Cc" not in msg and item.CC:
        msg["Cc"] = item.CC
    if "Subject" not in msg:
        msg["Subject"] = item.Subject or ""
    if "Date" not in msg:
        msg["Date"] = format_datetime(local_naive(item.ReceivedTime).astimezone())
    if "Message-ID" not in msg:
        try:
            mid = pa.GetProperty(PR_INTERNET_MESSAGE_ID)
        except Exception:
            mid = ""
        msg["Message-ID"] = mid or make_msgid(domain="mailbridge.local")

    msg.set_content(item.Body or "")
    html = item.HTMLBody if item.BodyFormat == OL_FORMAT_HTML else None
    if html:
        msg.add_alternative(html, subtype="html")

    with tempfile.TemporaryDirectory(prefix="mailbridge_") as tmp:
        for i in range(1, item.Attachments.Count + 1):
            att = item.Attachments.Item(i)
            if att.Type != OL_ATTACH_BY_VALUE:
                continue
            name = att.FileName or f"piece_jointe_{i}"
            safe = re.sub(r"[^\w.\- ]", "_", name)
            path = Path(tmp) / f"{i}_{safe}"
            att.SaveAsFile(str(path))
            data = path.read_bytes()
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)
            try:
                cid = att.PropertyAccessor.GetProperty(PR_ATTACH_CONTENT_ID)
            except Exception:
                cid = ""
            html_part = msg.get_body(("html",)) if html else None
            if cid and html_part is not None and f"cid:{cid}" in html:
                html_part.add_related(data, maintype, subtype, cid=f"<{cid}>", filename=name)
            else:
                msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes(policy=policy.SMTP)
