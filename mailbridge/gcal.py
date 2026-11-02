# -*- coding: utf-8 -*-
"""
gcal.py
=======
Accès à Google Agenda (API Calendar v3), sans aucune bibliothèque externe.

Pourquoi OAuth ?
    Google Agenda n'accepte pas les mots de passe d'application (contrairement à Gmail en IMAP).
    MailBridge utilise donc le parcours OAuth « application de bureau » recommandé par Google :
    vous créez une fois un « client OAuth » dans votre propre projet Google Cloud (guide :
    docs/GOOGLE_SETUP.md), vous l'importez dans MailBridge, puis vous vous connectez dans le
    navigateur. Seul le jeton de renouvellement est conservé, dans le coffre d'identifiants
    Windows ; aucun mot de passe Google n'est jamais vu par MailBridge.

Détails techniques
    * Redirection « loopback » (http://127.0.0.1:<port>) + PKCE (RFC 7636).
    * Jeton d'accès renouvelé automatiquement ; nouvelles tentatives sur 429 / 5xx.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from . import DATA_DIR, credentials

# ----------------------------- Paramètres ------------------------------------
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar"
CLIENT_FILE = DATA_DIR / "google_client.json"     # client OAuth importé (jamais versionné)
TOKEN_CRED = "MailBridge/google"                  # coffre Windows : utilisateur = e-mail, secret = jeton
HTTP_TIMEOUT_S = 30
MAX_RETRIES = 4
AUTH_TIMEOUT_S = 300                              # attente maximale de la connexion dans le navigateur
CLIENT_GLOB = "client_secret*.json"               # nom du fichier téléchargé depuis Google Cloud

# Pages exactes de Google Cloud, dans l'ordre de la création de l'accès (liens du guide officiel
# « Calendar API Python quickstart »). Les clés sont reprises par l'interface (web/app.js).
CONSOLE = {
    "enable": "https://console.cloud.google.com/flows/enableapi?apiid=calendar-json.googleapis.com",
    "branding": "https://console.developers.google.com/auth/branding",
    "audience": "https://console.developers.google.com/auth/audience",
    "clients": "https://console.developers.google.com/auth/clients",
    "permissions": "https://myaccount.google.com/permissions",
}
# -----------------------------------------------------------------------------


class GoogleError(Exception):
    """Erreur de l'API Google (message lisible).

    `fix` nomme la page Google (clé de CONSOLE) qui corrige le problème, si elle existe :
    l'interface en fait un bouton « Corriger ».
    """

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.fix = fix


class NotConnected(GoogleError):
    """Google Agenda n'est pas (ou plus) connecté."""


def explain(detail: str, code: int = 0) -> GoogleError:
    """Traduit une réponse d'erreur Google (texte JSON brut) en phrase claire + page de correction."""
    low = detail.lower()
    if "service_disabled" in low or "accessnotconfigured" in low or "has not been used in project" in low:
        return GoogleError("L'API Google Agenda n'est pas activée dans votre projet Google.", "enable")
    if "invalid_client" in low or "deleted_client" in low:
        return GoogleError("Google ne reconnaît plus cet accès (client supprimé ou secret modifié) : "
                           "téléchargez à nouveau le fichier JSON et importez-le.", "clients")
    if "unauthorized_client" in low:
        return GoogleError("Cet accès n'est pas de type « Application de bureau » : recréez-le.", "clients")
    if "invalid_grant" in low:
        return NotConnected("Autorisation Google expirée ou révoquée : reconnectez Google Agenda. Si cela "
                            "revient chaque semaine, publiez l'application (état « En production »).",
                            "audience")
    if "insufficient" in low and "scope" in low:
        return NotConnected("L'accès à l'agenda n'a pas été coché lors de la connexion : reconnectez-vous "
                            "et cochez la case Google Agenda.")
    return GoogleError(f"Google a refusé la demande ({code}) : {detail[:200]}" if code
                       else f"Google a refusé la demande : {detail[:200]}")


# Erreurs renvoyées par Google à la page de retour de la connexion (paramètre ?error=)
AUTH_ERRORS = {
    "access_denied": ("Connexion refusée. Si Google a affiché « Accès bloqué », l'application est encore en "
                      "mode Test : publiez-la (bouton « Publier l'application ») puis réessayez.", "audience"),
    "admin_policy_enforced": ("Votre organisation interdit cette connexion : utilisez un compte Gmail "
                              "personnel.", ""),
}


# ---- Client OAuth ------------------------------------------------------------

def load_client() -> dict | None:
    """{'client_id', 'client_secret'} du client importé, ou None."""
    try:
        data = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    block = data.get("installed") or data.get("web") or data
    if block.get("client_id") and block.get("client_secret"):
        return {"client_id": block["client_id"], "client_secret": block["client_secret"]}
    return None


def save_client(client_id: str, client_secret: str) -> None:
    """Enregistre le client OAuth (identifiant + secret de l'application de bureau)."""
    client_id, client_secret = client_id.strip(), client_secret.strip()
    if not client_id.endswith(".apps.googleusercontent.com") or not client_secret:
        raise GoogleError("Identifiant client invalide : il doit finir par .apps.googleusercontent.com")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_FILE.write_text(json.dumps({"installed": {"client_id": client_id, "client_secret": client_secret}},
                                      indent=2), encoding="utf-8")


def save_client_from_json(text: str) -> None:
    """Importe le fichier « client_secret_….json » téléchargé depuis Google Cloud."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise GoogleError("Ce fichier n'est pas un fichier JSON de client OAuth.") from exc
    if not isinstance(data, dict):
        raise GoogleError("Ce fichier n'est pas un fichier JSON de client OAuth.")
    if "web" in data and "installed" not in data:
        # Un client « Application Web » échoue plus tard avec redirect_uri_mismatch : refus immédiat.
        raise GoogleError("Ce fichier est un accès « Application Web ». Créez plutôt un client de type "
                          "« Application de bureau », puis téléchargez son fichier JSON.", "clients")
    block = data.get("installed") or {}
    save_client(block.get("client_id", ""), block.get("client_secret", ""))


def downloads_dir() -> Path:
    """Dossier Téléchargements réel de Windows (il peut avoir été déplacé, par ex. sur D:)."""
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

        # FOLDERID_Downloads = {374DE290-123F-4565-9164-39C4925E467B}
        fid = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0:
            path = Path(out.value)
            ctypes.windll.ole32.CoTaskMemFree(out)
            return path
    except (AttributeError, OSError):
        pass
    return Path.home() / "Downloads"


def find_downloaded_client(folder: Path | None = None) -> Path | None:
    """Fichier client_secret_….json le plus récent du dossier Téléchargements, ou None."""
    folder = folder or downloads_dir()
    try:
        files = [p for p in folder.glob(CLIENT_GLOB) if p.is_file()]
    except OSError:
        return None
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


def import_client_file(path: Path) -> None:
    """Importe un fichier client téléchargé (lecture seule : le fichier d'origine n'est pas modifié)."""
    save_client_from_json(Path(path).read_text(encoding="utf-8"))


def connected() -> bool:
    return load_client() is not None and credentials.exists(TOKEN_CRED)


def account_email() -> str:
    return credentials.read(TOKEN_CRED)[0] if credentials.exists(TOKEN_CRED) else ""


def disconnect() -> None:
    credentials.delete(TOKEN_CRED)


# ---- HTTP --------------------------------------------------------------------

def _post_form(url: str, fields: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise explain(exc.read().decode("utf-8", "replace"), exc.code) from exc
    except (urllib.error.URLError, socket.timeout) as exc:
        raise GoogleError(f"Google injoignable : vérifiez la connexion Internet ({exc}).") from exc


# ---- Connexion dans le navigateur -------------------------------------------

_DONE_PAGE = """<!doctype html><meta charset="utf-8"><title>MailBridge</title>
<body style="font:16px Segoe UI,system-ui;background:#0B0C11;color:#EDEEF4;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center"><div style="font-size:44px">{icon}</div><h2>{title}</h2>
<p style="color:#8C92A6">{text}</p></div></body>"""


_cancel = threading.Event()   # posé par cancel_authorize() (bouton « Annuler » de l'interface)


def cancel_authorize() -> None:
    """Interrompt une connexion en attente dans le navigateur."""
    _cancel.set()


def authorize(timeout_s: int = AUTH_TIMEOUT_S, open_browser=webbrowser.open) -> str:
    """Ouvre la page de connexion Google et attend l'autorisation. Renvoie l'e-mail connecté."""
    client = load_client()
    if not client:
        raise GoogleError("Importez d'abord le fichier client OAuth (voir le guide).")
    _cancel.clear()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (nom imposé par http.server)
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if query.get("state") != state:
                self.send_response(404)
                self.end_headers()
                return
            result.update(query)
            good = "code" in query
            page = _DONE_PAGE.format(icon="✅" if good else "⚠️",
                                     title="Google Agenda est connecté" if good else "Connexion annulée",
                                     text="Vous pouvez fermer cet onglet et revenir à MailBridge." if good
                                     else "Revenez à MailBridge pour réessayer.")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

        def log_message(self, *args):  # silence
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    redirect = f"http://127.0.0.1:{server.server_address[1]}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "code_challenge": challenge,
        "code_challenge_method": "S256", "state": state})
    open_browser(url)
    deadline = time.time() + timeout_s
    try:
        while not result and time.time() < deadline and not _cancel.is_set():
            server.handle_request()
    finally:
        server.server_close()
    if "code" not in result:
        if result.get("error"):
            message, fix = AUTH_ERRORS.get(result["error"], (f"Connexion Google refusée : {result['error']}", ""))
            raise GoogleError(message, fix)
        raise GoogleError("Connexion annulée." if _cancel.is_set()
                          else "Délai dépassé : la connexion n'a pas été validée dans le navigateur.")
    tokens = _post_form(TOKEN_URL, {"code": result["code"], "client_id": client["client_id"],
                                    "client_secret": client["client_secret"], "redirect_uri": redirect,
                                    "grant_type": "authorization_code", "code_verifier": verifier})
    if "refresh_token" not in tokens:
        raise GoogleError("Google n'a pas fourni de jeton durable : réessayez la connexion.")
    cal = GoogleCalendar(refresh_token=tokens["refresh_token"], client=client)
    cal._token, cal._expires = tokens["access_token"], time.time() + int(tokens.get("expires_in", 3600)) - 60
    email = cal.request("GET", "/users/me/calendarList/primary").get("id", "compte Google")
    credentials.write(TOKEN_CRED, email, tokens["refresh_token"])
    return email


def check_access() -> dict:
    """Vérifie réellement l'accès : renouvelle le jeton puis lit la liste des agendas modifiables.

    Renvoie {'ok', 'email', 'calendars' (nombre), 'message', 'fix'} ; ne lève jamais d'exception,
    pour que l'interface puisse toujours afficher un verdict clair.
    """
    email = account_email()
    try:
        n = len(GoogleCalendar().calendars())
    except GoogleError as exc:
        return {"ok": False, "email": email, "calendars": 0, "message": str(exc), "fix": exc.fix}
    except Exception as exc:  # coffre Windows illisible, réponse inattendue…
        return {"ok": False, "email": email, "calendars": 0, "message": f"Vérification impossible : {exc}", "fix": ""}
    return {"ok": True, "email": email, "calendars": n, "fix": "",
            "message": f"Accès vérifié · {n} agenda{'s' if n > 1 else ''} modifiable{'s' if n > 1 else ''}"}


# ---- Client de l'API ------------------------------------------------------------

class GoogleCalendar:
    """Petit client de l'API Google Calendar v3 (renouvellement du jeton, reprises)."""

    def __init__(self, refresh_token: str | None = None, client: dict | None = None):
        self.client = client or load_client()
        if not self.client:
            raise NotConnected("Google Agenda n'est pas configuré.")
        if refresh_token is None:
            if not credentials.exists(TOKEN_CRED):
                raise NotConnected("Google Agenda n'est pas connecté.")
            refresh_token = credentials.read(TOKEN_CRED)[1]
        self.refresh_token = refresh_token
        self._token, self._expires = None, 0.0

    def _access_token(self) -> str:
        if not self._token or time.time() >= self._expires:
            data = _post_form(TOKEN_URL, {"client_id": self.client["client_id"],
                                          "client_secret": self.client["client_secret"],
                                          "refresh_token": self.refresh_token, "grant_type": "refresh_token"})
            self._token = data["access_token"]
            self._expires = time.time() + int(data.get("expires_in", 3600)) - 60
        return self._token

    def request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        url = API + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        for attempt in range(MAX_RETRIES):
            req = urllib.request.Request(url, data=data, method=method, headers={
                "Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                    raw = resp.read()
                    return json.loads(raw.decode("utf-8")) if raw else {}
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410) and method == "DELETE":
                    return {}                                    # déjà supprimé : rien à faire
                if exc.code == 401 and attempt == 0:
                    self._token = None                           # jeton expiré : on renouvelle
                    continue
                detail = exc.read().decode("utf-8", "replace")
                # 403 = limite de débit OU refus définitif (API désactivée…) : on ne réessaie que le premier
                transient = exc.code in (429, 500, 502, 503) or (exc.code == 403 and "ratelimit" in detail.lower())
                if transient and attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)                     # limite de débit : on patiente
                    continue
                raise explain(detail, exc.code) from exc
            except (urllib.error.URLError, socket.timeout) as exc:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise GoogleError(f"Google injoignable : {exc}") from exc
        raise GoogleError("API Google : trop de tentatives")

    # ---- agendas et événements ---------------------------------------------
    def calendars(self) -> list[dict]:
        items = self.request("GET", "/users/me/calendarList", {"minAccessRole": "writer"}).get("items", [])
        return [{"id": c["id"], "name": c.get("summaryOverride") or c.get("summary", c["id"]),
                 "primary": bool(c.get("primary")), "color": c.get("backgroundColor", "#4285F4")} for c in items]

    def create_calendar(self, name: str) -> str:
        return self.request("POST", "/calendars", body={"summary": name})["id"]

    def list_events(self, calendar_id: str, time_min: str, time_max: str, private_filter: str | None = None) -> list:
        params = {"timeMin": time_min, "timeMax": time_max, "singleEvents": "true", "maxResults": 2500,
                  "showDeleted": "false"}
        if private_filter:
            params["privateExtendedProperty"] = private_filter
        events, token = [], None
        while True:
            if token:
                params["pageToken"] = token
            page = self.request("GET", f"/calendars/{urllib.parse.quote(calendar_id)}/events", params)
            events.extend(page.get("items", []))
            token = page.get("nextPageToken")
            if not token:
                return events

    def insert(self, calendar_id: str, body: dict) -> dict:
        return self.request("POST", f"/calendars/{urllib.parse.quote(calendar_id)}/events", body=body)

    def patch(self, calendar_id: str, event_id: str, body: dict) -> dict:
        return self.request("PATCH", f"/calendars/{urllib.parse.quote(calendar_id)}/events/{event_id}", body=body)

    def delete(self, calendar_id: str, event_id: str) -> None:
        self.request("DELETE", f"/calendars/{urllib.parse.quote(calendar_id)}/events/{event_id}")
