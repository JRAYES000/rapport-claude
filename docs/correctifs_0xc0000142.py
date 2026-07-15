# -*- coding: utf-8 -*-
"""
Correctifs à intégrer dans rapport_claude.py (v2.16.0 -> v2.17.0)
Objectif : supprimer l'erreur « powershell.exe (0xc0000142) » lors des mises à
jour, durcir les sous-processus et sécuriser l'auto-update.

Chaque correctif est autonome et commenté. Aucune dépendance externe :
uniquement la bibliothèque standard + ctypes (déjà disponibles dans le build
PyInstaller actuel).
"""

import os
import ctypes
import subprocess

CREATE_NO_WINDOW = 0x08000000


# ---------------------------------------------------------------------------
# CORRECTIF 3 — un seul point d'entrée pour tous les sous-processus cachés.
# Remplacer chaque subprocess.run([...], capture_output=True, text=True)
# (schtasks, taskkill, cmd) par _run_hidden([...]) : plus aucune console
# n'est allouée (suppression des flashs et d'une cause d'échec 0xc0000142).
# ---------------------------------------------------------------------------
def _run_hidden(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.run(cmd, **kw)


# ---------------------------------------------------------------------------
# CORRECTIF 4 — en mode silencieux (--install-silent, --run), empêcher
# Windows d'afficher des boîtes d'erreur pour les processus enfants qui
# échouent à l'initialisation. Le mode d'erreur est hérité par les enfants.
# À appeler au tout début de main() quand args.install_silent ou args.run :
#     _suppress_child_error_dialogs()
# ---------------------------------------------------------------------------
def _suppress_child_error_dialogs():
    SEM_FAILCRITICALERRORS = 0x0001
    SEM_NOGPFAULTERRORBOX = 0x0002
    SEM_NOOPENFILEERRORBOX = 0x8000
    try:
        ctypes.windll.kernel32.SetErrorMode(
            SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CORRECTIF 2a — dossiers spéciaux sans PowerShell.
# Remplace les fragments "[Environment]::GetFolderPath('Startup'/'Desktop')".
# SHGetFolderPathW est stable depuis Windows XP et suit les redirections
# (OneDrive, GPO), contrairement à un chemin construit à la main.
# ---------------------------------------------------------------------------
def _special_folder(csidl):
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return buf.value


def startup_dir():
    return _special_folder(7)      # CSIDL_STARTUP


def desktop_dir():
    return _special_folder(16)     # CSIDL_DESKTOPDIRECTORY


# ---------------------------------------------------------------------------
# CORRECTIF 2b — création/suppression de raccourci .lnk en Python pur
# (COM IShellLink via ctypes, zéro PowerShell, zéro sous-processus).
# Remplace intégralement _shortcut_create / _shortcut_remove.
# ---------------------------------------------------------------------------
def _shortcut_create(folder, exe_path, args="", name=None,
                     description="Rapport d'activite Claude"):
    """folder : chemin réel (ex. startup_dir()), plus un fragment PowerShell."""
    name = name or SHORTCUT_FILE  # constante existante du programme
    path = os.path.join(folder, name)
    try:
        _write_lnk(path, exe_path, args, description)
    except Exception:
        pass  # non bloquant, comme aujourd'hui


def _shortcut_remove(folder, name=None):
    name = name or SHORTCUT_FILE
    try:
        p = os.path.join(folder, name)
        if os.path.isfile(p):
            os.remove(p)          # un .lnk est un simple fichier
    except Exception:
        pass


def _write_lnk(lnk_path, target, args, description):
    """Crée un .lnk via COM (IShellLinkW + IPersistFile), sans dépendance."""
    from ctypes import POINTER, Structure, c_void_p, c_ulong, c_ushort, c_ubyte, byref
    from ctypes import wintypes

    class GUID(Structure):
        _fields_ = [("D1", c_ulong), ("D2", c_ushort),
                    ("D3", c_ushort), ("D4", c_ubyte * 8)]

    def guid(s):
        import uuid
        u = uuid.UUID(s)
        g = GUID()
        g.D1, g.D2, g.D3 = u.time_low, u.time_mid, u.time_hi_version
        for i, b in enumerate(u.bytes[8:]):
            g.D4[i] = b
        return g

    CLSID_ShellLink = guid("00021401-0000-0000-C000-000000000046")
    IID_IShellLinkW = guid("000214F9-0000-0000-C000-000000000046")
    IID_IPersistFile = guid("0000010b-0000-0000-C000-000000000046")

    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    try:
        psl = c_void_p()
        if ole32.CoCreateInstance(byref(CLSID_ShellLink), None, 1,
                                  byref(IID_IShellLinkW), byref(psl)) != 0:
            raise OSError("CoCreateInstance ShellLink")

        def vtbl(iface, idx, restype, *argtypes):
            fn_ptr = ctypes.cast(
                ctypes.cast(iface, POINTER(POINTER(c_void_p)))[0][idx], c_void_p)
            proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
            return proto(fn_ptr.value)

        # IShellLinkW : 0 QI, 1 AddRef, 2 Release, 7 SetDescription,
        # 11 SetArguments, 17 SetIconLocation, 20 SetPath
        vtbl(psl, 20, ctypes.HRESULT, wintypes.LPCWSTR)(psl, target)
        vtbl(psl, 11, ctypes.HRESULT, wintypes.LPCWSTR)(psl, args or "")
        vtbl(psl, 7, ctypes.HRESULT, wintypes.LPCWSTR)(psl, description)
        vtbl(psl, 17, ctypes.HRESULT, wintypes.LPCWSTR, ctypes.c_int)(psl, target, 0)

        ppf = c_void_p()
        if vtbl(psl, 0, ctypes.HRESULT, ctypes.POINTER(GUID),
                ctypes.POINTER(c_void_p))(psl, byref(IID_IPersistFile), byref(ppf)) != 0:
            raise OSError("QueryInterface IPersistFile")
        # IPersistFile::Save = index 6
        vtbl(ppf, 6, ctypes.HRESULT, wintypes.LPCWSTR, wintypes.BOOL)(ppf, lnk_path, True)
        vtbl(ppf, 2, c_ulong)(ppf)   # Release
        vtbl(psl, 2, c_ulong)(psl)   # Release
    finally:
        ole32.CoUninitialize()


# ---------------------------------------------------------------------------
# CORRECTIF 1 — le plus important : lors d'une mise à jour silencieuse,
# NE PAS toucher aux raccourcis si le raccourci Démarrage existe déjà.
# Le chemin d'installation est constant, donc le .lnk reste valide ;
# les 3 lancements de PowerShell disparaissent du chemin de mise à jour.
#
# Dans install(), remplacer le bloc :
#     kill_tray(); remove_desktop_shortcut(); remove_status_shortcut()
#     add_to_startup(target_exe)
# par :
# ---------------------------------------------------------------------------
def _refresh_shortcuts_if_needed(target_exe, silent):
    lnk = os.path.join(startup_dir(), SHORTCUT_FILE)
    if silent and os.path.isfile(lnk):
        return                      # mise à jour : rien à faire, .lnk déjà bon
    remove_desktop_shortcut()       # versions ctypes ci-dessus (plus de PowerShell)
    remove_status_shortcut()
    add_to_startup(target_exe)      # -> _shortcut_create(startup_dir(), ...)


# ---------------------------------------------------------------------------
# CORRECTIF 5 — sécurité : vérifier la signature Authenticode du binaire
# téléchargé AVANT de l'exécuter (self_update). Aujourd'hui rien n'est
# vérifié : une compromission du stockage de téléchargement exécuterait du
# code arbitraire sur tout le parc.
#
# Dans self_update(), avant subprocess.Popen([exe, "--install-silent"], ...) :
#     if not _authenticode_ok(exe):
#         if log: log("  [maj] signature invalide -> mise à jour refusée.")
#         return False
# ---------------------------------------------------------------------------
def _authenticode_ok(path):
    from ctypes import Structure, POINTER, byref, c_void_p, c_ulong, sizeof
    from ctypes import wintypes

    class GUID(Structure):
        _fields_ = [("D1", c_ulong), ("D2", ctypes.c_ushort),
                    ("D3", ctypes.c_ushort), ("D4", ctypes.c_ubyte * 8)]

    class WTD_FILE_INFO(Structure):
        _fields_ = [("cbStruct", wintypes.DWORD),
                    ("pcwszFilePath", wintypes.LPCWSTR),
                    ("hFile", wintypes.HANDLE),
                    ("pgKnownSubject", c_void_p)]

    class WTD_DATA(Structure):
        _fields_ = [("cbStruct", wintypes.DWORD), ("pPolicyCallbackData", c_void_p),
                    ("pSIPClientData", c_void_p), ("dwUIChoice", wintypes.DWORD),
                    ("fdwRevocationChecks", wintypes.DWORD),
                    ("dwUnionChoice", wintypes.DWORD), ("pFile", POINTER(WTD_FILE_INFO)),
                    ("dwStateAction", wintypes.DWORD), ("hWVTStateData", wintypes.HANDLE),
                    ("pwszURLReference", wintypes.LPCWSTR),
                    ("dwProvFlags", wintypes.DWORD), ("dwUIContext", wintypes.DWORD),
                    ("pSignatureSettings", c_void_p)]

    action = GUID(0xAAC56B, 0xCD44, 0x11D0,
                  (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))
    fi = WTD_FILE_INFO(sizeof(WTD_FILE_INFO), path, None, None)
    data = WTD_DATA(sizeof(WTD_DATA), None, None, 2,  # WTD_UI_NONE
                    0, 1, ctypes.pointer(fi), 1, None, None, 0x10, 0, None)
    try:
        res = ctypes.windll.wintrust.WinVerifyTrust(None, byref(action), byref(data))
        data.dwStateAction = 2  # WTD_STATEACTION_CLOSE
        ctypes.windll.wintrust.WinVerifyTrust(None, byref(action), byref(data))
        return res == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# RAPPEL D'INTÉGRATION (résumé)
# 1. install(silent=True)  : utiliser _refresh_shortcuts_if_needed(...)   [bug]
# 2. _shortcut_create/_remove + startup_dir/desktop_dir : versions ctypes [bug + AV]
# 3. schtasks / taskkill / cmd : passer par _run_hidden(...)              [cosmétique]
# 4. main() en mode --install-silent / --run : _suppress_child_error_dialogs()
# 5. self_update() : _authenticode_ok(exe) avant Popen                    [sécurité]
# Puis : app_version = "2.17.0", rebuild + signature, upload ZIP, version.json.
# ---------------------------------------------------------------------------
