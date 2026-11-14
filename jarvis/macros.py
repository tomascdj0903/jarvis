"""Macros vocales : des commandes perso en plusieurs étapes, sans coder.
Fichier %APPDATA%\\Jarvis\\macros.json, par exemple :
{
  "mode jeu":   ["open:discord", "open:steam", "volume:60"],
  "mode cours": ["open:teams", "open:notion", "volume:20"],
  "bonne nuit": ["pause", "brightness:10", "lock"]
}
Étapes : open:<appli>, music:<recherche>, volume:<0-100>, brightness:<0-100>, url:<adresse>, pause, play, lock, say:<texte>
"""
import json
import time

from . import actions, config

FILE = config.APP_DIR / "macros.json"
EXAMPLE = {"mode jeu": ["open:discord", "open:steam", "volume:60"],
           "bonne nuit": ["pause", "brightness:10", "say:Bonne nuit."]}


def load() -> dict:
    if not FILE.exists():
        try:
            FILE.write_text(json.dumps(EXAMPLE, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    try:
        return {k.lower().strip(): v for k, v in json.loads(FILE.read_text(encoding="utf-8")).items()}
    except Exception:
        return {}


def run(steps) -> str:
    said = []
    for st in steps:
        kind, _, arg = str(st).partition(":")
        kind, arg = kind.strip().lower(), arg.strip()
        try:
            if kind == "open":
                actions.open_app(arg)
            elif kind == "music":
                actions.play_music(arg, config.load().get("music_service", "youtube"))
            elif kind == "volume":
                actions.set_volume(int(arg))
            elif kind == "brightness":
                actions.set_brightness(int(arg))
            elif kind == "url":
                actions.open_url(arg if arg.startswith("http") else "https://" + arg)
            elif kind == "pause":
                actions.pause_music()
            elif kind == "play":
                actions.resume()
            elif kind == "lock":
                actions.system("lock")
            elif kind == "say":
                said.append(arg)
            time.sleep(0.4)
        except Exception:
            pass
    return " ".join(said) or "C'est parti."


def match(t: str):
    """t = phrase nettoyée. Renvoie les étapes si elle correspond à une macro."""
    import re
    m = load()
    t2 = re.sub(r"^(lance|active|mets|passe en|passe|demarre|go)( le| la| en)? ", "", t).strip()
    for name, steps in m.items():
        from .router import _norm
        n = _norm(name)
        if t == n or t2 == n:
            return steps
    return None
