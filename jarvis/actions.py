"""Tout ce que Jarvis sait faire sur le PC. Chaque fonction renvoie un texte court
que le cerveau utilise pour formuler sa réponse."""
import ctypes
import datetime
import os
import subprocess
import time
import webbrowser
from pathlib import Path

from . import config

user32 = ctypes.windll.user32 if os.name == "nt" else None

# ---------- Touches média / volume ----------
VK = {
    "next": 0xB0, "previous": 0xB1, "stop": 0xB2, "play_pause": 0xB3,
    "mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF,
}


def _press(vk: int, times: int = 1):
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.03)


def media(action: str) -> str:
    if action not in ("next", "previous", "stop", "play_pause"):
        return "Action média inconnue."
    _press(VK[action])
    return {"next": "Piste suivante.", "previous": "Piste précédente.",
            "stop": "Lecture arrêtée.", "play_pause": "Lecture/pause basculée."}[action]


def volume(action: str, steps: int = 5) -> str:
    if action == "mute":
        _press(VK["mute"])
        return "Son coupé/rétabli."
    if action in ("up", "down"):
        _press(VK["volume_" + action], max(1, min(int(steps), 50)))
        return f"Volume {'augmenté' if action == 'up' else 'baissé'}."
    return "Action volume inconnue."


# ---------- Applications ----------
_APPS: dict[str, str] = {}


def scan_apps() -> dict:
    """Indexe les raccourcis du menu Démarrer, du Bureau et les jeux Steam."""
    roots = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
        Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
        Path.home() / "Desktop",
        Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
    ]
    apps = {}
    for root in roots:
        if root.exists():
            for p in root.rglob("*"):
                if p.suffix.lower() in (".lnk", ".url") and "uninstall" not in p.stem.lower() \
                        and "désinstaller" not in p.stem.lower():
                    apps.setdefault(p.stem.lower(), str(p))
    # Jeux Steam
    for steam in (Path(r"C:\Program Files (x86)\Steam\steamapps"), Path(r"C:\Program Files\Steam\steamapps")):
        if steam.exists():
            for acf in steam.glob("appmanifest_*.acf"):
                try:
                    txt = acf.read_text(encoding="utf-8", errors="ignore")
                    appid = acf.stem.split("_")[1]
                    name = txt.split('"name"')[1].split('"')[1]
                    apps.setdefault(name.lower(), f"steam://rungameid/{appid}")
                except Exception:
                    pass
    _APPS.clear()
    _APPS.update(apps)
    return apps


def _find_app(name: str):
    if not _APPS:
        scan_apps()
    n = name.lower().strip()
    if n in _APPS:
        return n, _APPS[n]
    words = [w for w in n.split() if len(w) > 1]
    cands = [k for k in _APPS if n in k] or ([k for k in _APPS if all(w in k for w in words)] if words else [])
    if cands:
        best = min(cands, key=len)
        return best, _APPS[best]
    return None, None


# Services web connus : ouverts directement, jamais confondus avec autre chose
WEB_APPS = {
    "youtube music": "https://music.youtube.com", "yt music": "https://music.youtube.com",
    "youtube musique": "https://music.youtube.com",
    "youtube": "https://www.youtube.com", "deezer": "https://www.deezer.com",
    "spotify web": "https://open.spotify.com", "netflix": "https://www.netflix.com",
    "prime video": "https://www.primevideo.com", "disney": "https://www.disneyplus.com",
    "twitch": "https://www.twitch.tv", "gmail": "https://mail.google.com",
    "google drive": "https://drive.google.com", "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai", "instagram": "https://www.instagram.com",
    "whatsapp web": "https://web.whatsapp.com", "github": "https://github.com",
    "soundcloud": "https://soundcloud.com", "canva": "https://www.canva.com",
}


def open_app(name: str) -> str:
    import webbrowser
    n = name.lower().strip().removesuffix(".").strip()
    if not _APPS:
        scan_apps()
    if n in _APPS:                       # 1. appli installée, nom exact
        os.startfile(_APPS[n]); return f"{n} lancé."
    import re
    m = re.search(r"^(.+?) (?:sur|avec|dans|via) (youtube music|yt music|youtube|spotify|deezer)$", n)
    if m:  # « PNL sur YouTube » demandé comme appli par l'IA : c'est de la musique
        svc = {"yt music": "youtube_music", "youtube music": "youtube_music"}.get(m.group(2), m.group(2))
        return play_music(m.group(1), svc)
    site = re.sub(r"^(le site |le |la |l')", "", n)
    if site in WEB_APPS:                 # 2. service web connu, nom EXACT uniquement
        webbrowser.open(WEB_APPS[site]); return f"{site.title()} ouvert."
    key, target = _find_app(n)           # 3. appli installée, nom approché
    if not target:
        return f"Application « {name} » introuvable."
    os.startfile(target)
    return f"{key} lancé."


def close_app(name: str) -> str:
    """Ferme un programme en cherchant son processus par nom approché."""
    want = name.lower().replace(" ", "").removesuffix(".exe")
    r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                       creationflags=0x08000000)
    procs = {line.split('","')[0].strip('"') for line in r.stdout.splitlines() if line}
    hits = [p for p in procs if want in p.lower().replace(" ", "")]
    if not hits:
        return f"Aucun programme « {name} » en cours."
    for p in hits:
        subprocess.run(["taskkill", "/IM", p, "/F"], capture_output=True, creationflags=0x08000000)
    return f"{name} fermé."


def list_apps(query: str = "") -> str:
    if not _APPS:
        scan_apps()
    names = sorted(k for k in _APPS if query.lower() in k)[:40]
    return ", ".join(names) or "Aucune application trouvée."


# ---------- Musique (sans API ni compte) ----------
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
      "Accept-Language": "fr-FR,fr;q=0.9"}


def _youtube_id(query: str):
    import re
    import urllib.parse
    import requests
    html = requests.get("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query),
                        headers=UA, timeout=8).text
    m = re.search(r'"videoId":"([\w-]{11})"', html)
    return m.group(1) if m else None


def _deezer_track(query: str):
    import requests
    r = requests.get("https://api.deezer.com/search", params={"q": query, "limit": 1}, timeout=8).json()
    d = r.get("data") or []
    return d[0]["id"] if d else None


def play_music(query: str, service: str = "youtube") -> str:
    """Lance un titre/artiste sur le service choisi, sans clé API ni compte Premium.
    youtube / youtube_music : lecture automatique de la 1re vidéo trouvée.
    deezer : ouvre directement le titre trouvé. spotify : ouvre la recherche puis lance la lecture."""
    import webbrowser
    service = (service or "youtube").lower()
    try:
        if service in ("youtube", "youtube_music"):
            vid = _youtube_id(query + (" audio" if service == "youtube_music" else ""))
            if not vid:
                return f"Rien trouvé pour « {query} »."
            host = "music.youtube.com" if service == "youtube_music" else "www.youtube.com"
            webbrowser.open(f"https://{host}/watch?v={vid}")
            return f"Je lance « {query} »."
        if service == "deezer":
            tid = _deezer_track(query)
            if not tid:
                return f"Rien trouvé pour « {query} » sur Deezer."
            try:
                os.startfile(f"deezer://www.deezer.com/track/{tid}")
            except OSError:
                webbrowser.open(f"https://www.deezer.com/track/{tid}")
            return f"« {query} » ouvert dans Deezer."
        # Spotify : recherche dans l'appli, puis Entrée sur le meilleur résultat
        os.startfile(f"spotify:search:{query}")
        time.sleep(3.0)
        for vk in (0x09, 0x0D):  # Tab puis Entrée (lecture du meilleur résultat)
            user32.keybd_event(vk, 0, 0, 0); user32.keybd_event(vk, 0, 2, 0); time.sleep(0.4)
        return f"Recherche « {query} » lancée dans Spotify."
    except Exception as e:
        return f"Impossible de lancer la musique : {e}"


def spotify_play(query: str) -> str:  # compatibilité
    return play_music(query, "spotify")


# ---------- Fichiers ----------
def _allowed(p: Path, cfg) -> bool:
    p = p.resolve()
    return any(str(p).lower().startswith(str(Path(f).resolve()).lower()) for f in cfg["allowed_folders"])


def find_files(query: str, cfg) -> str:
    q = query.lower()
    hits = []
    for folder in cfg["allowed_folders"]:
        root = Path(folder)
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if q in p.name.lower():
                hits.append(str(p))
                if len(hits) >= 15:
                    break
        if len(hits) >= 15:
            break
    return "\n".join(hits) or "Aucun fichier trouvé."


def open_path(path: str, cfg) -> str:
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    if not p.exists():
        return "Ce chemin n'existe pas."
    if not _allowed(p, cfg):
        return "Ce dossier n'est pas dans les dossiers autorisés."
    os.startfile(str(p))
    return f"{p.name} ouvert."


def open_folder(name: str) -> str:
    known = {"bureau": "Desktop", "documents": "Documents", "téléchargements": "Downloads",
             "telechargements": "Downloads", "musique": "Music", "images": "Pictures", "vidéos": "Videos",
             "videos": "Videos"}
    sub = known.get(name.lower(), name)
    p = Path.home() / sub
    if p.exists():
        os.startfile(str(p))
        return f"Dossier {name} ouvert."
    return f"Dossier {name} introuvable."


def organize_downloads(cfg) -> str:
    dl = Path.home() / "Downloads"
    groups = {"Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"},
              "Documents": {".pdf", ".docx", ".doc", ".xlsx", ".pptx", ".txt", ".csv"},
              "Musique": {".mp3", ".wav", ".flac", ".m4a"}, "Vidéos": {".mp4", ".mkv", ".mov", ".avi"},
              "Archives": {".zip", ".rar", ".7z"}, "Installateurs": {".exe", ".msi"}}
    moved = 0
    for f in dl.iterdir():
        if f.is_file():
            for g, exts in groups.items():
                if f.suffix.lower() in exts:
                    (dl / g).mkdir(exist_ok=True)
                    dest = dl / g / f.name
                    if not dest.exists():
                        f.rename(dest)
                        moved += 1
                    break
    return f"{moved} fichiers rangés dans Téléchargements."


# ---------- Système ----------
def system(action: str) -> str:
    if action == "lock":
        user32.LockWorkStation()
        return "Session verrouillée."
    if action == "screenshot":
        _press(0x2C)  # Impr écran -> presse-papiers / OneDrive selon réglages
        subprocess.Popen(["explorer", "ms-screenclip:"])
        return "Outil de capture ouvert."
    if action == "shutdown":
        subprocess.run(["shutdown", "/s", "/t", "30"], creationflags=0x08000000)
        return "Arrêt dans 30 secondes. Dites « annule l'arrêt » pour annuler."
    if action == "restart":
        subprocess.run(["shutdown", "/r", "/t", "30"], creationflags=0x08000000)
        return "Redémarrage dans 30 secondes."
    if action == "cancel_shutdown":
        subprocess.run(["shutdown", "/a"], creationflags=0x08000000)
        return "Arrêt annulé."
    if action == "sleep":
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return "Mise en veille."
    return "Action système inconnue."


def now() -> str:
    d = datetime.datetime.now()
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    return f"Nous sommes {jours[d.weekday()]} {d:%d/%m/%Y}, il est {d:%H:%M}."


def web_search(query: str) -> str:
    webbrowser.open(f"https://www.google.com/search?q={query}")
    return f"Recherche « {query} » ouverte."


def open_website(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return f"{url} ouvert."


def type_text(text: str) -> str:
    """Tape du texte dans la fenêtre active (presse-papiers + Ctrl+V)."""
    subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
                   input=text, text=True, creationflags=0x08000000)
    time.sleep(0.15)
    user32.keybd_event(0x11, 0, 0, 0); user32.keybd_event(0x56, 0, 0, 0)
    user32.keybd_event(0x56, 0, 2, 0); user32.keybd_event(0x11, 0, 2, 0)
    return "Texte tapé."


_timers = []


def set_timer(seconds: int, label: str, speak) -> str:
    import threading
    t = threading.Timer(int(seconds), lambda: speak(f"Minuteur terminé : {label}."))
    t.daemon = True
    t.start()
    _timers.append(t)
    m, s = divmod(int(seconds), 60)
    return f"Minuteur de {m} min {s} s lancé."


# Actions qui demandent une confirmation vocale
SENSITIVE = {("system", "shutdown"), ("system", "restart"), ("organize_downloads", None)}
