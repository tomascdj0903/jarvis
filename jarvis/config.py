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


def known_folder(name: str) -> str:
    """Vrai chemin des dossiers Windows (gère OneDrive qui déplace Bureau/Documents/Images)."""
    guids = {"Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
             "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}", "Music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
             "Pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}", "Videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}"}
    if os.name == "nt" and name in guids:
        try:
            import ctypes
            import uuid
            from ctypes import wintypes
            g = uuid.UUID(guids[name])
            guid = (ctypes.c_byte * 16).from_buffer_copy(g.bytes_le)
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(p)) == 0:
                path = p.value
                ctypes.windll.ole32.CoTaskMemFree(p)
                return path
        except Exception:
            pass
    return str(Path.home() / name)


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
    "allowed_folders": [known_folder(n) for n in ("Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos")],
    "gemini_api_key": "",
    "openrouter_api_key": "",
    "conversation_mode": True,
    "duck_music": True,
    "morning_briefing": True,
    "planning_url": "https://planning-partage-xi.vercel.app",
    "planning_key": "",
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


SECRETS = ("groq_api_key", "gemini_api_key", "openrouter_api_key", "planning_key")


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
    for n in ("Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos"):
        real = known_folder(n)
        if real not in cfg["allowed_folders"]:
            cfg["allowed_folders"].append(real)
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
