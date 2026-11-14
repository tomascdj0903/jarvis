"""Mises à jour automatiques depuis les Releases GitHub."""
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

from . import __version__

REPO = "tomascdj0903/jarvis"
API = f"https://api.github.com/repos/{REPO}/releases/latest"


def _v(s: str):
    return tuple(int(x) for x in s.lstrip("vV").split(".") if x.isdigit())


def cleanup_temp():
    """Supprime les dossiers de mise à jour des fois précédentes (~350 Mo chacun)."""
    import shutil
    cur = Path(sys.executable).resolve()
    for d in Path(tempfile.gettempdir()).glob("jarvis_upd_*"):
        try:
            if d not in cur.parents:  # jamais le dossier d'où l'on s'exécute
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


def exe_machine(path) -> str:
    """Processeur visé par un .exe (en-tête PE) : « x64 », « ARM64 » ou « x86 »."""
    import struct
    with open(path, "rb") as f:
        f.seek(0x3C)
        pe = struct.unpack("<I", f.read(4))[0]
        f.seek(pe + 4)
        mach = struct.unpack("<H", f.read(2))[0]
    return {0x8664: "x64", 0xAA64: "ARM64", 0x14C: "x86"}.get(mach, hex(mach))


def native_arm64() -> bool:
    """Vrai si Windows tourne sur un processeur ARM64 (même si ce Jarvis est la version x64 émulée)."""
    try:
        import ctypes
        pm, nm = ctypes.c_ushort(), ctypes.c_ushort()
        k = ctypes.windll.kernel32
        if k.IsWow64Process2(k.GetCurrentProcess(), ctypes.byref(pm), ctypes.byref(nm)):
            return nm.value == 0xAA64
    except Exception:
        pass
    return False


def check():
    """Renvoie (version, url_zip, notes) si une version plus récente existe, sinon None."""
    try:
        r = requests.get(API, timeout=8, headers={"Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            return None
        d = r.json()
        tag = d.get("tag_name", "")
        if not tag or _v(tag) <= _v(__version__):
            return None
        assets = d.get("assets", [])
        arm = native_arm64() and any(a["name"] == "Jarvis-Windows-ARM64.pkg" for a in assets)
        want = "Jarvis-Windows-ARM64.pkg" if arm else "Jarvis-Windows.zip"
        # nom EXACT : jamais la version d'un autre processeur
        zips = [a for a in assets if a["name"] == want]
        sums = [a for a in assets if a["name"] == zips[0]["name"] + ".sha256"] if zips else []
        if zips:
            url = zips[0]["browser_download_url"]
            check.sha_url = sums[0]["browser_download_url"] if sums else None
            return tag, url, (d.get("body") or "")[:400]
    except Exception:
        pass
    return None


def install(url: str, progress=lambda p: None) -> bool:
    """Télécharge le zip, puis remplace le dossier de l'exe et relance Jarvis.
    Ne fonctionne que pour la version .exe (en mode script, utiliser git pull)."""
    if not getattr(sys, "frozen", False):
        return False
    app_dir = Path(sys.executable).parent
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_upd_"))
    zpath = tmp / "jarvis.zip"
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0)) or 1
        done = 0
        with open(zpath, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                done += len(chunk)
                progress(done / total)
    # contrôle d'intégrité : le fichier reçu doit être exactement celui publié
    sha_url = getattr(check, "sha_url", None)
    if sha_url:
        import hashlib
        want = requests.get(sha_url, timeout=15).text.split()[0].strip().lower()
        h = hashlib.sha256()
        with open(zpath, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != want:
            raise RuntimeError("fichier de mise à jour corrompu ou modifié (somme SHA-256 différente) — annulé")
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp / "new")
    new = tmp / "new"
    inner = [p for p in new.iterdir() if p.is_dir()]
    if len(inner) == 1 and (inner[0] / "Jarvis.exe").exists():
        new = inner[0]
    # sécurité : le .exe téléchargé doit pouvoir tourner sur CE processeur
    m = exe_machine(new / "Jarvis.exe")
    if m == "ARM64" and not native_arm64():
        raise RuntimeError("la mise à jour reçue est pour processeur ARM (Snapdragon), pas pour ce PC — annulée")
    # Le NOUVEAU Jarvis.exe (dans le dossier temporaire) fait lui-même le remplacement :
    # plus de script PowerShell (souvent bloqué par l'antivirus), et le dossier cible n'est pas verrouillé.
    flags = 0x00000008 | 0x00000200 | 0x08000000  # détaché, nouveau groupe, sans fenêtre
    args = [str(new / "Jarvis.exe"), "--apply-update", str(new), str(app_dir), str(os.getpid())]
    try:
        subprocess.Popen(args, creationflags=flags | 0x01000000, close_fds=True)  # + sortie du job parent
    except OSError:
        subprocess.Popen(args, creationflags=flags, close_fds=True)
    return True


LOG = Path(os.environ.get("APPDATA", tempfile.gettempdir())) / "Jarvis" / "update.log"


def _log(msg):
    import datetime
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def apply_update(src: str, dst: str, pid: str):
    """Exécuté par le nouveau Jarvis.exe : attend la fermeture de l'ancien, copie, relance."""
    import ctypes
    import shutil
    import time
    src, dst = Path(src), Path(dst)
    _log(f"application de la mise à jour {src} -> {dst}")
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
    if h:
        k32.WaitForSingleObject(h, 20000)
        k32.CloseHandle(h)
    subprocess.run(["taskkill", "/IM", "Jarvis.exe", "/F", "/FI", f"PID ne {os.getpid()}"],
                   capture_output=True, creationflags=0x08000000)
    time.sleep(1.5)
    # 1. le nouveau Jarvis se teste lui-même AVANT de remplacer quoi que ce soit
    t = subprocess.run([str(src / "Jarvis.exe"), "--selftest", "--offline"], capture_output=True, timeout=120)
    if t.returncode != 0:
        _log(f"auto-test de la nouvelle version ÉCHOUÉ (code {t.returncode}) : mise à jour annulée")
        subprocess.Popen([str(dst / "Jarvis.exe")], cwd=str(dst), creationflags=0x00000008, close_fds=True)
        return False
    # 2. sauvegarde de la version actuelle (retour arrière possible)
    backup = dst.parent / (dst.name + ".prev")
    try:
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        shutil.copytree(dst, backup)
    except Exception as e:
        _log(f"sauvegarde impossible : {e}")
        backup = None
    last = None
    for attempt in range(15):
        try:
            shutil.copytree(src, dst, dirs_exist_ok=True)
            _log("mise à jour installée")
            subprocess.Popen([str(dst / "Jarvis.exe")], cwd=str(dst), creationflags=0x00000008, close_fds=True)
            return True
        except Exception as e:
            last = e
            _log(f"essai {attempt + 1} : {e}")
            time.sleep(2)
    _log(f"ÉCHEC : {last}")
    if backup and backup.exists():  # 3. retour à la version précédente
        try:
            shutil.copytree(backup, dst, dirs_exist_ok=True)
            _log("version précédente restaurée")
            subprocess.Popen([str(dst / "Jarvis.exe")], cwd=str(dst), creationflags=0x00000008, close_fds=True)
        except Exception as e:
            _log(f"restauration impossible : {e}")
    import tkinter as tk
    from tkinter import messagebox
    r = tk.Tk(); r.withdraw()
    messagebox.showerror("J.A.R.V.I.S.", f"La mise à jour n'a pas pu remplacer les fichiers :\n{last}\n\n"
                         f"Dossier : {dst}\nJournal : {LOG}")
    return False


def rollback() -> bool:
    """Revient à la version précédente (menu « Revenir à la version précédente »)."""
    import shutil
    if not getattr(sys, "frozen", False):
        return False
    dst = Path(sys.executable).parent
    backup = dst.parent / (dst.name + ".prev")
    if not (backup / "Jarvis.exe").exists():
        return False
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_upd_"))
    shutil.copytree(backup, tmp / "Jarvis")
    args = [str(tmp / "Jarvis" / "Jarvis.exe"), "--apply-update", str(tmp / "Jarvis"), str(dst), str(os.getpid())]
    subprocess.Popen(args, creationflags=0x00000008 | 0x00000200 | 0x08000000, close_fds=True)
    return True


def uninstall():
    """Désinstallation : démarrage auto, raccourcis, réglages et programme."""
    import shutil
    appdata = Path(os.environ.get("APPDATA", ""))
    for lnk in (appdata / r"Microsoft\Windows\Start Menu\Programs\Startup\Jarvis.lnk",
                appdata / r"Microsoft\Windows\Start Menu\Programs\Jarvis.lnk",
                Path.home() / "Desktop" / "Jarvis.lnk"):
        try:
            lnk.unlink()
        except OSError:
            pass
    shutil.rmtree(appdata / "Jarvis", ignore_errors=True)
    if getattr(sys, "frozen", False):
        app = Path(sys.executable).parent
        bat = Path(tempfile.gettempdir()) / "jarvis_uninstall.bat"
        bat.write_text(f'@echo off\r\ntimeout /t 3 /nobreak >nul\r\nrmdir /s /q "{app}"\r\n'
                       f'rmdir /s /q "{app}.prev"\r\ndel "%~f0"\r\n', encoding="mbcs", errors="ignore")
        subprocess.Popen(["cmd", "/c", str(bat)], creationflags=0x08000000 | 0x00000008, close_fds=True)
