# -*- coding: utf-8 -*-
"""
engine.py
=========
Moteur de MailBridge : une « passe » copie dans Gmail les nouveaux messages de chaque compte
source activé, puis vérifie que la synchro calendrier tourne.

Pourquoi copier plutôt que rediriger ?
    Quand un serveur réexpédie un mail venu de l'extérieur, Gmail voit un expéditeur
    (ex. @sorbonne-universite.fr) arriver d'un serveur tiers : SPF / DKIM échouent et Gmail
    rejette le message (« 550 5.7.30 »). MailBridge LIT le message à la source puis le DÉPOSE
    directement dans Gmail (IMAP APPEND) : un dépôt n'est pas une réception, aucun contrôle
    SPF / DKIM ne s'applique, rien n'est perdu. Expéditeur, date et fil sont conservés.

Garanties
    * Lecture seule à la source (IMAP EXAMINE + BODY.PEEK, Outlook en lecture seule).
    * Pas de doublon : un message déjà présent dans Gmail (même Message-ID, ou même
      expéditeur + objet + heure, car certaines redirections réécrivent le Message-ID)
      n'est pas recopié.
    * Reprise sûre : progression mémorisée par compte dans data/state.json.
    * Traçabilité : chaque décision est écrite dans data/journal_copies.csv.

Ligne de commande
    python -m mailbridge.engine              une passe complète (mode tâche planifiée)
    python -m mailbridge.engine --check      teste Gmail et chaque compte
    python -m mailbridge.engine --dry-run    simulation : rien n'est écrit dans Gmail
    python -m mailbridge.engine --account ID --reset-state   refait le rattrapage d'un compte
"""

from __future__ import annotations

import argparse
import copy
import csv
import imaplib
import json
import logging
import logging.handlers
import os
import re
import ssl
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from email import policy
from email.parser import BytesHeaderParser
from email.utils import parseaddr

from . import DATA_DIR, calendar_sync, config, credentials, gcal, outlook_source

# =============================================================================
# PARAMÈTRES FIXES (les réglages modifiables sont dans data/config.json)
# =============================================================================
GMAIL_HOST = "imap.gmail.com"
GMAIL_PORT = 993
GMAIL_TARGET_MAILBOX = "INBOX"
NETWORK_TIMEOUT_S = 60

STATE_FILE = DATA_DIR / "state.json"
LEDGER_FILE = DATA_DIR / "journal_copies.csv"
SIMULATION_FILE = DATA_DIR / "simulation.csv"
LOG_FILE = DATA_DIR / "mailbridge.log"
LOCK_FILE = DATA_DIR / "mailbridge.lock"
LOCK_STALE_MINUTES = 30
# =============================================================================

log = logging.getLogger("mailbridge")

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_APPENDUID_RE = re.compile(rb"APPENDUID\s+\d+\s+(\d+)", re.I)
_LIST_RE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.+)$')
_MSGID_RE = re.compile(r"<([^<>\s]+)>")


class BridgeError(Exception):
    """Erreur bloquante pour la passe en cours (message lisible par l'utilisateur)."""


# =============================================================================
# Utilitaires IMAP
# =============================================================================

def imap_quote(text: str) -> str:
    """Met une chaîne entre guillemets IMAP (échappe \\ et ")."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def imap_date(d) -> str:
    """Date au format IMAP, ex. 29-Oct-2026 (indépendant de la langue de Windows)."""
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def ok(result, what: str):
    """Vérifie une réponse (typ, data) d'imaplib ; lève IMAP4.error si elle n'est pas OK."""
    typ, data = result
    if typ != "OK":
        raise imaplib.IMAP4.error(f"{what} : {typ} {data!r}")
    return data


def normalize_message_id(value: str | None) -> str | None:
    """'<abc@x.fr>' -> 'abc@x.fr' ; None si absent ou inutilisable."""
    if not value:
        return None
    m = _MSGID_RE.search(value)
    if m:
        return m.group(1)
    value = value.strip()
    return value if value and " " not in value else None


def connect(host: str, port: int, cred_target: str, *, strip_spaces: bool = False) -> imaplib.IMAP4_SSL:
    """Connexion IMAP chiffrée, authentifiée avec l'identifiant Windows `cred_target`."""
    user, password = credentials.read(cred_target)
    if strip_spaces and re.fullmatch(r"[A-Za-z]{4}( ?[A-Za-z]{4}){3}", password.strip()):
        password = password.replace(" ", "")  # mot de passe d'application collé en groupes de 4 lettres
    conn = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=NETWORK_TIMEOUT_S)
    try:
        if "AUTH=PLAIN" in conn.capabilities:
            # AUTHENTICATE PLAIN accepte les accents dans le mot de passe (LOGIN non)
            blob = b"\0" + user.encode("utf-8") + b"\0" + password.encode("utf-8")
            conn.authenticate("PLAIN", lambda _challenge: blob)
        else:
            conn.login(user, password)
    except Exception:
        conn.shutdown()
        raise
    return conn


def safe_logout(conn) -> None:
    """Ferme une connexion sans jamais lever d'exception."""
    if conn is None:
        return
    try:
        conn.logout()
    except Exception:
        pass


def find_gmail_all_mail(conn) -> str:
    """Nom IMAP (entre guillemets) de « Tous les messages », repéré par l'attribut \\All."""
    data = ok(conn.list(), "LIST Gmail")
    for item in data:
        if isinstance(item, tuple):  # nom transmis en « littéral » IMAP
            m = re.match(rb"^\(([^)]*)\)", item[0])
            if m and b"\\all" in m.group(1).lower().split():
                return imap_quote(item[1].decode("ascii", "replace"))
        elif isinstance(item, bytes):
            m = _LIST_RE.match(item)
            if m and b"\\all" in m.group("flags").lower().split():
                name = m.group("name").decode("ascii", "replace")
                return name if name.startswith('"') else imap_quote(name)
    raise BridgeError("Dossier « Tous les messages » introuvable dans Gmail (IMAP activé ?)")


def fetch_message(src, uid: int):
    """(message_brut, date_interne, drapeaux) sans marquer le message comme lu."""
    data = ok(src.uid("FETCH", str(uid), "(INTERNALDATE FLAGS BODY.PEEK[])"), f"FETCH {uid}")
    raw, meta = None, b""
    for part in data:
        if isinstance(part, tuple):
            meta += part[0]
            raw = part[1]
        elif isinstance(part, bytes):
            meta += b" " + part  # certains serveurs envoient FLAGS après le corps
    if raw is None:
        raise imaplib.IMAP4.error(f"FETCH {uid} : message vide ou disparu")
    return raw, imaplib.Internaldate2tuple(meta), imaplib.ParseFlags(meta)


def fetch_header_infos(src, uids) -> list:
    """[(infos, date_interne)] en ne lisant que De / Objet / Message-ID (léger)."""
    if not uids:
        return []
    data = ok(src.uid("FETCH", ",".join(str(u) for u in uids),
                      "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT)])"), "FETCH en-têtes")
    result = []
    for i, part in enumerate(data):
        if isinstance(part, tuple):
            tail = data[i + 1] if i + 1 < len(data) and isinstance(data[i + 1], bytes) else b""
            result.append((describe(part[1] or b""), imaplib.Internaldate2tuple(part[0] + b" " + tail)))
    return result


# =============================================================================
# Analyse d'un message
# =============================================================================

def _header(msg, name: str) -> str:
    """Valeur décodée d'un en-tête, chaîne vide si absent ou illisible."""
    try:
        return " ".join(str(msg.get(name, "") or "").split())
    except Exception:
        return ""


def describe(raw: bytes) -> dict:
    """Expéditeur, objet, date, Message-ID et type, lus dans les en-têtes."""
    msg = BytesHeaderParser(policy=policy.default).parsebytes(raw)
    try:
        ctype = msg.get_content_type()
    except Exception:
        ctype = "text/plain"
    return {
        "from": _header(msg, "From"),
        "subject": _header(msg, "Subject"),
        "date": _header(msg, "Date"),
        "message_id": normalize_message_id(_header(msg, "Message-ID")),
        "content_type": ctype,
    }


def is_forwarding_bounce(info: dict, raw: bytes, target: str | None) -> bool:
    """Avis de non-remise (multipart/report) causé par un transfert vers l'adresse Gmail."""
    return bool(target) and info["content_type"] == "multipart/report" and target.lower().encode() in raw.lower()


def norm_subject(subject: str | None) -> str:
    """Objet comparable : minuscules, sans aucun espace (y compris insécables)."""
    return "".join((subject or "").casefold().split())


# =============================================================================
# Cible Gmail
# =============================================================================

class Gmail:
    """Boîte Gmail de destination : recherche des doublons, dépôt, libellés."""

    def __init__(self, conn, settings: dict, address: str = "", dry_run: bool = False):
        self.conn, self.s, self.address, self.dry_run = conn, settings, address, dry_run
        self.all_mail = find_gmail_all_mail(conn)
        ok(conn.select(self.all_mail, readonly=True), "SELECT Tous les messages")
        self.pending = defaultdict(list)   # libellé -> UID Gmail des copies

    def has_message_id(self, message_id: str) -> bool:
        data = ok(self.conn.uid("SEARCH", "X-GM-RAW", imap_quote(f"rfc822msgid:{message_id}")), "SEARCH Gmail")
        return bool(data and data[0] and data[0].split())

    def has_similar(self, info: dict, idate) -> bool:
        """Même expéditeur, même objet, reçu à ± N minutes (redirections qui réécrivent le Message-ID)."""
        addr = parseaddr(info.get("from") or "")[1]
        subject = norm_subject(info.get("subject"))
        if not addr or not subject or not idate:
            return False
        t, w = int(time.mktime(idate)), int(self.s["dedup_window_minutes"] * 60)
        data = ok(self.conn.uid("SEARCH", "X-GM-RAW", imap_quote(f"from:{addr} after:{t - w} before:{t + w}")),
                  "SEARCH Gmail")
        uids = [u.decode() for u in (data[0] or b"").split()][:25]
        if not uids:
            return False
        data = ok(self.conn.uid("FETCH", ",".join(uids), "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])"), "FETCH objets")
        for part in data:
            if isinstance(part, tuple):
                msg = BytesHeaderParser(policy=policy.default).parsebytes(part[1] or b"")
                if norm_subject(_header(msg, "Subject")) == subject:
                    return True
        return False

    def find(self, info: dict, idate) -> str | None:
        """Raison pour laquelle le message est déjà dans Gmail, ou None s'il faut le copier."""
        if info.get("message_id") and self.has_message_id(info["message_id"]):
            return "même Message-ID"
        if self.has_similar(info, idate):
            return "même expéditeur, objet et heure"
        return None

    def append(self, raw: bytes, idate, src_flags, label: str | None) -> None:
        flags = r"(\Seen)" if self.s["mirror_seen"] and b"\\Seen" in src_flags else None
        data = ok(self.conn.append(GMAIL_TARGET_MAILBOX, flags, idate or time.localtime(), raw), "APPEND Gmail")
        m = _APPENDUID_RE.search(data[0] if data and isinstance(data[0], bytes) else b"")
        if m and label:
            self.pending[label].append(m.group(1).decode())

    def apply_labels(self) -> None:
        """Pose les libellés (un par compte) sur les copies, en une commande par libellé."""
        if self.dry_run or not self.pending:
            return
        try:
            ok(self.conn.select(imap_quote(GMAIL_TARGET_MAILBOX)), "SELECT cible")
            for label, uids in self.pending.items():
                self.conn.create(imap_quote(label))  # NO si déjà existant : sans importance
                ok(self.conn.uid("STORE", ",".join(uids), "+X-GM-LABELS", f"({imap_quote(label)})"), "STORE")
        except Exception as exc:  # confort seulement : ne doit pas faire échouer la passe
            log.warning("Libellés non posés : %s", exc)
        self.pending.clear()


# =============================================================================
# État, verrou, journal
# =============================================================================

def load_state(path=STATE_FILE) -> dict:
    """Charge l'état ({} si première passe) et migre l'ancien format mono-compte."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = {}
    if "folders" in state:  # version 1 : un seul compte « u-paris »
        state.setdefault("accounts", {}).setdefault("u-paris", {})["folders"] = state.pop("folders")
    return state


def save_state(state: dict, path=STATE_FILE) -> None:
    """Écrit l'état de façon atomique."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class RunLock:
    """Empêche deux passes simultanées (un verrou de plus de 30 min est ignoré)."""

    def __init__(self, path=LOCK_FILE):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and time.time() - self.path.stat().st_mtime > LOCK_STALE_MINUTES * 60:
            self.path.unlink(missing_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise BridgeError("Une autre passe est déjà en cours.") from None
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


class Ledger:
    """Journal CSV (une ligne par message examiné), lisible dans Excel."""

    FIELDS = ["horodatage", "compte", "dossier", "uid", "date_message", "expediteur", "objet",
              "message_id", "action", "detail"]

    def __init__(self, path, overwrite: bool = False):
        self.path = path
        self.rows = []
        path.parent.mkdir(parents=True, exist_ok=True)
        if overwrite:
            path.unlink(missing_ok=True)
        elif path.exists():
            with open(path, encoding="utf-8-sig", newline="") as fh:
                header = next(csv.reader(fh, delimiter=";"), [])
            if header and header != self.FIELDS:   # ancien format : archivé, pas mélangé
                path.replace(path.with_name(path.stem + "_v1.csv"))

    def write(self, **row) -> None:
        row.setdefault("horodatage", datetime.now().isoformat(timespec="seconds"))
        self.rows.append(row)
        new = not self.path.exists()
        with open(self.path, "a", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=self.FIELDS, delimiter=";", extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)


# =============================================================================
# Traitement d'un message (commun aux comptes IMAP et Outlook)
# =============================================================================

def handle_message(gm: Gmail, raw: bytes, idate, flags, label: str, row: dict, dry_run: bool) -> str:
    """Décide et applique : ignorer, déjà présent, copier. Renvoie l'action."""
    info = describe(raw)
    row.update(date_message=info["date"], expediteur=info["from"], objet=info["subject"],
               message_id=info["message_id"] or "")
    if is_forwarding_bounce(info, raw, gm.address):
        return "ignoré_rebond_redirection"
    match = gm.find(info, idate)
    if match:
        row["detail"] = match
        return "déjà_dans_gmail"
    if dry_run:
        return "serait_copié"
    gm.append(raw, idate, flags, label)
    return "copié"


def _record_failure(failures: dict, key: str, exc, s: dict, ledger: Ledger, row: dict, stats: Counter) -> bool:
    """Compte un échec ; renvoie True si le message est abandonné (on passe au suivant)."""
    n = failures.get(key, 0) + 1
    failures[key] = n
    if n >= s["max_retries"]:
        ledger.write(action="abandonné", detail=f"{n} échecs : {exc}", **row)
        stats["abandonné"] += 1
        failures.pop(key, None)
        return True
    ledger.write(action="erreur", detail=f"essai {n}/{s['max_retries']} : {exc}", **row)
    stats["erreur"] += 1
    return False


# =============================================================================
# Comptes IMAP
# =============================================================================

def process_imap_folder(src, gm: Gmail, acc: dict, folder: str, s: dict, st: dict, ledger: Ledger,
                        *, dry_run: bool, now: datetime, save) -> Counter:
    """Copie vers Gmail les nouveaux messages d'un dossier IMAP."""
    stats = Counter()
    ok(src.select(imap_quote(folder) if " " in folder else folder, readonly=True), f"EXAMINE {folder}")
    uidvalidity = int(src.response("UIDVALIDITY")[1][0])
    fst = st.setdefault("folders", {}).setdefault(folder, {})

    if fst.get("uidvalidity") != uidvalidity:
        # Première passe (ou dossier renuméroté) : rattrapage par date
        if fst:
            log.warning("%s/%s : UIDVALIDITY a changé, rattrapage", acc["id"], folder)
        since = imap_date(now.date() - timedelta(days=s["backfill_days"]))
        data = ok(src.uid("SEARCH", "SINCE", since), "SEARCH SINCE")
        uids = sorted(int(x) for x in (data[0] or b"").split())
        fst.clear()
        fst.update({"uidvalidity": uidvalidity, "last_uid": 0, "failures": {}})
        if acc.get("expects_redirect"):
            # Compte déjà redirigé vers Gmail : on doit retrouver une partie des messages.
            # Si aucun n'est retrouvé, la déduplication est jugée non fiable : pas de rattrapage.
            infos = fetch_header_infos(src, uids[-s["dedup_probe_size"]:])
            found = sum(1 for info, idate in infos if gm.find(info, idate))
            log.info("%s : test de déduplication, %d/%d déjà dans Gmail", acc["id"], found, len(infos))
            if len(infos) >= 5 and found == 0:
                log.warning("%s : aucun message retrouvé, rattrapage annulé par sécurité", acc["id"])
                fst["last_uid"] = uids[-1] if uids else 0
                fst["backfill_skipped"] = True
                uids = []
        save()
    else:
        last = fst.get("last_uid", 0)
        data = ok(src.uid("SEARCH", f"UID {last + 1}:*"), "SEARCH UID")
        uids = sorted(u for u in (int(x) for x in (data[0] or b"").split()) if u > last)

    failures = fst.setdefault("failures", {})
    young_limit = now.timestamp() - s["min_age_minutes"] * 60
    for uid in uids[: s["max_messages_per_run"]]:
        row = {"compte": acc["name"], "dossier": folder, "uid": uid}
        try:
            raw, idate, flags = fetch_message(src, uid)
            if idate and time.mktime(idate) > young_limit:
                stats["en_attente"] += 1   # trop récent : une redirection éventuelle passe d'abord
                break
            action = handle_message(gm, raw, idate, flags, acc["label"], row, dry_run)
            ledger.write(action=action, **row)
            stats[action] += 1
            fst["last_uid"] = uid
            failures.pop(str(uid), None)
            save()
        except (imaplib.IMAP4.abort, OSError):
            raise
        except Exception as exc:
            if _record_failure(failures, str(uid), exc, s, ledger, row, stats):
                fst["last_uid"] = uid
                save()
                continue
            save()
            break
    return stats


def process_imap_account(gm: Gmail, acc: dict, s: dict, st: dict, ledger: Ledger, **kw) -> Counter:
    src = connect(acc["host"], int(acc["port"]), acc["cred"], strip_spaces=True)
    try:
        stats = Counter()
        for folder in acc["folders"]:
            stats.update(process_imap_folder(src, gm, acc, folder, s, st, ledger, **kw))
        return stats
    finally:
        safe_logout(src)


# =============================================================================
# Comptes Outlook (Microsoft 365, Inserm…)
# =============================================================================

def process_outlook_account(gm: Gmail, acc: dict, s: dict, st: dict, ledger: Ledger,
                            *, dry_run: bool, now: datetime, save) -> Counter:
    """Copie vers Gmail les nouveaux messages d'un compte lu dans Outlook."""
    ns = outlook_source.connect()   # lève OutlookNotRunning si Outlook est fermé
    stats = Counter()
    for folder_name in acc["folders"]:
        folder = outlook_source.get_folder(ns, acc["store"], folder_name)
        fst = st.setdefault("outlook", {}).setdefault(folder_name, {})
        if "since" not in fst:
            fst.update({"since": (now - timedelta(days=s["backfill_days"])).isoformat(timespec="seconds"),
                        "done": {}, "failures": {}})
        done, failures = fst.setdefault("done", {}), fst.setdefault("failures", {})
        since = datetime.fromisoformat(fst["since"])
        young_limit = now - timedelta(minutes=s["min_age_minutes"])
        copied = 0
        for received, entry_id, item in outlook_source.iter_items_since(folder, since - timedelta(hours=1)):
            if entry_id in done:
                continue
            if copied >= s["max_messages_per_run"]:
                break
            if received > young_limit:
                stats["en_attente"] += 1
                break
            row = {"compte": acc["name"], "dossier": folder_name, "uid": entry_id[-12:]}
            try:
                raw = outlook_source.item_to_mime(item)
                flags = () if item.UnRead else (b"\\Seen",)
                action = handle_message(gm, raw, received.timetuple(), flags, acc["label"], row, dry_run)
                ledger.write(action=action, **row)
                stats[action] += 1
                copied += 1
                done[entry_id] = received.isoformat(timespec="seconds")
                fst["since"] = max(fst["since"], done[entry_id])
                failures.pop(entry_id, None)
                save()
            except (imaplib.IMAP4.abort, OSError):
                raise
            except Exception as exc:
                if _record_failure(failures, entry_id, exc, s, ledger, row, stats):
                    done[entry_id] = received.isoformat(timespec="seconds")
                    save()
                    continue
                save()
                break
        # On ne garde en mémoire que les messages récents (le reste est sous le seuil « since »)
        horizon = (datetime.fromisoformat(fst["since"]) - timedelta(days=2)).isoformat(timespec="seconds")
        fst["done"] = {k: v for k, v in done.items() if v >= horizon}
    return stats


# =============================================================================
# Une passe complète
# =============================================================================

def open_gmail(conf: dict, dry_run: bool = False) -> Gmail:
    cred = conf["gmail"]["cred"]
    address = credentials.read(cred)[0]
    conn = connect(GMAIL_HOST, GMAIL_PORT, cred, strip_spaces=True)
    return Gmail(conn, conf["settings"], address=address, dry_run=dry_run)


def run_all(conf: dict, state: dict, ledger: Ledger, *, dry_run: bool = False, now: datetime | None = None,
            save=lambda: None, only: str | None = None, gmail: Gmail | None = None) -> dict:
    """Traite tous les comptes activés. Renvoie {id_compte: Counter} ; une erreur sur un compte
    n'empêche pas les autres d'être traités."""
    now = now or datetime.now()
    s = conf["settings"]
    gm = gmail or open_gmail(conf, dry_run)
    results = {}
    try:
        for acc in conf["accounts"]:
            if not acc.get("enabled", True) or (only and acc["id"] != only):
                continue
            st = state.setdefault("accounts", {}).setdefault(acc["id"], {})
            kw = dict(dry_run=dry_run, now=now, save=save)
            note, error, stats = None, None, Counter()
            try:
                if acc["type"] == "outlook":
                    stats = process_outlook_account(gm, acc, s, st, ledger, **kw)
                else:
                    stats = process_imap_account(gm, acc, s, st, ledger, **kw)
            except outlook_source.OutlookNotRunning as exc:
                note = str(exc)
            except credentials.CredentialNotFound:
                error = "Mot de passe non enregistré"
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                log.error("%s : %s", acc["id"], error)
            st["last"] = {"time": now.isoformat(timespec="seconds"), "stats": dict(stats),
                          "error": error, "note": note}
            results[acc["id"]] = stats
            save()
        gm.apply_labels()
    finally:
        if gmail is None:
            safe_logout(gm.conn)
    state["last_run"] = now.isoformat(timespec="seconds")
    save()
    return results


# =============================================================================
# Tests de connexion (utilisés par l'interface)
# =============================================================================

def test_gmail(conf: dict) -> tuple[bool, str]:
    try:
        gm = open_gmail(conf)
        safe_logout(gm.conn)
        return True, f"Connecté à Gmail ({gm.address})"
    except Exception as exc:
        return False, friendly_error(str(exc))


def test_account(acc: dict) -> tuple[bool, str]:
    try:
        if acc["type"] == "outlook":
            ns = outlook_source.connect()
            folder = outlook_source.get_folder(ns, acc["store"], acc["folders"][0])
            return True, f"Outlook : {folder.Items.Count} messages dans « {folder.Name} »"
        conn = connect(acc["host"], int(acc["port"]), acc["cred"], strip_spaces=True)
        count = ok(conn.select("INBOX", readonly=True), "EXAMINE")[0].decode()
        safe_logout(conn)
        return True, f"Connecté ({count} messages dans la boîte de réception)"
    except Exception as exc:
        return False, friendly_error(str(exc))


def friendly_error(msg: str) -> str:
    """Traduit les refus de connexion courants en phrases claires."""
    low = msg.lower()
    if "application-specific password" in low or "app password" in low:
        return "Ce fournisseur exige un mot de passe d'application (pas votre mot de passe habituel)."
    if any(w in low for w in ("authenticationfailed", "invalid credentials", "login failed", "logon failure",
                              "authentication failed")):
        return "Connexion refusée : identifiant ou mot de passe incorrect."
    if "outlook est fermé" in low:
        return "Outlook est fermé : ouvrez Outlook puis réessayez."
    if "getaddrinfo" in low or "timed out" in low:
        return "Serveur injoignable : vérifiez l'adresse du serveur et la connexion Internet."
    return msg


# =============================================================================
# Ligne de commande
# =============================================================================

def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if sys.stdout is not None:  # pythonw.exe (tâche planifiée) n'a pas de console
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        log.addHandler(ch)


def run_check(conf: dict) -> int:
    status = 0
    good, msg = test_gmail(conf)
    print(f"[{'OK' if good else 'ÉCHEC'}] Gmail : {msg}")
    status |= not good
    for acc in conf["accounts"]:
        if acc.get("enabled", True):
            good, msg = test_account(acc)
            print(f"[{'OK' if good else 'ÉCHEC'}] {acc['name']} : {msg}")
            status |= not good
    if conf.get("calendars"):
        if not gcal.connected():
            print("[ÉCHEC] Google Agenda : non connecté")
            status = 1
        else:
            try:
                names = [c["name"] for c in gcal.GoogleCalendar().calendars()]
                print(f"[OK] Google Agenda : {gcal.account_email()} ({len(names)} agendas modifiables)")
            except Exception as exc:
                print(f"[ÉCHEC] Google Agenda : {exc}")
                status = 1
    return int(status)


def calendar_pass(conf: dict, state: dict, now: datetime, *, force: bool, dry_run: bool, save) -> None:
    """Synchronise les calendriers si c'est l'heure (ou si `force`)."""
    sources = [c for c in conf.get("calendars", []) if c.get("enabled", True)]
    if not sources:
        return
    info = state.setdefault("calendar_pass", {})
    last = info.get("time")
    due = force or not last or now - datetime.fromisoformat(last) >= timedelta(
        minutes=conf["settings"]["calendar_interval_minutes"])
    if not due:
        return
    info.update({"time": now.isoformat(timespec="seconds"), "error": None, "note": None})
    try:
        if not gcal.connected():
            raise gcal.NotConnected("Google Agenda n'est pas connecté.")
        results = calendar_sync.run(conf, state, now, outlook_source.connect(), dry_run=dry_run, save=save)
        for src_id, res in results.items():
            summary = res if isinstance(res, str) else (", ".join(f"{k}={v}" for k, v in sorted(res.items()) if v)
                                                         or "rien à faire")
            log.info("%sAgenda %s : %s", "[SIMULATION] " if dry_run else "", src_id, summary)
    except outlook_source.OutlookNotRunning as exc:
        info["note"] = str(exc)
        log.info("Agenda : %s", exc)
    except Exception as exc:
        info["error"] = friendly_error(str(exc))
        log.warning("Agenda : %s", exc)
    save()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="MailBridge : comptes mail -> Gmail.")
    parser.add_argument("--check", action="store_true", help="teste Gmail et chaque compte")
    parser.add_argument("--dry-run", action="store_true", help="simulation : n'écrit rien dans Gmail")
    parser.add_argument("--account", help="ne traiter que ce compte (identifiant)")
    parser.add_argument("--reset-state", action="store_true", help="refait le rattrapage (du compte --account)")
    parser.add_argument("--calendar-only", action="store_true", help="synchronise seulement les agendas, tout de suite")
    args = parser.parse_args(argv)

    conf = config.load()
    if args.check:
        return run_check(conf)
    setup_logging()
    now = datetime.now()
    try:
        with RunLock():
            state = load_state()
            if args.reset_state:
                if args.account:
                    state.get("accounts", {}).pop(args.account, None)
                else:
                    state.pop("accounts", None)
            work = copy.deepcopy(state) if args.dry_run else state
            save = (lambda: None) if args.dry_run else (lambda: save_state(state))
            ledger = Ledger(SIMULATION_FILE if args.dry_run else LEDGER_FILE, overwrite=args.dry_run)
            outcome, code = "ok", 0
            if not args.calendar_only:
                try:
                    results = run_all(conf, work, ledger, dry_run=args.dry_run, now=now, save=save, only=args.account)
                    for acc_id, stats in results.items():
                        summary = ", ".join(f"{k}={v}" for k, v in sorted(stats.items())) or "rien de nouveau"
                        last = work["accounts"][acc_id]["last"]
                        extra = f" ({last['error'] or last['note']})" if (last["error"] or last["note"]) else ""
                        log.info("%s%s : %s%s", "[SIMULATION] " if args.dry_run else "", acc_id, summary, extra)
                except credentials.CredentialNotFound:
                    outcome, code = "Mot de passe Gmail non enregistré", 2
                    log.warning(outcome)
                except Exception as exc:
                    outcome, code = friendly_error(str(exc)), 1
                    log.error("Passe interrompue : %s", exc)
                work["last_pass"] = {"time": now.isoformat(timespec="seconds"), "outcome": outcome}
            calendar_pass(conf, work, now, force=args.calendar_only, dry_run=args.dry_run, save=save)
            save()
            return code
    except BridgeError as exc:
        log.warning("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
