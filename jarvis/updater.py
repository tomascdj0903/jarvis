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
        for a in d.get("assets", []):
            if a["name"].lower().endswith(".zip"):
                return tag, a["browser_download_url"], (d.get("body") or "")[:400]
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
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp / "new")
    new = tmp / "new"
    inner = [p for p in new.iterdir() if p.is_dir()]
    if len(inner) == 1 and (inner[0] / "Jarvis.exe").exists():
        new = inner[0]
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
    import tkinter as tk
    from tkinter import messagebox
    r = tk.Tk(); r.withdraw()
    messagebox.showerror("J.A.R.V.I.S.", f"La mise à jour n'a pas pu remplacer les fichiers :\n{last}\n\n"
                         f"Dossier : {dst}\nJournal : {LOG}")
    return False
