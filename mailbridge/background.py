# -*- coding: utf-8 -*-
"""Shared Windows launch helpers. No WebView or mailbox access is needed here."""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from . import BASE_DIR

TASK_NAME = "MailBridge"
TRAY_TASK_NAME = "MailBridgeTray"
NO_WINDOW = 0x08000000


def task_enabled() -> bool | None:
    """Read the sync task, distinguishing disabled automation from a missing task.

    Redirected schtasks output can use the OEM code page even though its XML
    declaration says UTF-16. Decode the actual bytes before parsing the settings.
    """
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/XML"],
        capture_output=True, creationflags=NO_WINDOW, timeout=10,
    )
    if result.returncode:
        return None
    raw = result.stdout
    encoding = "utf-16" if b"\x00" in raw[:100] or raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "oem"
    text = raw.decode(encoding, "replace")
    # Once decoded, the "UTF-16" declaration is false and ElementTree rejects it: drop it.
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text.lstrip("﻿"))
    root = ET.fromstring(text)
    enabled = root.find("{*}Settings/{*}Enabled")
    return enabled is None or (enabled.text or "").strip().lower() != "false"


def launch(*args: str) -> subprocess.Popen:
    """Launch a GmailBridge component with the same Python, without a console."""
    executable = Path(sys.executable)
    windowless = executable.with_name("pythonw.exe")
    return subprocess.Popen(
        [str(windowless if windowless.exists() else executable), *args],
        cwd=str(BASE_DIR), creationflags=NO_WINDOW,
    )


def ensure_tray() -> None:
    """Start the lightweight icon. Its named mutex prevents duplicate instances."""
    launch("-m", "mailbridge.tray")
