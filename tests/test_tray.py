# -*- coding: utf-8 -*-
"""Offline checks for truthful tray status and the Windows task XML parser."""

import subprocess
import unittest
from unittest.mock import patch

from mailbridge.background import task_enabled
from mailbridge.tray import status_text


class TrayStatusTests(unittest.TestCase):
    """An icon must not describe paused or failing automation as healthy."""

    def setUp(self):
        self.conf = {"accounts": [{"id": "source", "enabled": True}]}
        self.state = {"last_pass": {"time": "2026-11-02T14:30:00", "outcome": "ok"}}

    def test_active_status_includes_last_pass(self):
        text = status_text(True, self.state, self.conf, False)
        self.assertIn("actif en arrière-plan", text)
        self.assertIn("14:30:00", text)

    def test_disabled_and_missing_tasks_never_report_active(self):
        self.assertIn("en pause", status_text(False, self.state, self.conf, False))
        self.assertIn("non installée", status_text(None, self.state, self.conf, False))

    def test_manual_sync_can_run_while_automation_is_paused(self):
        self.assertIn("en cours", status_text(False, self.state, self.conf, True))

    def test_failed_pass_and_source_errors_are_visible(self):
        self.state["last_pass"]["outcome"] = "Connexion impossible"
        self.assertIn("erreur", status_text(True, self.state, self.conf, False))
        self.state["last_pass"]["outcome"] = "ok"
        self.state["accounts"] = {"source": {"last": {"error": "Authentification"}}}
        self.assertIn("à vérifier", status_text(True, self.state, self.conf, False))
        self.conf["accounts"][0]["enabled"] = False
        self.assertIn("actif", status_text(True, self.state, self.conf, False))

    def test_calendar_error_is_visible(self):
        self.conf["calendars"] = [{"id": "work"}]
        self.state["calendars"] = {"work": {"last": {"error": "Google indisponible"}}}
        self.assertIn("à vérifier", status_text(True, self.state, self.conf, False))

    def test_global_calendar_error_only_affects_enabled_calendars(self):
        self.state["calendar_pass"] = {"error": "Connexion Google requise"}
        self.conf["calendars"] = [{"id": "work"}]
        self.assertIn("à vérifier", status_text(True, self.state, self.conf, False))
        self.conf["calendars"][0]["enabled"] = False
        self.assertIn("actif", status_text(True, self.state, self.conf, False))

    def test_first_launch_requests_configuration(self):
        self.assertIn("ajoutez un compte", status_text(True, {}, {}, False))
        self.assertIn("en attente", status_text(True, {}, self.conf, False))


class TaskStatusTests(unittest.TestCase):
    """Use Windows UTF-16 output, including its default XML namespace."""

    @patch("mailbridge.background.subprocess.run")
    def test_namespaced_utf16_enabled_and_disabled(self, run):
        for value in ("true", "false"):
            xml = ('<?xml version="1.0" encoding="UTF-16"?>'
                   '<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
                   f'<Settings><Enabled>{value}</Enabled></Settings></Task>')
            run.return_value = subprocess.CompletedProcess([], 0, xml.encode("utf-16"))
            self.assertIs(task_enabled(), value == "true")

    @patch("mailbridge.background.subprocess.run")
    def test_absent_task(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, b"")
        self.assertIsNone(task_enabled())

    @patch("mailbridge.background.subprocess.run")
    def test_redirected_oem_bytes_with_utf16_declaration(self, run):
        xml = ('<?xml version="1.0" encoding="UTF-16"?>'
               '<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
               '<Settings><Enabled>false</Enabled></Settings></Task>')
        run.return_value = subprocess.CompletedProcess([], 0, xml.encode("ascii"))
        self.assertIs(task_enabled(), False)


if __name__ == "__main__":
    unittest.main()
