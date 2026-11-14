"""Fonctions d'assistant personnel : rappels et minuteurs persistants, notes vocales,
briefing du matin, batterie, réseau. Tout est stocké localement dans %APPDATA%\\Jarvis."""
import datetime as dt
import json
import re
import subprocess
import threading
import uuid

from . import config

REM_FILE = config.APP_DIR / "rappels.json"
_lock = threading.Lock()
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
NUM = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
       "neuf": 9, "dix": 10, "quinze": 15, "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50}


# ---------------------------------------------------------------- rappels / minuteurs
def _load():
    try:
        return json.loads(REM_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items):
    REM_FILE.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")


def parse_when(t: str, now=None):
    """« dans 10 minutes », « dans 2 h », « à 18h30 », « demain à 9h », « lundi à 14h » -> datetime."""
    now = now or dt.datetime.now()
    t = t.lower()
    for w, n in NUM.items():
        t = re.sub(rf"\b{w}\b", str(n), t)
    m = re.search(r"dans (\d+)\s*(secondes?|s|minutes?|min|mn|heures?|h)\b(?:\s*(\d+))?", t)
    if m:
        n, u = int(m.group(1)), m.group(2)
        if u.startswith("s"):
            return now + dt.timedelta(seconds=n)
        if u.startswith("h"):
            return now + dt.timedelta(hours=n, minutes=int(m.group(3) or 0))
        return now + dt.timedelta(minutes=n)
    if re.search(r"dans une? demi[- ]heure", t):
        return now + dt.timedelta(minutes=30)
    m = re.search(r"\b(?:a|à|vers)\s*(\d{1,2})\s*(?:h|heures?|:)\s*(\d{2})?", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        day = now.date()
        if "apres-demain" in t or "après-demain" in t:
            day += dt.timedelta(days=2)
        elif "demain" in t:
            day += dt.timedelta(days=1)
        else:
            for i, j in enumerate(JOURS):
                if re.search(rf"\b{j}\b", t):
                    day += dt.timedelta(days=(i - now.weekday()) % 7 or 7)
        when = dt.datetime.combine(day, dt.time(h % 24, mi))
        if when <= now:
            when += dt.timedelta(days=1)
        return when
    return None


def _say_when(when: dt.datetime) -> str:
    now = dt.datetime.now()
    delta = when - now
    if delta.total_seconds() < 3600:
        m = max(1, round(delta.total_seconds() / 60))
        return f"dans {m} minute{'s' if m > 1 else ''}"
    jour = "aujourd'hui" if when.date() == now.date() else (
        "demain" if when.date() == now.date() + dt.timedelta(days=1) else JOURS[when.weekday()])
    return f"{jour} à {when:%H:%M}".replace(":00", " heures").replace(":", " h ")


def add_reminder(text: str, when: dt.datetime) -> str:
    with _lock:
        items = _load()
        items.append({"id": uuid.uuid4().hex[:8], "when": when.isoformat(timespec="seconds"), "text": text.strip()})
        _save(items)
    return f"C'est noté, je vous le rappelle {_say_when(when)}."


def list_reminders() -> str:
    items = sorted(_load(), key=lambda x: x["when"])
    if not items:
        return "Vous n'avez aucun rappel."
    parts = [f"{_say_when(dt.datetime.fromisoformat(i['when']))} : {i['text']}" for i in items[:5]]
    return "Vos rappels : " + " ; ".join(parts) + "."


def clear_reminders() -> str:
    with _lock:
        _save([])
    return "Tous vos rappels sont supprimés."


def due():
    """Rappels arrivés à échéance (retirés de la liste). Rattrape aussi ceux manqués PC éteint."""
    now = dt.datetime.now()
    with _lock:
        items = _load()
        hit = [i for i in items if dt.datetime.fromisoformat(i["when"]) <= now]
        if hit:
            _save([i for i in items if i not in hit])
    return hit


def start_scheduler(say, notify):
    def run():
        import time
        while True:
            try:
                for r in due():
                    late = (dt.datetime.now() - dt.datetime.fromisoformat(r["when"])).total_seconds() > 300
                    msg = f"Rappel{' (en retard)' if late else ''} : {r['text']}"
                    notify(msg, 20)
                    say(msg)
            except Exception:
                pass
            time.sleep(10)
    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- notes vocales
def notes_file():
    p = config.known_folder("Documents")
    from pathlib import Path
    f = Path(p) / "Notes Jarvis.md"
    return f


def add_note(text: str) -> str:
    f = notes_file()
    if not f.exists():
        f.write_text("# Notes Jarvis\n\n", encoding="utf-8")
    with open(f, "a", encoding="utf-8") as h:
        h.write(f"- {dt.datetime.now():%d/%m/%Y %H:%M} — {text.strip()}\n")
    return "Note enregistrée."


def read_notes(n=3) -> str:
    f = notes_file()
    if not f.exists():
        return "Vous n'avez aucune note."
    lines = [l[2:] for l in f.read_text(encoding="utf-8").splitlines() if l.startswith("- ")]
    if not lines:
        return "Vous n'avez aucune note."
    return "Vos dernières notes : " + " ; ".join(l.split("— ", 1)[-1] for l in lines[-n:]) + "."


# ---------------------------------------------------------------- système
def battery() -> str:
    import ctypes

    class SPS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
    s = SPS()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s))
    pct = s.BatteryLifePercent & 0xFF
    if pct == 255:
        return "Je ne trouve pas de batterie sur cet ordinateur."
    txt = f"Batterie à {pct} %"
    if s.ACLineStatus == 1:
        txt += ", en charge"
    elif s.BatteryLifeTime not in (0xFFFFFFFF, -1) and s.BatteryLifeTime > 0:
        h, m = divmod(s.BatteryLifeTime // 60, 60)
        txt += f", environ {h} h {m:02d} restantes"
    return txt + "."


SETTINGS_PAGES = {"wifi": "ms-settings:network-wifi", "bluetooth": "ms-settings:bluetooth",
                  "mode avion": "ms-settings:network-airplanemode", "batterie": "ms-settings:batterysaver",
                  "economie d'energie": "ms-settings:batterysaver", "son": "ms-settings:sound",
                  "affichage": "ms-settings:display", "mise a jour": "ms-settings:windowsupdate",
                  "notifications": "ms-settings:notifications", "ne pas deranger": "ms-settings:notifications"}


def wifi(on: bool) -> str:
    if not on:
        r = subprocess.run(["netsh", "wlan", "disconnect"], capture_output=True, text=True, creationflags=0x08000000)
        return "Wi-Fi déconnecté." if r.returncode == 0 else "Je n'ai pas pu couper le Wi-Fi."
    import os
    os.startfile("ms-settings:network-wifi")
    return "J'ouvre les réglages Wi-Fi pour vous reconnecter."


def open_settings_page(name: str) -> str:
    import os
    for k, uri in SETTINGS_PAGES.items():
        if k in name:
            os.startfile(uri)
            return f"Réglages {k} ouverts."
    os.startfile("ms-settings:")
    return "Paramètres Windows ouverts."


# ---------------------------------------------------------------- Planning partagé (web app Vercel)
def planning_devoirs(cfg=None) -> str:
    """Rappel des devoirs du jour, via la même adresse que le raccourci iPhone (/api/rappels-devoirs)."""
    import requests
    cfg = cfg or config.load()
    key = (cfg.get("planning_key") or "").strip()
    base = (cfg.get("planning_url") or "").rstrip("/")
    if not key or not base:
        return "Planning partagé n'est pas encore relié : ajoutez sa clé dans les Réglages."
    try:
        r = requests.get(f"{base}/api/rappels-devoirs", params={"cle": key}, timeout=20)
    except Exception:
        return "Je n'arrive pas à joindre Planning partagé."
    if r.status_code == 401:
        return "La clé de Planning partagé est refusée. Vérifiez-la dans les Réglages."
    if not r.ok:
        return f"Planning partagé ne répond pas correctement ({r.status_code})."
    txt = r.text.strip()
    if not txt:
        return "Rien à rappeler aujourd'hui dans Planning partagé."
    txt = re.sub(r"https?://\S+", "", txt)  # pas de lien lu à voix haute
    return " ".join(txt.split())


# ---------------------------------------------------------------- briefing
def briefing(user_name: str = "") -> str:
    now = dt.datetime.now()
    h = now.hour
    hello = "Bonjour" if h < 18 else "Bonsoir"
    parts = [f"{hello}{' ' + user_name if user_name else ''}. Nous sommes {JOURS[now.weekday()]} {now:%d/%m}, "
             f"il est {now:%H:%M}."]
    try:
        from .weather import weather
        parts.append(weather("", "aujourd'hui"))
    except Exception:
        pass
    today = [i for i in _load() if dt.datetime.fromisoformat(i["when"]).date() == now.date()]
    if today:
        parts.append(f"Vous avez {len(today)} rappel{'s' if len(today) > 1 else ''} aujourd'hui : "
                     + ", ".join(f"{i['text']} à {dt.datetime.fromisoformat(i['when']):%H:%M}" for i in today[:3]) + ".")
    if config.load().get("planning_key"):
        d = planning_devoirs()
        if not d.startswith(("Rien", "Je n'arrive", "La clé", "Planning partagé ne")):
            parts.append(d)
    try:
        b = battery()
        if "charge" not in b and any(f"à {x} %" in b for x in range(0, 31)):
            parts.append(b)
    except Exception:
        pass
    return " ".join(parts)
