# -*- coding: utf-8 -*-
"""Persistent Windows notification icon, independent of the short sync passes.

Run with ``pythonw -m mailbridge.tray``. Only pywin32 is required. The scheduled
engine keeps ownership of synchronization; closing either window or icon does
not cancel scheduled passes. No credentials or raw messages are read here.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import threading
import time

import win32api
import win32con
import win32event
import win32gui

from . import ASSETS_DIR, BASE_DIR, DATA_DIR
from .background import launch, task_enabled

# User-adjustable refresh frequencies and stable Windows identifiers.
POLL_SECONDS = 5
TASK_POLL_SECONDS = 30
LOCK_STALE_SECONDS = 30 * 60  # same lifetime as engine.RunLock
WINDOW_CLASS = "MailBridgeTrayWindow"
MUTEX_NAME = "Local\\MailBridgeTray"
ICON_ID = 1
WM_TRAY = win32con.WM_APP + 1
WM_REFRESH = win32con.WM_APP + 2
CMD_OPEN, CMD_SYNC, CMD_EXIT = 1001, 1002, 1003
log = logging.getLogger("mailbridge.tray")


def read_json(path) -> dict:
    """Read snapshots without creating or migrating any user files."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}


def status_text(enabled: bool | None, state: dict, conf: dict, busy: bool) -> str:
    """Describe automation honestly, including paused tasks and recorded errors."""
    if busy:
        return "GmailBridge : synchronisation en cours"
    if enabled is None:
        return "GmailBridge : automatisation non installée"
    if not enabled:
        return "GmailBridge : synchronisation automatique en pause"
    last = state.get("last_pass") or {}
    if last.get("outcome", "ok") != "ok":
        return "GmailBridge : erreur de synchronisation, ouvrez l'application"
    if any(c.get("enabled", True) for c in conf.get("calendars", [])) and (state.get("calendar_pass") or {}).get("error"):
        return "GmailBridge : synchronisation des agendas à vérifier"
    for key in ("accounts", "calendars"):
        for source in conf.get(key, []):
            previous = state.get(key, {}).get(source["id"], {}).get("last") or {}
            if source.get("enabled", True) and previous.get("error"):
                return "GmailBridge : un compte ou agenda est à vérifier"
    if not conf.get("accounts") and not conf.get("calendars"):
        return "GmailBridge : actif, ajoutez un compte dans l'application"
    if last.get("time"):
        return f"GmailBridge : actif en arrière-plan. Dernière passe : {last['time'].replace('T', ' ')}"
    return "GmailBridge : actif en arrière-plan, en attente de synchronisation"


class TrayIcon:
    """Own the hidden window and icon on the Windows message-pump thread."""

    def __init__(self):
        self.stop = threading.Event()
        self.tooltip = "GmailBridge : vérification de l'état…"
        self.added = False
        self.sync_process = None
        self.taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")
        instance = win32api.GetModuleHandle(None)
        wc = win32gui.WNDCLASS()
        wc.hInstance, wc.lpszClassName = instance, WINDOW_CLASS
        wc.lpfnWndProc = self.window_proc
        win32gui.RegisterClass(wc)
        # A hidden top-level window receives TaskbarCreated broadcasts after an
        # Explorer restart. Message-only windows do not receive that broadcast.
        self.hwnd = win32gui.CreateWindow(
            WINDOW_CLASS, "GmailBridge notification", 0, 0, 0, 0, 0,
            0, 0, instance, None,
        )
        self.hicon = win32gui.LoadImage(
            0, str(ASSETS_DIR / "gmailbridge.ico"), win32con.IMAGE_ICON,
            32, 32, win32con.LR_LOADFROMFILE,
        )

    def update_icon(self):
        """Register or refresh the icon, retrying if Explorer is not ready yet."""
        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        data = (self.hwnd, ICON_ID, flags, WM_TRAY, self.hicon, self.tooltip[:127])
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY if self.added else win32gui.NIM_ADD, data)
            self.added = True
        except win32gui.error:
            self.added = False
            log.exception("Impossible de mettre à jour l'icône")

    def poll(self):
        """Read local state off the UI thread so the context menu stays responsive."""
        next_task_check, enabled = 0, None
        while not self.stop.is_set():
            try:
                if time.monotonic() >= next_task_check:
                    enabled = task_enabled()
                    next_task_check = time.monotonic() + TASK_POLL_SECONDS
                state = read_json(DATA_DIR / "state.json")
                conf = read_json(DATA_DIR / "config.json")
                try:
                    busy = time.time() - (DATA_DIR / "mailbridge.lock").stat().st_mtime < LOCK_STALE_SECONDS
                except FileNotFoundError:
                    busy = False
                self.tooltip = status_text(enabled, state, conf, busy)
            except Exception:
                self.tooltip = "GmailBridge : état indisponible, ouvrez l'application"
                log.exception("Lecture de l'état impossible")
            if not self.stop.is_set():
                win32gui.PostMessage(self.hwnd, WM_REFRESH, 0, 0)
            self.stop.wait(POLL_SECONDS)

    def show_menu(self):
        """Offer the usual open/sync actions and an explicitly icon-only exit."""
        menu = win32gui.CreatePopupMenu()
        try:
            win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_GRAYED, 0, self.tooltip)
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_OPEN, "Ouvrir GmailBridge")
            running = self.sync_process is not None and self.sync_process.poll() is None
            flags = win32con.MF_STRING | (win32con.MF_GRAYED if running else 0)
            win32gui.AppendMenu(menu, flags, CMD_SYNC, "Synchroniser maintenant")
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_EXIT, "Masquer l'icône (synchro maintenue)")
            x, y = win32gui.GetCursorPos()
            win32gui.SetForegroundWindow(self.hwnd)
            command = win32gui.TrackPopupMenu(
                menu, win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON,
                x, y, 0, self.hwnd, None,
            )
            win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
            self.command(command)
        finally:
            win32gui.DestroyMenu(menu)

    def command(self, command):
        """Dispatch actions; the engine's existing lock prevents concurrent passes."""
        if command == CMD_OPEN:
            launch(str(BASE_DIR / "GmailBridge.pyw"))
        elif command == CMD_SYNC:
            if self.sync_process is None or self.sync_process.poll() is not None:
                self.sync_process = launch("-m", "mailbridge.engine")
        elif command == CMD_EXIT:
            win32gui.DestroyWindow(self.hwnd)

    def window_proc(self, hwnd, message, wparam, lparam):
        """Handle shell callbacks and restore registration after Explorer restarts."""
        if message == self.taskbar_created:
            self.added = False
            self.update_icon()
        elif message == WM_REFRESH:
            self.update_icon()
        elif message == WM_TRAY:
            if lparam == win32con.WM_LBUTTONUP:
                self.command(CMD_OPEN)
            elif lparam in (win32con.WM_RBUTTONUP, win32con.WM_CONTEXTMENU):
                self.show_menu()
        elif message == win32con.WM_CLOSE:
            win32gui.DestroyWindow(hwnd)
        elif message == win32con.WM_DESTROY:
            self.stop.set()
            try:
                win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, ICON_ID))
            except win32gui.error:
                pass  # Explorer may already have removed the icon.
            win32gui.PostQuitMessage(0)
        else:
            return win32gui.DefWindowProc(hwnd, message, wparam, lparam)
        return 0

    def run(self):
        """Keep only a native message pump and a sleeping state-reader in memory."""
        self.update_icon()
        worker = threading.Thread(target=self.poll, name="GmailBridge tray status", daemon=True)
        worker.start()
        try:
            win32gui.PumpMessages()
        finally:
            self.stop.set()
            worker.join(timeout=12)
            win32gui.DestroyIcon(self.hicon)
            win32gui.UnregisterClass(WINDOW_CLASS, win32api.GetModuleHandle(None))


def stop_existing(timeout: float = 30) -> None:
    """Close the old icon and await mutex disposal before an installer restarts it.

    WM_CLOSE destroys the window before the polling thread has necessarily
    stopped. Waiting for the mutex to disappear also covers that cleanup period.
    """
    hwnd = win32gui.FindWindow(WINDOW_CLASS, None)
    if hwnd:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    deadline = time.monotonic() + timeout
    while True:
        try:
            handle = win32event.OpenMutex(win32con.SYNCHRONIZE, False, MUTEX_NAME)
        except win32api.error as exc:
            if exc.winerror == 2:  # ERROR_FILE_NOT_FOUND
                return
            raise
        win32api.CloseHandle(handle)
        if time.monotonic() >= deadline:
            raise TimeoutError("L'ancienne icône GmailBridge ne s'est pas arrêtée.")
        time.sleep(0.1)


def main():
    """Hold a session-local mutex for the entire icon lifetime, including cleanup."""
    if "--stop" in sys.argv[1:]:
        stop_existing()
        return
    mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
    duplicate = win32api.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    try:
        if duplicate:
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            DATA_DIR / "tray.log", maxBytes=200_000, backupCount=1, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        TrayIcon().run()
    finally:
        win32api.CloseHandle(mutex)


if __name__ == "__main__":
    main()
