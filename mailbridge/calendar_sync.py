# -*- coding: utf-8 -*-
"""
calendar_sync.py
================
Synchronisation des calendriers Outlook (université, Inserm, Microsoft 365…) vers Google Agenda,
intégrée à GmailBridge (remplace Outlook Google Calendar Sync).

Principe (sens unique Outlook -> Google)
    1. On lit dans Outlook (ouvert) les rendez-vous de la fenêtre [aujourd'hui - N jours,
       aujourd'hui + M jours], récurrences dépliées.
    2. On lit dans l'agenda Google cible les événements créés par GmailBridge pour cette source
       (marqués par des « propriétés privées » invisibles : mailbridge, mbsrc, mbkey, mbhash).
    3. On crée ce qui manque, on met à jour ce qui a changé (empreinte mbhash), on supprime ce
       qui a disparu d'Outlook. Rien d'autre dans votre agenda Google n'est touché.
    4. Première synchro : un événement déjà présent avec le même titre et la même heure (copié
       par un ancien outil) est « adopté » au lieu d'être dupliqué.

Les rendez-vous refusés ou annulés ne sont pas copiés. Les rappels Google sont désactivés sur
les copies (Outlook vous prévient déjà), pour éviter les doubles notifications.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta

from . import gcal

# ----------------------------- Paramètres ------------------------------------
OL_APPOINTMENT = 26          # classe COM d'un rendez-vous
OL_FOLDER_CALENDAR = 9
OL_MEETING_CANCELED = (5, 7)  # olMeetingCanceled, olMeetingReceivedAndCanceled
OL_RESPONSE_DECLINED = 4
OL_FREE = 0
OL_PRIVATE = 2
MAX_DESCRIPTION = 4000        # caractères de description recopiés
TARGET_PREFIX = "GmailBridge · "
# -----------------------------------------------------------------------------


# ---- Lecture d'Outlook ---------------------------------------------------------

class _SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ushort) for n in ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour", "wMinute",
                                               "wSecond", "wMilliseconds")]


def outlook_date(dt: datetime) -> str:
    """Date au format attendu par les filtres Outlook : format court de la langue de Windows."""
    st = _SYSTEMTIME(dt.year, dt.month, 0, dt.day, dt.hour, dt.minute, 0, 0)
    k32 = ctypes.windll.kernel32
    d, t = ctypes.create_unicode_buffer(64), ctypes.create_unicode_buffer(64)
    k32.GetDateFormatEx(None, 1, ctypes.byref(st), None, d, 64, None)   # DATE_SHORTDATE
    k32.GetTimeFormatEx(None, 2, ctypes.byref(st), None, t, 64)         # TIME_NOSECONDS
    return f"{d.value} {t.value}"


def _naive(dt) -> datetime:
    return datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def outlook_events(ns, store_name: str, start: datetime, end: datetime) -> list[dict]:
    """Rendez-vous (récurrences dépliées) du calendrier principal d'un compte Outlook."""
    store = next((s for s in ns.Stores if s.DisplayName.lower() == store_name.lower()), None)
    if store is None:
        raise KeyError(f"Compte « {store_name} » introuvable dans Outlook")
    items = store.GetDefaultFolder(OL_FOLDER_CALENDAR).Items
    items.Sort("[Start]")
    items.IncludeRecurrences = True
    found = items.Restrict(f"[Start] < '{outlook_date(end)}' AND [End] > '{outlook_date(start)}'")
    events = []
    item = found.GetFirst()
    while item is not None:
        try:
            if (item.Class == OL_APPOINTMENT and item.MeetingStatus not in OL_MEETING_CANCELED
                    and item.ResponseStatus != OL_RESPONSE_DECLINED):
                s, e = _naive(item.Start), _naive(item.End)
                try:
                    gid = item.GlobalAppointmentID
                except Exception:
                    gid = item.EntryID
                events.append({
                    "key": f"{gid}|{s.isoformat()}" if item.IsRecurring else gid,
                    "subject": item.Subject or "", "start": s, "end": e, "all_day": bool(item.AllDayEvent),
                    "location": item.Location or "", "body": (item.Body or "")[:MAX_DESCRIPTION],
                    "free": item.BusyStatus == OL_FREE, "private": item.Sensitivity == OL_PRIVATE,
                })
        except Exception:
            pass   # élément illisible : ignoré
        item = found.GetNext()
    return events


# ---- Conversion vers Google ---------------------------------------------------------

def to_google(ev: dict, source_id: str) -> dict:
    """Corps d'événement Google Calendar (avec empreinte pour détecter les changements)."""
    if ev["all_day"]:
        start, end = {"date": ev["start"].date().isoformat()}, {"date": ev["end"].date().isoformat()}
    else:   # heure locale de Windows -> heure avec décalage explicite (heure d'été comprise)
        start = {"dateTime": ev["start"].astimezone().isoformat()}
        end = {"dateTime": ev["end"].astimezone().isoformat()}
    body = {
        "summary": ev["subject"] or "(sans titre)", "location": ev["location"], "description": ev["body"],
        "start": start, "end": end, "transparency": "transparent" if ev["free"] else "opaque",
        "visibility": "private" if ev["private"] else "default", "reminders": {"useDefault": False},
    }
    digest = hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    body["extendedProperties"] = {"private": {"mailbridge": "1", "mbsrc": source_id, "mbkey": ev["key"][:900],
                                              "mbhash": digest}}
    return body


def _start_key(g: dict) -> str:
    """Début d'un événement Google, comparable à celui d'une copie (pour l'adoption)."""
    s = g.get("start", {})
    if "date" in s:
        return s["date"]
    try:
        return datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None).isoformat()
    except (KeyError, ValueError):
        return ""


def _local_start_key(body: dict) -> str:
    s = body["start"]
    return s["date"] if "date" in s else datetime.fromisoformat(s["dateTime"]).replace(tzinfo=None).isoformat()


# ---- Synchronisation d'une source ---------------------------------------------------

def sync_source(google, events: list[dict], src: dict, settings: dict, now: datetime, state: dict,
                dry_run: bool = False) -> Counter:
    """Aligne l'agenda Google cible sur la liste `events` d'Outlook. Renvoie les compteurs."""
    stats = Counter()
    t_min = (now - timedelta(days=settings["calendar_past_days"])).astimezone().isoformat()
    t_max = (now + timedelta(days=settings["calendar_future_days"])).astimezone().isoformat()
    target = src["target_id"]
    ours = {g["extendedProperties"]["private"].get("mbkey"): g
            for g in google.list_events(target, t_min, t_max, private_filter=f"mbsrc={src['id']}")}

    # Événements non marqués (copiés par un ancien outil) : candidats à l'adoption, 1re synchro seulement
    orphans = {}
    if not state.get("adopted"):
        for g in google.list_events(target, t_min, t_max):
            if "mailbridge" not in g.get("extendedProperties", {}).get("private", {}):
                orphans[(g.get("summary", ""), _start_key(g))] = g

    for ev in events:
        body = to_google(ev, src["id"])
        current = ours.pop(body["extendedProperties"]["private"]["mbkey"], None)
        if current is None:
            orphan = orphans.pop((body["summary"], _local_start_key(body)), None)
            if not dry_run:
                if orphan:
                    google.patch(target, orphan["id"], body)
                else:
                    google.insert(target, body)
            stats["adopté" if orphan else "créé"] += 1
        elif current["extendedProperties"]["private"].get("mbhash") != body["extendedProperties"]["private"]["mbhash"]:
            if not dry_run:
                google.patch(target, current["id"], body)
            stats["modifié"] += 1
        else:
            stats["inchangé"] += 1
    for gone in ours.values():   # supprimé (ou refusé) dans Outlook
        if not dry_run:
            google.delete(target, gone["id"])
        stats["supprimé"] += 1
    if not dry_run:
        state["adopted"] = True
    return stats


def ensure_target(google, src: dict) -> bool:
    """Crée l'agenda Google cible si besoin. Renvoie True si la configuration a changé."""
    if src.get("target_id"):
        return False
    name = src.get("target_name") or f"{TARGET_PREFIX}{src.get('label') or src['store']}"
    src["target_id"] = google.create_calendar(name)
    src["target_name"] = name
    return True


def run(conf: dict, state: dict, now: datetime, ns, google=None, dry_run: bool = False, save=lambda: None) -> dict:
    """Synchronise toutes les sources calendrier activées. Renvoie {id_source: Counter | message}."""
    sources = [c for c in conf.get("calendars", []) if c.get("enabled", True)]
    if not sources:
        return {}
    google = google or gcal.GoogleCalendar()
    s = conf["settings"]
    start = now - timedelta(days=s["calendar_past_days"])
    end = now + timedelta(days=s["calendar_future_days"])
    results, config_changed = {}, False
    for src in sources:
        st = state.setdefault("calendars", {}).setdefault(src["id"], {})
        try:
            if not dry_run:
                config_changed |= ensure_target(google, src)
            events = outlook_events(ns, src["store"], start, end)
            stats = sync_source(google, events, src, s, now, st, dry_run=dry_run)
            st["last"] = {"time": now.isoformat(timespec="seconds"), "stats": dict(stats), "error": None,
                          "count": len(events)}
            results[src["id"]] = stats
        except Exception as exc:
            st["last"] = {"time": now.isoformat(timespec="seconds"), "stats": {}, "error": str(exc)}
            results[src["id"]] = str(exc)
        save()
    if config_changed:
        from . import config
        fresh = config.load()            # on ne réécrit que les identifiants d'agenda créés
        ids = {c["id"]: c for c in sources}
        for c in fresh.get("calendars", []):
            if c["id"] in ids:
                c["target_id"], c["target_name"] = ids[c["id"]]["target_id"], ids[c["id"]]["target_name"]
        config.save(fresh)
    return results
