# -*- coding: utf-8 -*-
"""
Tests hors ligne de la synchro des agendas Outlook -> Google (faux agenda Google en mémoire)
et du client OAuth / API (requêtes HTTP simulées).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mailbridge import calendar_sync, config, gcal  # noqa: E402

NOW = datetime(2026, 10, 30, 12, 0, 0)
SETTINGS = dict(config.DEFAULT_SETTINGS)


class FakeGoogle:
    """Agenda Google en mémoire : insert / patch / delete / list (avec filtre de propriété privée)."""

    def __init__(self):
        self.events, self.n, self.calls = {}, 0, []
        self.created_calendars = []

    def create_calendar(self, name):
        self.created_calendars.append(name)
        return f"cal-{len(self.created_calendars)}@group"

    def list_events(self, cal, tmin, tmax, private_filter=None):
        out = []
        for ev in self.events.values():
            props = ev.get("extendedProperties", {}).get("private", {})
            if private_filter:
                k, v = private_filter.split("=", 1)
                if props.get(k) != v:
                    continue
            out.append(ev)
        return out

    def insert(self, cal, body):
        self.n += 1
        ev = dict(body, id=f"e{self.n}")
        self.events[ev["id"]] = ev
        self.calls.append(("insert", ev["id"]))
        return ev

    def patch(self, cal, eid, body):
        self.events[eid] = dict(self.events[eid], **body)
        self.calls.append(("patch", eid))

    def delete(self, cal, eid):
        self.events.pop(eid, None)
        self.calls.append(("delete", eid))


def ev(key, subject, start, hours=1, all_day=False, **kw):
    base = {"key": key, "subject": subject, "start": start, "end": start + timedelta(hours=hours),
            "all_day": all_day, "location": "", "body": "", "free": False, "private": False}
    base.update(kw)
    return base


class SyncSource(unittest.TestCase):
    def setUp(self):
        self.g = FakeGoogle()
        self.src = {"id": "cal-u-paris", "store": "moi@u-paris.fr", "label": "U-Paris", "target_id": "T"}
        self.state = {}

    def sync(self, events):
        return calendar_sync.sync_source(self.g, events, self.src, SETTINGS, NOW, self.state)

    def test_create_update_delete_cycle(self):
        a = ev("A", "Cours", NOW + timedelta(days=1))
        b = ev("B", "Réunion", NOW + timedelta(days=2))
        self.assertEqual(self.sync([a, b])["créé"], 2)
        self.assertEqual(self.sync([a, b])["inchangé"], 2)              # rien ne change : aucun appel
        b2 = dict(b, location="Salle 12")
        res = self.sync([a, b2])
        self.assertEqual((res["modifié"], res["inchangé"]), (1, 1))
        res = self.sync([a])                                          # B supprimé dans Outlook
        self.assertEqual(res["supprimé"], 1)
        self.assertEqual(len(self.g.events), 1)

    def test_existing_untagged_event_is_adopted_not_duplicated(self):
        start = NOW + timedelta(days=3)
        self.g.events["old"] = {"id": "old", "summary": "Formation Moodle",
                                "start": {"dateTime": start.astimezone().isoformat()}}
        res = self.sync([ev("M", "Formation Moodle", start)])
        self.assertEqual(res["adopté"], 1)
        self.assertEqual(len(self.g.events), 1)
        self.assertEqual(self.g.events["old"]["extendedProperties"]["private"]["mbkey"], "M")

    def test_other_sources_and_personal_events_are_untouched(self):
        self.g.events["perso"] = {"id": "perso", "summary": "Anniversaire", "start": {"date": "2026-11-05"},
                                  "extendedProperties": {"private": {"note": "perso"}}}
        self.g.events["other"] = {"id": "other", "summary": "Inserm", "start": {"date": "2026-11-06"},
                                  "extendedProperties": {"private": {"mailbridge": "1", "mbsrc": "cal-inserm",
                                                                     "mbkey": "Z", "mbhash": "x"}}}
        self.state["adopted"] = True
        self.sync([])
        self.assertIn("perso", self.g.events)
        self.assertIn("other", self.g.events)

    def test_google_body_all_day_free_private(self):
        body = calendar_sync.to_google(ev("D", "Congé", datetime(2026, 12, 24), hours=48, all_day=True,
                                          free=True, private=True), "s")
        self.assertEqual(body["start"], {"date": "2026-12-24"})
        self.assertEqual(body["end"], {"date": "2026-12-26"})
        self.assertEqual(body["transparency"], "transparent")
        self.assertEqual(body["visibility"], "private")
        self.assertFalse(body["reminders"]["useDefault"])

    def test_timed_event_has_explicit_offset(self):
        body = calendar_sync.to_google(ev("T", "Cours", datetime(2026, 7, 1, 9, 0)), "s")
        self.assertRegex(body["start"]["dateTime"], r"^2026-07-01T09:00:00[+-]\d\d:\d\d$")

    def test_dry_run_changes_nothing(self):
        res = calendar_sync.sync_source(self.g, [ev("A", "Cours", NOW)], self.src, SETTINGS, NOW, self.state,
                                        dry_run=True)
        self.assertEqual(res["créé"], 1)
        self.assertEqual(self.g.events, {})

    def test_run_creates_dedicated_calendar_once(self):
        conf = {"calendars": [dict(self.src, target_id="", target_name="", enabled=True)], "settings": SETTINGS}
        tmp = Path(tempfile.mkdtemp()) / "config.json"
        with mock.patch.object(config, "CONFIG_FILE", tmp), mock.patch.object(config, "DATA_DIR", tmp.parent), \
             mock.patch.object(calendar_sync, "outlook_events", lambda ns, store, s, e: [ev("A", "Cours", NOW)]):
            config.save({"gmail": {}, "accounts": [], "calendars": [dict(conf["calendars"][0])], "settings": {}})
            res = calendar_sync.run(conf, {}, NOW, ns=None, google=self.g)
            saved = config.load()
        self.assertEqual(res["cal-u-paris"]["créé"], 1)
        self.assertEqual(self.g.created_calendars, ["MailBridge · U-Paris"])
        self.assertEqual(saved["calendars"][0]["target_id"], "cal-1@group")


class OAuthAndApi(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "google_client.json"
        self.patch = mock.patch.object(gcal, "CLIENT_FILE", self.tmp)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_import_client_json(self):
        gcal.save_client_from_json(json.dumps({"installed": {"client_id": "123-abc.apps.googleusercontent.com",
                                                             "client_secret": "s3cr3t"}}))
        self.assertEqual(gcal.load_client()["client_id"], "123-abc.apps.googleusercontent.com")
        with self.assertRaises(gcal.GoogleError):
            gcal.save_client_from_json('{"installed": {"client_id": "faux", "client_secret": "x"}}')

    def test_token_refresh_and_paginated_listing(self):
        gcal.save_client("1-a.apps.googleusercontent.com", "s")
        pages = [{"items": [{"id": "e1"}], "nextPageToken": "p2"}, {"items": [{"id": "e2"}]}]
        seen = []

        def fake_urlopen(req, timeout=0):
            seen.append((req.get_method(), req.full_url))
            if req.full_url.startswith(gcal.TOKEN_URL):
                return io.BytesIO(json.dumps({"access_token": "AT", "expires_in": 3600}).encode())
            self.assertEqual(req.get_header("Authorization"), "Bearer AT")
            return io.BytesIO(json.dumps(pages.pop(0)).encode())

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            g = gcal.GoogleCalendar(refresh_token="RT")
            events = g.list_events("primary", "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z", "mbsrc=x")
        self.assertEqual([e["id"] for e in events], ["e1", "e2"])
        self.assertEqual(sum(1 for m, u in seen if u.startswith(gcal.TOKEN_URL)), 1)   # un seul renouvellement
        self.assertIn("privateExtendedProperty=mbsrc%3Dx", seen[1][1])

    def test_revoked_token_raises_not_connected(self):
        gcal.save_client("1-a.apps.googleusercontent.com", "s")

        def fake_urlopen(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 400, "Bad", {}, io.BytesIO(b'{"error":"invalid_grant"}'))

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(gcal.NotConnected):
                gcal.GoogleCalendar(refresh_token="RT").calendars()

    def test_delete_of_missing_event_is_ignored(self):
        gcal.save_client("1-a.apps.googleusercontent.com", "s")

        def fake_urlopen(req, timeout=0):
            if req.full_url.startswith(gcal.TOKEN_URL):
                return io.BytesIO(b'{"access_token": "AT", "expires_in": 3600}')
            raise urllib.error.HTTPError(req.full_url, 410, "Gone", {}, io.BytesIO(b""))

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            gcal.GoogleCalendar(refresh_token="RT").delete("primary", "e1")   # ne lève rien


@unittest.skipUnless(sys.platform == "win32", "format de date Windows")
class OutlookDateFormat(unittest.TestCase):
    def test_outlook_date_contains_day_month_year(self):
        text = calendar_sync.outlook_date(datetime(2026, 11, 28, 14, 5))
        for part in ("2026", "28", "11", "14", "05"):
            self.assertIn(part, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
