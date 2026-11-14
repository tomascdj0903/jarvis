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
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    if cfg.get("wake_threshold") == 0.5:  # migration v1.0 -> plus sensible
        cfg["wake_threshold"] = 0.35
    return cfg


def save(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
