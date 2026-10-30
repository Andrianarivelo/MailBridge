# -*- coding: utf-8 -*-
"""
credentials.py
==============
Lecture, écriture et suppression d'identifiants dans le Gestionnaire
d'identifiants Windows (« Identifiants Windows > Informations d'identification
génériques »), sans aucune dépendance externe (uniquement ctypes).

Pourquoi le Gestionnaire d'identifiants ?
    * les mots de passe ne sont jamais écrits en clair dans un fichier du projet ;
    * Windows les chiffre avec la session de l'utilisateur (DPAPI) ;
    * on peut les voir / supprimer à la main dans le Panneau de configuration.

Format : identifiant de type GENERIC, mot de passe stocké en UTF-16-LE
(même format que la commande `cmdkey /generic:...`).
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes as wt

# Constantes de l'API Win32 (wincred.h)
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2  # survit aux redémarrages, propre à cet utilisateur
ERROR_NOT_FOUND = 1168


class CredentialNotFound(Exception):
    """L'identifiant demandé n'existe pas dans le Gestionnaire d'identifiants."""


class _CREDENTIAL(ctypes.Structure):
    """Miroir exact de la structure CREDENTIALW de wincred.h."""

    _fields_ = [
        ("Flags", wt.DWORD),
        ("Type", wt.DWORD),
        ("TargetName", wt.LPWSTR),
        ("Comment", wt.LPWSTR),
        ("LastWritten", wt.FILETIME),
        ("CredentialBlobSize", wt.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wt.DWORD),
        ("AttributeCount", wt.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wt.LPWSTR),
        ("UserName", wt.LPWSTR),
    ]


_PCREDENTIAL = ctypes.POINTER(_CREDENTIAL)

if sys.platform == "win32":
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    _CredReadW = _advapi32.CredReadW
    _CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(_PCREDENTIAL)]
    _CredReadW.restype = wt.BOOL

    _CredWriteW = _advapi32.CredWriteW
    _CredWriteW.argtypes = [_PCREDENTIAL, wt.DWORD]
    _CredWriteW.restype = wt.BOOL

    _CredDeleteW = _advapi32.CredDeleteW
    _CredDeleteW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD]
    _CredDeleteW.restype = wt.BOOL

    _CredFree = _advapi32.CredFree
    _CredFree.argtypes = [ctypes.c_void_p]
    _CredFree.restype = None


def read(target: str) -> tuple[str, str]:
    """Renvoie (nom_utilisateur, mot_de_passe) pour l'entrée `target`.

    Lève CredentialNotFound si l'entrée n'existe pas.
    """
    pcred = _PCREDENTIAL()
    if not _CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            raise CredentialNotFound(
                f"Identifiant « {target} » absent du Gestionnaire d'identifiants Windows. "
                "Ouvrez MailBridge et renseignez le compte."
            )
        raise ctypes.WinError(err)
    try:
        cred = pcred.contents
        blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return (cred.UserName or ""), blob.decode("utf-16-le")
    finally:
        _CredFree(pcred)  # la mémoire est allouée par Windows, on la rend


def write(target: str, username: str, password: str, comment: str = "MailBridge") -> None:
    """Crée ou remplace l'entrée `target` avec ce nom d'utilisateur et ce mot de passe."""
    blob = password.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(blob, len(blob))  # garde la mémoire vivante pendant l'appel
    cred = _CREDENTIAL()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.Comment = comment
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = username
    if not _CredWriteW(ctypes.byref(cred), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def delete(target: str) -> bool:
    """Supprime l'entrée `target`. Renvoie False si elle n'existait pas."""
    if _CredDeleteW(target, CRED_TYPE_GENERIC, 0):
        return True
    err = ctypes.get_last_error()
    if err == ERROR_NOT_FOUND:
        return False
    raise ctypes.WinError(err)


def exists(target: str) -> bool:
    """Vrai si l'entrée `target` existe."""
    try:
        read(target)
        return True
    except CredentialNotFound:
        return False
