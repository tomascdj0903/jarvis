"""Configuration de Jarvis : stockée dans %APPDATA%\\Jarvis\\config.json."""
import json
import os
import sys
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "Jarvis"
APP_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "jarvis.log"


def resource(rel: str) -> Path:
    """Chemin d'une ressource, en dev comme dans le .exe PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


DEFAULTS = {
    "groq_api_key": "",
    "llm_model": "llama-3.3-70b-versatile",
    "stt_model": "whisper-large-v3-turbo",
    "voice": "fr-FR-HenriNeural",
    "language": "fr",
    "user_name": "Monsieur",
    "wake_threshold": 0.35,
    "show_idle_orb": True,
    "input_device": None,
    "music_service": "youtube",
    "home_city": "",
    "hotkey": "ctrl+alt+j",
    "allowed_folders": [
        str(Path.home() / "Desktop"),
        str(Path.home() / "Documents"),
        str(Path.home() / "Downloads"),
        str(Path.home() / "Music"),
        str(Path.home() / "Pictures"),
        str(Path.home() / "Videos"),
    ],
    "show_hud": True,
    "log_utterances": False,
    "pause_when_locked": True,
}


# ---------- chiffrement de la clé (DPAPI Windows : lisible seulement par ce compte sur ce PC) ----------
def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    inp, out = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    ok = (fn(ctypes.byref(inp), "Jarvis" if encrypt else None, None, None, None, 0, ctypes.byref(out)) if encrypt
          else fn(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)))
    if not ok:
        raise OSError("DPAPI")
    res = ctypes.string_at(out.pbData, out.cbData)
    ctypes.windll.kernel32.LocalFree(out.pbData)
    return res


SECRETS = ("groq_api_key",)


def _protect(v: str) -> str:
    import base64
    return "dpapi:" + base64.b64encode(_dpapi(v.encode(), True)).decode()


def _unprotect(v: str) -> str:
    import base64
    if not v.startswith("dpapi:"):
        return v
    return _dpapi(base64.b64decode(v[6:]), False).decode()


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    if cfg.get("wake_threshold") == 0.5:  # migration v1.0 -> plus sensible
        cfg["wake_threshold"] = 0.35
    plain_on_disk = False
    for k in SECRETS:
        v = cfg.get(k) or ""
        if v and not v.startswith("dpapi:"):
            plain_on_disk = True
        try:
            cfg[k] = _unprotect(v)
        except Exception:
            cfg[k] = ""  # clé d'un autre compte/PC : illisible, on la redemandera
    if plain_on_disk and os.name == "nt":
        save(cfg)  # migration : la clé en clair est chiffrée tout de suite
    return cfg


def save(cfg: dict) -> None:
    data = dict(cfg)
    if os.name == "nt":
        for k in SECRETS:
            if data.get(k):
                data[k] = _protect(data[k])
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
