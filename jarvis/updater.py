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
    log = Path(os.environ.get("APPDATA", tempfile.gettempdir())) / "Jarvis" / "update.log"
    ps1 = tmp / "update.ps1"
    # PowerShell en UTF-8 avec BOM : gère les chemins avec accents
    ps1.write_text(f"""
$ErrorActionPreference = 'Continue'
$log = '{log}'
function L($m) {{ Add-Content -LiteralPath $log -Value ("$(Get-Date -f s) " + $m) }}
L 'Mise a jour : attente de la fermeture de Jarvis (PID {os.getpid()})'
try {{ Wait-Process -Id {os.getpid()} -Timeout 20 -ErrorAction SilentlyContinue }} catch {{}}
Get-Process -Name Jarvis -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$src = '{new}'; $dst = '{app_dir}'
$ok = $false
for ($i = 1; $i -le 10 -and -not $ok; $i++) {{
    robocopy $src $dst /E /IS /IT /R:2 /W:1 /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -lt 8) {{ $ok = $true }} else {{ L "Copie echouee (code $LASTEXITCODE), essai $i"; Start-Sleep -Seconds 2 }}
}}
if ($ok) {{ L 'Mise a jour installee.' }} else {{ L 'ECHEC de la mise a jour.' }}
Start-Process -FilePath (Join-Path $dst 'Jarvis.exe')
""", encoding="utf-8-sig")
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                      "-File", str(ps1)], creationflags=0x08000000 | 0x00000008 | 0x00000200,
                     close_fds=True)
    return True
