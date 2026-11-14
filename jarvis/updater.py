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
    bat = tmp / "update.bat"
    bat.write_text(
        "@echo off\r\n"
        f"taskkill /PID {os.getpid()} /F >nul 2>nul\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f'robocopy "{new}" "{app_dir}" /E /IS /IT /NFL /NDL /NJH /NJS >nul\r\n'
        f'start "" "{app_dir / "Jarvis.exe"}"\r\n',
        encoding="ascii", errors="ignore")
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=0x08000000 | 0x00000008)
    return True
