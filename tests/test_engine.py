# -*- coding: utf-8 -*-
"""
Tests hors ligne de GmailBridge : de faux serveurs IMAP (source et Gmail) et un faux Outlook
reproduisent les cas réels rencontrés (redirection qui réécrit le Message-ID, rejets Gmail,
avis de non-remise, message trop récent, coupure réseau, plusieurs comptes).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import copy
import imaplib
import re
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mailbridge import config, credentials, engine, outlook_source  # noqa: E402

NOW = datetime(2026, 10, 29, 12, 0, 0)
GMAIL_ADDR = "destination@gmail.com"


def make_raw(mid: str | None, sender: str, subject: str, report_for: str | None = None) -> bytes:
    """Message RFC 822 minimal (ou avis de non-remise si report_for)."""
    lines = [f"From: {sender}", "To: moi@exemple.fr", f"Subject: {subject}", "Date: Wed, 28 Oct 2026 10:00:00 +0100"]
    if mid:
        lines.append(f"Message-ID: <{mid}>")
    if report_for:
        lines += ['Content-Type: multipart/report; report-type=delivery-status; boundary="b"', "",
                  "--b", "", f"<{report_for}>: 550-5.7.30 DKIM authentication didn't pass", "--b--"]
    else:
        lines += ["Content-Type: text/plain; charset=utf-8", "", "Corps du message."]
    return "\r\n".join(lines).encode()


class FakeMailbox:
    def __init__(self, uidvalidity: int = 1):
        self.uidvalidity, self.msgs, self.next_uid = uidvalidity, {}, 1

    def add(self, raw: bytes, when: datetime = NOW - timedelta(hours=5), flags=()) -> int:
        uid = self.next_uid
        self.next_uid += 1
        self.msgs[uid] = {"raw": raw, "when": when, "flags": tuple(flags)}
        return uid


class FakeIMAP:
    """Sous-ensemble d'imaplib.IMAP4 utilisé par le moteur."""

    def __init__(self, mailboxes: dict, all_mail: str | None = None):
        self.mailboxes, self.all_mail = mailboxes, all_mail
        self.selected, self._resp = None, {}
        self.appended, self.created, self.stored = [], [], []
        self.fail_fetch: dict[int, Exception] = {}
        self.conn = self

    @staticmethod
    def _unq(name: str) -> str:
        return name[1:-1] if name.startswith('"') else name

    def list(self):
        lines = [b'(\\HasNoChildren) "/" "INBOX"']
        if self.all_mail:
            lines.append(f'(\\All \\HasNoChildren) "/" "{self.all_mail}"'.encode())
        return "OK", lines

    def select(self, mailbox, readonly=False):
        box = self.mailboxes[self._unq(mailbox)]
        self.selected = box
        self._resp["UIDVALIDITY"] = [str(box.uidvalidity).encode()]
        return "OK", [str(len(box.msgs)).encode()]

    def response(self, code):
        return code, self._resp.pop(code, [None])

    def create(self, name):
        self.created.append(name)
        return "OK", [b"created"]

    def append(self, mailbox, flags, date_time, message):
        target = self.mailboxes[self._unq(mailbox)]
        uid = target.add(message, when=NOW)
        if self.all_mail and self._unq(mailbox) != self.all_mail:
            self.mailboxes[self.all_mail].add(message, when=NOW)
        self.appended.append((self._unq(mailbox), flags, message))
        return "OK", [f"[APPENDUID {target.uidvalidity} {uid}] (Success)".encode()]

    def logout(self):
        return "BYE", []

    def uid(self, command, *args):
        command, box = command.upper(), self.selected
        if command == "SEARCH":
            if args[0] == "X-GM-RAW":
                q = self._unq(args[1])
                if q.startswith("rfc822msgid:"):
                    wanted = q.split(":", 1)[1]
                    hits = [u for u, m in box.msgs.items() if f"<{wanted}>".encode() in m["raw"]]
                else:
                    mm = re.match(r"from:(\S+) after:(\d+) before:(\d+)$", q)
                    addr, lo, hi = f"From: {mm.group(1)}".lower().encode(), int(mm.group(2)), int(mm.group(3))
                    hits = [u for u, m in box.msgs.items() if addr in m["raw"].lower()
                            and lo <= time.mktime(m["when"].timetuple()) <= hi]
            elif args[0].startswith("UID "):
                lo = int(args[0][4:].split(":")[0])
                hits = [u for u in box.msgs if u >= lo] or ([max(box.msgs)] if box.msgs else [])
            elif args[0] == "SINCE":
                since = datetime.strptime(args[1], "%d-%b-%Y")
                hits = [u for u, m in box.msgs.items() if m["when"] >= since]
            else:
                hits = list(box.msgs)
            return "OK", [" ".join(map(str, sorted(hits))).encode()]
        if command == "FETCH":
            spec = args[1]
            if "HEADER.FIELDS" in spec:
                fields = re.search(r"HEADER\.FIELDS \(([^)]*)\)", spec).group(1).split()
                out = []
                for u in (int(x) for x in args[0].split(",")):
                    m = box.msgs[u]
                    head = m["raw"].split(b"\r\n\r\n")[0].split(b"\r\n")
                    hdr = b"\r\n".join(ln for ln in head if ln.split(b":")[0].decode().upper() in fields) + b"\r\n\r\n"
                    idate = imaplib.Time2Internaldate(time.mktime(m["when"].timetuple()))
                    out += [(f"{u} (UID {u} INTERNALDATE {idate} BODY[HEADER] {{{len(hdr)}}}".encode(), hdr), b")"]
                return "OK", out
            u = int(args[0])
            if u in self.fail_fetch:
                raise self.fail_fetch[u]
            m = box.msgs[u]
            idate = imaplib.Time2Internaldate(time.mktime(m["when"].timetuple()))
            flags = " ".join(f.decode() for f in m["flags"])
            meta = f"{u} (UID {u} INTERNALDATE {idate} FLAGS ({flags}) BODY[] {{{len(m['raw'])}}}".encode()
            return "OK", [(meta, m["raw"]), b")"]
        if command == "STORE":
            self.stored.append(args)
            return "OK", [b""]
        raise AssertionError(command)


def settings(**over) -> dict:
    s = dict(config.DEFAULT_SETTINGS)
    s.update(over)
    return s


class ImapScenario(unittest.TestCase):
    """Compte universitaire redirigé : 5 messages, la redirection en a livré 1 (Message-ID réécrit)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.s = settings()
        self.inbox = FakeMailbox(uidvalidity=14)
        self.inbox.add(make_raw("interne-1@universite.fr", "alice@universite.fr", "TD semaine 46"))
        self.inbox.add(make_raw("ext-1@labo-externe.fr", "bob@labo-externe.fr", "Question calcium"))
        self.inbox.add(make_raw("ndr-1@mx1", "MAILER-DAEMON@mx1", "Non remis", report_for=GMAIL_ADDR))
        self.inbox.add(make_raw("ext-2@etranger.ch", "carol@etranger.ch", "Article en cours"))
        self.inbox.add(make_raw("ext-3@institut.fr", "dave@institut.fr", "tout frais"), when=NOW - timedelta(minutes=1))
        self.src = FakeIMAP({"INBOX": self.inbox})
        self.g_inbox, self.g_all = FakeMailbox(99), FakeMailbox(98)
        self.g_all.add(make_raw("rewritten-1@relay.exemple", "alice@universite.fr", "TD semaine 46"))
        self.gconn = FakeIMAP({"INBOX": self.g_inbox, "[Gmail]/Tous les messages": self.g_all},
                              all_mail="[Gmail]/Tous les messages")
        self.acc = config.new_account("u-paris", id="u-paris", cred="X", expects_redirect=True)
        self.conf = {"gmail": {"cred": "G"}, "accounts": [self.acc], "settings": self.s}

    def run_pass(self, state, dry_run=False, now=NOW, sources=None):
        ledger = engine.Ledger(self.tmp / "journal.csv")
        gm = engine.Gmail(self.gconn, self.s, address=GMAIL_ADDR, dry_run=dry_run)
        sources = sources or {"X": self.src}
        with mock.patch.object(engine, "connect", side_effect=lambda h, p, cred, **k: sources[cred]):
            res = engine.run_all(self.conf, state, ledger, dry_run=dry_run, now=now, gmail=gm)
        return res, ledger

    def test_first_pass_copies_only_missing_mail(self):
        state = {}
        res, ledger = self.run_pass(state)
        t = res["u-paris"]
        self.assertEqual(t["copié"], 2)
        self.assertEqual(t["déjà_dans_gmail"], 1)                 # malgré le Message-ID réécrit
        self.assertEqual(t["ignoré_rebond_redirection"], 1)
        self.assertEqual(t["en_attente"], 1)
        self.assertEqual(state["accounts"]["u-paris"]["folders"]["INBOX"]["last_uid"], 4)
        self.assertIn("objet", ledger.rows[0]["detail"])
        self.assertEqual(self.gconn.stored[0][-1], '("U-Paris")')   # libellé du compte

    def test_passes_are_idempotent(self):
        state = {}
        self.run_pass(state)
        res, _ = self.run_pass(state, now=NOW + timedelta(minutes=10))
        self.assertEqual(res["u-paris"]["copié"], 1)
        res, _ = self.run_pass(state, now=NOW + timedelta(minutes=20))
        self.assertEqual(sum(res["u-paris"].values()), 0)
        self.assertEqual(len(self.gconn.appended), 3)

    def test_dry_run_writes_nothing(self):
        state = {}
        res, _ = self.run_pass(copy.deepcopy(state), dry_run=True)
        self.assertEqual(res["u-paris"]["serait_copié"], 2)
        self.assertEqual(self.gconn.appended, [])
        self.assertEqual(self.gconn.stored, [])
        self.assertEqual(state, {})

    def test_uidvalidity_reset_does_not_duplicate(self):
        state = {}
        self.run_pass(state, now=NOW + timedelta(minutes=10))
        n = len(self.gconn.appended)
        self.inbox.uidvalidity = 15
        res, _ = self.run_pass(state, now=NOW + timedelta(minutes=20))
        self.assertEqual(res["u-paris"]["copié"], 0)
        self.assertEqual(len(self.gconn.appended), n)

    def test_backfill_cancelled_when_dedup_finds_nothing(self):
        for i in range(5):
            self.inbox.add(make_raw(f"x{i}@ex.fr", "a@ex.fr", f"x{i}"))
        self.g_all.msgs.clear()
        state = {}
        res, _ = self.run_pass(state)
        self.assertEqual(res["u-paris"]["copié"], 0)
        self.assertTrue(state["accounts"]["u-paris"]["folders"]["INBOX"]["backfill_skipped"])

    def test_no_probe_for_accounts_without_redirect(self):
        self.acc["expects_redirect"] = False
        self.g_all.msgs.clear()
        res, _ = self.run_pass({})
        self.assertEqual(res["u-paris"]["copié"], 3)   # le compte n'est pas redirigé : tout est copié

    def test_failing_message_retried_then_abandoned(self):
        self.src.fail_fetch[2] = imaplib.IMAP4.error("message illisible")
        state = {}
        for _ in range(2):
            res, _ = self.run_pass(state)
            self.assertEqual(res["u-paris"]["erreur"], 1)
            self.assertEqual(state["accounts"]["u-paris"]["folders"]["INBOX"]["last_uid"], 1)
        res, _ = self.run_pass(state)
        self.assertEqual(res["u-paris"]["abandonné"], 1)
        self.assertEqual(res["u-paris"]["copié"], 1)

    def test_network_error_is_recorded_not_fatal(self):
        self.src.fail_fetch[2] = imaplib.IMAP4.abort("connexion perdue")
        state = {}
        self.run_pass(state)
        last = state["accounts"]["u-paris"]["last"]
        self.assertIn("connexion perdue", last["error"])
        self.assertEqual(state["accounts"]["u-paris"]["folders"]["INBOX"]["last_uid"], 1)

    def test_two_accounts_get_their_own_label(self):
        yahoo_box = FakeMailbox(uidvalidity=3)
        yahoo_box.add(make_raw("y-1@yahoo.fr", "ami@yahoo.fr", "Coucou"))
        yahoo = config.new_account("yahoo", id="yahoo", cred="Y")
        self.conf["accounts"].append(yahoo)
        state = {}
        res, _ = self.run_pass(state, sources={"X": self.src, "Y": FakeIMAP({"INBOX": yahoo_box})})
        self.assertEqual(res["yahoo"]["copié"], 1)
        labels = sorted(a[-1] for a in self.gconn.stored)
        self.assertEqual(labels, ['("U-Paris")', '("Yahoo")'])

    def test_disabled_account_is_skipped(self):
        self.acc["enabled"] = False
        res, _ = self.run_pass({})
        self.assertEqual(res, {})


# ---- Comptes Outlook ---------------------------------------------------------

class FakeAttachment:
    def __init__(self, name, data, cid=""):
        self.FileName, self.Type, self._data, self._cid = name, 1, data, cid
        self.PropertyAccessor = mock.Mock(GetProperty=lambda _p: self._cid)

    def SaveAsFile(self, path):
        Path(path).write_bytes(self._data)


class FakeAttachments:
    def __init__(self, items):
        self._items = items
        self.Count = len(items)

    def Item(self, i):
        return self._items[i - 1]


class FakeOutlookItem:
    """Message Outlook (COM) minimal."""

    def __init__(self, entry_id, received, subject, sender="Collègue <c@institut.fr>", mid=None, unread=True,
                 attachments=(), html=None):
        self.EntryID, self.ReceivedTime, self.Subject, self.UnRead = entry_id, received, subject, unread
        self.Class, self.SenderName, self.Sender, self.To, self.CC = 43, "Collègue", None, "moi@institut.fr", ""
        self.Body, self.HTMLBody, self.BodyFormat = "Bonjour", html or "", 2 if html else 1
        self.Attachments = FakeAttachments(list(attachments))
        headers = (f"From: {sender}\r\nTo: moi@institut.fr\r\nSubject: {subject}\r\n"
                   f"Date: Thu, 29 Oct 2026 09:00:00 +0100\r\n" + (f"Message-ID: <{mid}>\r\n" if mid else ""))
        self.PropertyAccessor = mock.Mock(GetProperty=lambda p: headers if p == outlook_source.PR_TRANSPORT_HEADERS else "")


class OutlookScenario(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.s = settings()
        self.items = [
            FakeOutlookItem("E1", NOW - timedelta(hours=3), "Réunion d'équipe", mid="o-1@institut.fr"),
            FakeOutlookItem("E2", NOW - timedelta(hours=2), "Commande labo", mid="o-2@institut.fr",
                            attachments=[FakeAttachment("devis.pdf", b"%PDF-1.4 test")]),
            FakeOutlookItem("E3", NOW - timedelta(minutes=1), "Tout frais", mid="o-3@institut.fr"),
        ]
        self.gconn = FakeIMAP({"INBOX": FakeMailbox(99), "[Gmail]/Tous les messages": FakeMailbox(98)},
                              all_mail="[Gmail]/Tous les messages")
        self.acc = config.new_account("outlook", id="inserm", name="Inserm", label="Inserm", store="moi@institut.fr")
        self.conf = {"gmail": {"cred": "G"}, "accounts": [self.acc], "settings": self.s}

    def run_pass(self, state, now=NOW, running=True):
        ledger = engine.Ledger(self.tmp / "journal.csv")
        gm = engine.Gmail(self.gconn, self.s, address=GMAIL_ADDR)
        fake_connect = (lambda: object()) if running else mock.Mock(side_effect=outlook_source.OutlookNotRunning("fermé"))
        with mock.patch.object(outlook_source, "connect", fake_connect), \
             mock.patch.object(outlook_source, "get_folder", lambda ns, store, name: "dossier"), \
             mock.patch.object(outlook_source, "iter_items_since",
                               lambda folder, since: [(i.ReceivedTime, i.EntryID, i) for i in self.items
                                                      if i.ReceivedTime >= since]):
            return engine.run_all(self.conf, state, ledger, now=now, gmail=gm)

    def test_outlook_account_copies_and_resumes(self):
        state = {}
        res = self.run_pass(state)
        self.assertEqual(res["inserm"]["copié"], 2)
        self.assertEqual(res["inserm"]["en_attente"], 1)
        res = self.run_pass(state, now=NOW + timedelta(minutes=10))
        self.assertEqual(res["inserm"]["copié"], 1)
        res = self.run_pass(state, now=NOW + timedelta(minutes=20))
        self.assertEqual(sum(res["inserm"].values()), 0)
        self.assertEqual(self.gconn.stored[0][-1], '("Inserm")')

    def test_outlook_closed_is_a_note_not_an_error(self):
        state = {}
        self.run_pass(state, running=False)
        last = state["accounts"]["inserm"]["last"]
        self.assertIsNone(last["error"])
        self.assertIn("fermé", last["note"])

    def test_item_to_mime_keeps_headers_body_and_attachment(self):
        raw = outlook_source.item_to_mime(self.items[1])
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        self.assertEqual(msg["Subject"], "Commande labo")
        self.assertEqual(msg["Message-ID"], "<o-2@institut.fr>")
        self.assertIn("c@institut.fr", msg["From"])
        names = [p.get_filename() for p in msg.iter_attachments()]
        self.assertEqual(names, ["devis.pdf"])

    def test_item_to_mime_inline_image_goes_related(self):
        item = FakeOutlookItem("E9", NOW, "Avec image", mid="o-9@x", html='<p><img src="cid:logo1"></p>',
                               attachments=[FakeAttachment("logo.png", b"\x89PNG..", cid="logo1")])
        msg = BytesParser(policy=policy.default).parsebytes(outlook_source.item_to_mime(item))
        types = [p.get_content_type() for p in msg.walk()]
        self.assertIn("multipart/related", types)
        self.assertIn("image/png", types)


# ---- Utilitaires, configuration, identifiants --------------------------------

class Helpers(unittest.TestCase):
    def test_message_id_normalization(self):
        self.assertEqual(engine.normalize_message_id(" <a.b+c=d@x.fr> "), "a.b+c=d@x.fr")
        self.assertIsNone(engine.normalize_message_id("deux mots"))

    def test_imap_quote_and_date(self):
        self.assertEqual(engine.imap_quote('a"b\\c'), '"a\\"b\\\\c"')
        self.assertEqual(engine.imap_date(datetime(2026, 3, 5)), "05-Mar-2026")

    def test_find_all_mail_french_and_literal(self):
        class L:
            def list(self):
                return "OK", [b'(\\All \\HasNoChildren) "/" "[Gmail]/Tous les messages"']

        class Lit:
            def list(self):
                return "OK", [(b'(\\HasNoChildren \\All) "/" {14}', b"[Gmail]/Alle E"), b""]
        self.assertEqual(engine.find_gmail_all_mail(L()), '"[Gmail]/Tous les messages"')
        self.assertEqual(engine.find_gmail_all_mail(Lit()), '"[Gmail]/Alle E"')

    def test_describe_and_subject_normalisation(self):
        raw = b"From: =?utf-8?q?S=C3=A9verine?= <s@u-paris.fr>\r\nSubject: =?utf-8?q?Bio_Cellulaire=C2=A0:_cours?=\r\n\r\nx"
        info = engine.describe(raw)
        self.assertIn("Séverine", info["from"])
        self.assertEqual(engine.norm_subject(info["subject"]), engine.norm_subject("Bio Cellulaire : cours"))

    def test_friendly_errors(self):
        self.assertIn("mot de passe d'application",
                      engine.friendly_error("[ALERT] Application-specific password required"))
        self.assertIn("incorrect", engine.friendly_error("[AUTHENTICATIONFAILED] Invalid credentials"))


class ConfigTests(unittest.TestCase):
    def test_migration_from_v1_and_unique_ids(self):
        tmp = Path(tempfile.mkdtemp()) / "config.json"
        with mock.patch.object(config, "CONFIG_FILE", tmp), mock.patch.object(config, "DATA_DIR", tmp.parent), \
             mock.patch.object(credentials, "exists", lambda t: t == "MailBridge/u-paris"):
            conf = config.load()
        self.assertEqual([a["id"] for a in conf["accounts"]], ["u-paris"])
        self.assertTrue(conf["accounts"][0]["expects_redirect"])
        self.assertEqual(config.unique_id(conf, "Université Paris Cité"), "universite-paris-cite")
        conf["accounts"].append({"id": "yahoo"})
        self.assertEqual(config.unique_id(conf, "Yahoo"), "yahoo-2")

    def test_outlook_account_defaults_to_inbox(self):
        self.assertEqual(config.new_account("outlook")["folders"], ["Inbox"])

    def test_state_migration_from_v1(self):
        tmp = Path(tempfile.mkdtemp()) / "state.json"
        tmp.write_text('{"folders": {"INBOX": {"uidvalidity": 14, "last_uid": 9}}}', encoding="utf-8")
        state = engine.load_state(tmp)
        self.assertEqual(state["accounts"]["u-paris"]["folders"]["INBOX"]["last_uid"], 9)


@unittest.skipUnless(sys.platform == "win32", "Gestionnaire d'identifiants Windows uniquement")
class CredentialStore(unittest.TestCase):
    TARGET = "MailBridge/test-unitaire"

    def test_roundtrip_with_accents(self):
        try:
            credentials.write(self.TARGET, "utilisateur@exemple.fr", "mötdepässe é$€ 123")
            self.assertEqual(credentials.read(self.TARGET), ("utilisateur@exemple.fr", "mötdepässe é$€ 123"))
        finally:
            credentials.delete(self.TARGET)
        self.assertFalse(credentials.exists(self.TARGET))


if __name__ == "__main__":
    unittest.main(verbosity=2)
