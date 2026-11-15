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

# ---------- Premier plan ----------
BROWSERS = ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe")


def _windows():
    """[(hwnd, exe, titre)] des fenêtres visibles."""
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    res = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            h = k32.OpenProcess(0x1000, False, pid.value)
            exe = ""
            if h:
                buf = ctypes.create_unicode_buffer(512); n = wintypes.DWORD(512)
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    exe = buf.value.rsplit("\\", 1)[-1].lower()
                k32.CloseHandle(h)
            t = ctypes.create_unicode_buffer(512); user32.GetWindowTextW(hwnd, t, 512)
            res.append((hwnd, exe, t.value))
        return True
    user32.EnumWindows(cb, 0)
    return res  # ordre Z : la plus récemment active en premier


def _force_front(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # astuce Alt : Windows autorise alors le changement de premier plan
    user32.keybd_event(0x12, 0, 0, 0); user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)


def bring_to_front(exes=BROWSERS, title_hint="", delay=1.2, tries=6):
    """Met au premier plan la fenêtre qui vient d'être ouverte (navigateur ou appli)."""
    import threading

    def run():
        time.sleep(delay)
        for _ in range(tries):
            try:
                wins = [w for w in _windows() if (not exes or w[1] in exes)
                        and (not title_hint or title_hint.lower() in w[2].lower())]
                if wins:
                    _force_front(wins[0][0])
                    if user32.GetForegroundWindow() == wins[0][0]:
                        return
            except Exception:
                return
            time.sleep(0.6)
    threading.Thread(target=run, daemon=True).start()


def open_url(url: str):
    import webbrowser
    webbrowser.open(url)
    bring_to_front()


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


def set_volume(percent: int) -> str:
    """Volume exact : 50 crans vers le bas (0 %), puis remontée (1 cran = 2 %)."""
    p = max(0, min(100, int(percent)))
    _press(VK["volume_down"], 50)
    _press(VK["volume_up"], round(p / 2))
    return f"Volume réglé à {p} %."


def set_brightness(percent: int) -> str:
    """Luminosité de l'écran intégré (portable) via WMI. Les écrans externes ne sont pas pilotables ainsi."""
    p = max(0, min(100, int(percent)))
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                        f".WmiSetBrightness(1,{p})"], capture_output=True, text=True, creationflags=0x08000000)
    if r.returncode != 0 or "Exception" in (r.stderr or ""):
        return "Impossible de régler la luminosité de cet écran."
    return f"Luminosité réglée à {p} %."


# ---------- Applications ----------
_APPS: dict[str, str] = {}
_ALTS: dict[str, list] = {}   # nom -> toutes les cibles trouvées (raccourci, appli Store…), essayées dans l'ordre


def scan_apps() -> dict:
    """Indexe les raccourcis du menu Démarrer, du Bureau et les jeux Steam."""
    roots = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
        Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
        Path.home() / "Desktop",
        Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
    ]
    apps, alts = {}, {}
    for root in roots:
        if root.exists():
            for p in root.rglob("*"):
                if p.suffix.lower() in (".lnk", ".url") and "uninstall" not in p.stem.lower() \
                        and "désinstaller" not in p.stem.lower():
                    apps.setdefault(p.stem.lower(), str(p))
                    alts.setdefault(p.stem.lower(), []).append(str(p))
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
    # Jeux Epic Games
    man = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Epic\EpicGamesLauncher\Data\Manifests"
    if man.exists():
        import json
        for item in man.glob("*.item"):
            try:
                d = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
                if d.get("DisplayName") and d.get("AppName"):
                    apps.setdefault(d["DisplayName"].lower(),
                                    f"com.epicgames.launcher://apps/{d['AppName']}?action=launch&silent=true")
            except Exception:
                pass
    # Applis du Microsoft Store / Xbox (WhatsApp, Netflix, Minecraft…)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-StartApps | ForEach-Object { $_.Name + '|' + $_.AppID }"],
                           capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        for line in r.stdout.splitlines():
            if "|" in line and "!" in line:  # AppID des applis Store
                nm, aid = line.rsplit("|", 1)
                k, tgt = nm.strip().lower(), f"shell:AppsFolder\\{aid.strip()}"
                apps[k] = tgt                         # l'appli Store enregistrée passe avant un vieux raccourci
                alts.setdefault(k, []).insert(0, tgt)
    except Exception:
        pass
    _APPS.clear()
    _APPS.update(apps)
    _ALTS.clear()
    _ALTS.update(alts)
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


def _sim(a: str, b: str) -> float:
    """Proportion des mots de « a » présents dans « b » (accents et ponctuation ignorés)."""
    wa = [w for w in _norm_txt(a).split() if len(w) > 1]
    wb = set(_norm_txt(b).split())
    if not wa:
        return 0.0
    hit = sum(1 for w in wa if w in wb or any(x.startswith(w[:5]) for x in wb if len(w) >= 5))
    return hit / len(wa)


def switch_window(name: str):
    """Passe sur une fenêtre déjà ouverte (barre des tâches) dont le titre correspond. None si aucune."""
    best, score = None, 0.0
    for hwnd, exe, title in _windows():
        if exe in ("jarvis.exe",) or not title:
            continue
        sc = _sim(name, title)
        if sc > score:
            best, score = (hwnd, title), sc
    if best and score >= 0.99:
        _force_front(best[0])
        return f"Fenêtre « {best[1][:60]} » affichée."
    return None


def _bookmarks():
    """[(nom, url)] des favoris Chrome, Edge et Brave (tous profils)."""
    import json
    out = []
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    for base in ("Google/Chrome", "Microsoft/Edge", "BraveSoftware/Brave-Browser"):
        for f in (local / base / "User Data").glob("*/Bookmarks"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            stack = list(data.get("roots", {}).values())
            while stack:
                n = stack.pop()
                if isinstance(n, dict):
                    if n.get("type") == "url":
                        out.append((n.get("name", ""), n.get("url", "")))
                    stack.extend(n.get("children", []))
    return out


def open_bookmark(name: str):
    best, score = None, 0.0
    for title, url in _bookmarks():
        sc = _sim(name, title)
        if sc > score:
            best, score = (title, url), sc
    if best and score >= 0.99 and best[1].startswith(("http://", "https://")):
        open_url(best[1])
        return f"Favori « {best[0][:60]} » ouvert."
    return None


# Services web connus : ouverts directement, jamais confondus avec autre chose
WEB_APPS = {
    "youtube music": "https://music.youtube.com", "yt music": "https://music.youtube.com",
    "youtube musique": "https://music.youtube.com",
    "youtube": "https://www.youtube.com", "deezer": "https://www.deezer.com",
    "google": "https://www.google.com", "google images": "https://images.google.com", "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com", "wikipedia": "https://fr.wikipedia.org",
    "spotify web": "https://open.spotify.com", "netflix": "https://www.netflix.com",
    "prime video": "https://www.primevideo.com", "disney": "https://www.disneyplus.com",
    "twitch": "https://www.twitch.tv", "gmail": "https://mail.google.com",
    "google drive": "https://drive.google.com", "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai", "instagram": "https://www.instagram.com",
    "whatsapp web": "https://web.whatsapp.com", "github": "https://github.com",
    "soundcloud": "https://soundcloud.com", "canva": "https://www.canva.com",
    "planning partage": "https://planning-partage-xi.vercel.app", "planning partagé": "https://planning-partage-xi.vercel.app",
}


def _launch(target: str):
    if str(target).startswith("shell:"):
        subprocess.Popen(["explorer.exe", target])
    else:
        os.startfile(target)


def _launch_app(key: str, target: str):
    """Lance l'appli ; si la cible est cassée (raccourci d'une ancienne version), essaie les autres."""
    last = None
    for t in [target] + [x for x in _ALTS.get(key, []) if x != target]:
        try:
            _launch(t)
            return
        except OSError as e:
            last = e
    raise last


def open_app(name: str) -> str:
    import webbrowser
    n = name.lower().strip().removesuffix(".").strip()
    if n.count(",") >= 2:
        return "Donnez-moi une seule application à ouvrir."
    if not _APPS:
        scan_apps()
    if n in _APPS:                       # 1. appli installée, nom exact
        try:
            _launch_app(n, _APPS[n])
        except OSError:
            return f"Impossible de lancer {n} : son raccourci semble cassé, réinstallez l'application."
        bring_to_front(exes=(), title_hint=n.split()[0], delay=2.0, tries=10)
        return f"{n} lancé."
    import re
    m = re.search(r"^(.+?) (?:sur|avec|dans|via) (youtube music|yt music|youtube|spotify|deezer)$", n)
    if m:  # « PNL sur YouTube » demandé comme appli par l'IA : c'est de la musique
        svc = {"yt music": "youtube_music", "youtube music": "youtube_music"}.get(m.group(2), m.group(2))
        return play_music(m.group(1), svc)
    site = re.sub(r"^(le site |le |la |l')", "", n)
    if site in WEB_APPS:                 # 2. service web connu, nom EXACT uniquement
        open_url(WEB_APPS[site]); return f"{site.title()} ouvert."
    key, target = _find_app(n)           # 3. appli installée, nom approché
    if not target:
        # 4. fenêtre déjà ouverte (onglet actif, document…), 5. favori du navigateur
        return switch_window(n) or open_bookmark(n) or f"Application « {name} » introuvable."
    try:
        _launch_app(key, target)
    except OSError:
        return f"Impossible de lancer {key} : son raccourci semble cassé, réinstallez l'application."
    if not str(target).startswith(("steam://", "com.epicgames")):
        bring_to_front(exes=(), title_hint=key.split()[0], delay=2.0, tries=10)
    return f"{key} lancé."


PROTECTED = {"explorer.exe", "svchost.exe", "csrss.exe", "winlogon.exe", "lsass.exe", "services.exe", "dwm.exe",
             "system", "registry", "smss.exe", "wininit.exe", "jarvis.exe", "python.exe", "pythonw.exe",
             "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe", "ctfmon.exe",
             "runtimebroker.exe", "sihost.exe", "taskhostw.exe", "fontdrvhost.exe", "conhost.exe", "msmpeng.exe"}


def _procs():
    r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, creationflags=0x08000000)
    return {line.split('","')[0].strip('"').lower() for line in r.stdout.splitlines() if line}


def close_app(name: str) -> str:
    """Ferme UN programme : nom d'exe exact (ou exact sans espaces), jamais un processus système.
    Fermeture douce d'abord (comme la croix), forcée seulement si le programme ne répond pas."""
    want = name.lower().strip().removesuffix(".exe")
    if len(want) < 3:
        return "Nom de programme trop court, précisez lequel fermer."
    procs = _procs()
    cands = [p for p in procs if p.removesuffix(".exe") in (want, want.replace(" ", ""))]
    if not cands:  # nom de fenêtre (ex. « word » -> winword.exe)
        wins = [w for w in _windows() if want in w[2].lower() and w[1]]
        cands = sorted({w[1] for w in wins})
    cands = [c for c in cands if c not in PROTECTED]
    if not cands:
        return f"Aucun programme « {name} » ouvert (ou programme protégé)."
    if len(cands) > 1:
        return f"Plusieurs programmes correspondent ({', '.join(cands[:4])}) : lequel dois-je fermer ?"
    exe = cands[0]
    subprocess.run(["taskkill", "/IM", exe], capture_output=True, creationflags=0x08000000)  # douce
    time.sleep(2.5)
    if exe in _procs():
        subprocess.run(["taskkill", "/IM", exe, "/F"], capture_output=True, creationflags=0x08000000)
    return f"{exe.removesuffix('.exe')} fermé."


def list_apps(query: str = "") -> str:
    if not _APPS:
        scan_apps()
    q = query.lower().strip()
    if q in ("jeu", "jeux", "game", "games", "steam", "epic"):
        names = [k for k, _ in games("" if q in ("jeu", "jeux", "game", "games") else q)]
    else:
        names = sorted(k for k in _APPS if q in k)
    total = len(names)
    names = names[:25]
    return (", ".join(names) + (f" (et {total - 25} autres)" if total > 25 else "")) or "Aucune application trouvée."


NOT_GAMES = ("redistributable", "steamworks", "soundtrack", "dedicated server", "sdk", "benchmark", "editor",
             "wallpaper engine", "proton", "steam linux runtime", "tool", "demo", "server")


def games(store: str = "") -> list:
    """Jeux installés (Steam, Epic) : [(nom, cible)]."""
    if not _APPS:
        scan_apps()
    pref = {"steam": ("steam://",), "epic": ("com.epicgames",)}.get(store, ("steam://", "com.epicgames"))
    return sorted((k, v) for k, v in _APPS.items()
                  if str(v).startswith(pref) and not any(x in k for x in NOT_GAMES))


def random_game(store: str = "") -> str:
    import random
    g = games(store)
    if not g:
        return "Je ne trouve aucun jeu installé" + (f" sur {store.title()}." if store else ".")
    name, target = random.choice(g)
    _launch(target)
    return f"Au hasard : je lance {name}."


# ---------- Musique (sans API ni compte) ----------
YT_COOKIES = {"SOCS": "CAI", "CONSENT": "YES+"}  # évite la page de consentement européenne de YouTube
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
      "Accept-Language": "fr-FR,fr;q=0.9"}


def _norm_txt(t):
    import re, unicodedata
    t = unicodedata.normalize("NFD", t.lower())
    return re.sub(r"[^a-z0-9 ]", " ", "".join(c for c in t if unicodedata.category(c) != "Mn"))


def correct_query(query: str) -> str:
    """Corrige l'orthographe comme la barre de recherche YouTube (« nahar pnl » -> « naha pnl »)."""
    import requests
    try:
        r = requests.get("https://suggestqueries.google.com/complete/search", timeout=5, headers=UA, cookies=YT_COOKIES,
                         params={"client": "firefox", "ds": "yt", "hl": "fr", "q": query}).json()
        sug = r[1] if len(r) > 1 else []
        n = len(query.split())
        for cand in sug:
            words = cand.split()[:n]  # même nombre de mots : on corrige, on n'ajoute rien (« slowed », « lyrics »…)
            if len(words) == n:
                return " ".join(words)
    except Exception:
        pass
    return query


def _youtube_id(query: str):
    """Meilleure vidéo pour la requête : on compare les titres au lieu de prendre le 1er résultat (pub, mix…)."""
    import json, re, urllib.parse
    import requests
    html = requests.get("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query),
                        headers=UA, cookies=YT_COOKIES, timeout=8).text
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", html)
    cands = []
    if m:
        def walk(o):
            if isinstance(o, dict):
                if "videoRenderer" in o:
                    v = o["videoRenderer"]
                    title = "".join(r.get("text", "") for r in v.get("title", {}).get("runs", []))
                    owner = "".join(r.get("text", "") for r in v.get("ownerText", {}).get("runs", []))
                    if v.get("videoId"):
                        cands.append((v["videoId"], title, owner))
                for x in o.values():
                    walk(x)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        try:
            walk(json.loads(m.group(1)))
        except Exception:
            pass
    if not cands:
        f = re.search(r'"videoId":"([\w-]{11})"', html)
        return f.group(1) if f else None
    words = [w for w in _norm_txt(query).split() if w not in ("audio", "clip", "officiel", "de", "la", "le")]

    def score(c):
        t = _norm_txt(c[1] + " " + c[2]).split()
        hit = sum(1 for w in words if w in t)
        return (hit, -cands.index(c))
    return max(cands[:12], key=score)[0]


def _deezer_track(query: str):
    import requests
    r = requests.get("https://api.deezer.com/search", params={"q": query, "limit": 1}, timeout=8).json()
    d = r.get("data") or []
    return d[0]["id"] if d else None


def _shortcut_info(lnk: str):
    """(cible, arguments) d'un raccourci .lnk."""
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($args[0]); $s.TargetPath; $s.Arguments", lnk],
                       capture_output=True, text=True, timeout=10, creationflags=0x08000000)
    lines = r.stdout.splitlines() + ["", ""]
    return lines[0].strip(), lines[1].strip()


def open_in_installed_app(name: str, url: str) -> bool:
    """Ouvre l'URL DANS l'appli web installée (Chrome/Edge « Installer l'application »), pas dans un onglet."""
    if not _APPS:
        scan_apps()
    lnk = _APPS.get(name, "")
    if not str(lnk).lower().endswith(".lnk"):
        return False
    try:
        target, args = _shortcut_info(lnk)
        if "--app-id=" not in args or not target.lower().endswith(("chrome_proxy.exe", "msedge_proxy.exe", "chrome.exe", "msedge.exe")):
            return False
        subprocess.Popen(f'"{target}" {args} --app-launch-url-for-shortcuts-menu-item="{url}"',
                         creationflags=0x08000000)  # chaîne passée telle quelle à Windows (guillemets du raccourci gardés)
        bring_to_front(exes=(), title_hint=name.split()[0], delay=1.5, tries=8)
        return True
    except Exception:
        return False


def play_music(query: str, service: str = "youtube") -> str:
    """Lance un titre/artiste sur le service choisi, sans clé API ni compte Premium.
    youtube / youtube_music : lecture automatique de la 1re vidéo trouvée.
    deezer : ouvre directement le titre trouvé. spotify : ouvre la recherche puis lance la lecture."""
    import webbrowser
    service = (service or "youtube").lower()
    try:
        if service in ("youtube", "youtube_music"):
            import re as _re
            base = _re.sub(r"\b(de|du|des|la|le|les|d')\b", " ", query)
            base = " ".join(base.split()) or query
            fixed = correct_query(query)
            suffix = " audio" if service == "youtube_music" else ""
            vid = None
            for q in dict.fromkeys((fixed, query, base)):  # corrigé, puis tel que dit, puis sans les petits mots
                vid = _youtube_id(q + suffix)
                if vid:
                    query = q
                    break
            if not vid:
                return f"Rien trouvé pour « {query} »."
            host = "music.youtube.com" if service == "youtube_music" else "www.youtube.com"
            url = f"https://{host}/watch?v={vid}"
            # appli installée (YouTube Music / YouTube installés depuis Chrome ou Edge) : on reste dedans
            if not open_in_installed_app("youtube music" if service == "youtube_music" else "youtube", url):
                open_url(url)
            _autoplay(after=3)
            return f"Je lance « {query} »."
        if service == "deezer":
            tid = _deezer_track(query)
            if not tid:
                return f"Rien trouvé pour « {query} » sur Deezer."
            try:
                os.startfile(f"deezer://www.deezer.com/track/{tid}")
            except OSError:
                open_url(f"https://www.deezer.com/track/{tid}")
            _autoplay(after=4)
            return f"Je lance « {query} » sur Deezer."
        # Spotify : recherche dans l'appli, puis Entrée sur le meilleur résultat
        os.startfile(f"spotify:search:{query}")
        sp = None
        for _ in range(10):  # attend la fenêtre Spotify (5 s max)
            time.sleep(0.5)
            sp = next((w for w in _windows() if w[1] == "spotify.exe"), None)
            if sp:
                break
        if not sp:
            return f"Recherche « {query} » ouverte dans Spotify."
        _force_front(sp[0]); time.sleep(1.5)
        if user32.GetForegroundWindow() != sp[0]:
            return f"Recherche « {query} » ouverte dans Spotify."  # jamais de frappe dans une autre fenêtre
        for vk in (0x09, 0x0D):  # Tab puis Entrée (lecture du meilleur résultat)
            if user32.GetForegroundWindow() != sp[0]:
                break
            user32.keybd_event(vk, 0, 0, 0); user32.keybd_event(vk, 0, 2, 0); time.sleep(0.4)
        _autoplay(after=1, keywords=("spotify",))
        return f"Je lance « {query} » sur Spotify."
    except Exception as e:
        return f"Impossible de lancer la musique : {e}"


def _is_playing() -> bool:
    try:
        from . import media
        return any(p for _, _, _, p, _ in media.sessions())
    except Exception:
        return False


def _page_key(title_low: str):
    """Touche lecture/pause propre au site affiché dans le navigateur."""
    if "youtube music" in title_low:
        return 0x20  # Espace
    if "youtube" in title_low:
        return 0x4B  # K
    if "deezer" in title_low:
        return 0x20
    return None


def press_play_in_browser() -> bool:
    """Chrome bloque la lecture auto : une vraie frappe clavier dans la page compte comme un geste de
    l'utilisateur et débloque la lecture. Uniquement si la fenêtre au premier plan est le bon site."""
    hwnd = user32.GetForegroundWindow()
    t = ctypes.create_unicode_buffer(512); user32.GetWindowTextW(hwnd, t, 512)
    key = _page_key(t.value.lower())
    if key is None:
        return False
    user32.keybd_event(key, 0, 0, 0); user32.keybd_event(key, 0, 2, 0)
    return True


def _autoplay(after=3, keywords=None):
    """Après ouverture : premier plan, puis lecture si rien ne joue (vérifie ensuite que ça joue)."""
    import threading

    def run():
        time.sleep(after)
        for _ in range(6):
            if _is_playing():
                return
            try:
                from . import media
                media.ensure_playing(timeout=1.5) if keywords is None else media.ensure_playing(keywords=keywords, timeout=1.5)
            except Exception:
                pass
            time.sleep(1.6)
            if _is_playing():
                return
            wins = [w for w in _windows() if w[1] in BROWSERS]
            if wins:
                _force_front(wins[0][0]); time.sleep(0.4)
                press_play_in_browser()
            time.sleep(1.5)
    threading.Thread(target=run, daemon=True).start()


def resume() -> str:
    if _is_playing():
        return "C'est déjà en lecture."
    try:
        from . import media
        if media.play():
            time.sleep(0.8)
            if _is_playing():
                return "Lecture lancée."
    except Exception:
        pass
    # pas de session média (page bloquée par la lecture auto) : frappe dans l'onglet du navigateur
    wins = [w for w in _windows() if w[1] in BROWSERS and _page_key(w[2].lower())]
    if wins:
        _force_front(wins[0][0]); time.sleep(0.4)
        press_play_in_browser()
        return "Lecture lancée."
    _press(VK["play_pause"])
    return "Lecture lancée."


def pause_music() -> str:
    try:
        from . import media
        if media.pause():
            return "Pause."
    except Exception:
        pass
    _press(VK["play_pause"])
    return "Pause."


def what_is_playing() -> str:
    try:
        from . import media
        t = media.now_playing()
        return f"C'est {t}." if t else "Rien ne joue en ce moment."
    except Exception:
        return "Je ne peux pas voir ce qui joue."


def spotify_play(query: str) -> str:  # compatibilité
    return play_music(query, "spotify")


# ---------- Fichiers ----------
def _allowed(p: Path, cfg) -> bool:
    p = p.resolve()
    for f in cfg["allowed_folders"]:
        try:
            if p.is_relative_to(Path(f).resolve()):
                return True
        except (OSError, ValueError):
            pass
    return False


def _key(name: str) -> str:
    """« Jarvis-Windows », « jarvis windows », « Jarvis_Windows.zip » -> « jarviswindows »"""
    import re
    return re.sub(r"[^a-z0-9]", "", _norm_txt(name))


def _search(query: str, cfg, dirs_only=False, limit=15, depth=4):
    q = _key(query)
    if not q:
        return []
    hits = []
    for folder in cfg["allowed_folders"]:
        root = Path(folder)
        if not root.exists():
            continue
        stack = [(root, 0)]
        while stack:
            d, lv = stack.pop()
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                if e.name.startswith((".", "$")) or e.name in ("node_modules", "_internal", "AppData"):
                    continue
                is_dir = e.is_dir(follow_symlinks=False)
                k = _key(Path(e.name).stem if not is_dir else e.name)
                if (not dirs_only or is_dir) and (q == k or q in k):
                    hits.append((0 if q == k else 1, 0 if is_dir else 1, len(k), e.path))
                if is_dir and lv < depth:
                    stack.append((e.path, lv + 1))
    hits.sort()
    return [h[3] for h in hits[:limit]]


def find_files(query: str, cfg) -> str:
    return "\n".join(_search(query, cfg)) or "Aucun fichier trouvé."


def is_shortcut(path: str) -> bool:
    """Raccourci d'appli (.lnk/.url) du menu Démarrer ou du Bureau."""
    p = str(path).lower()
    return p.endswith((".lnk", ".url")) and any(k in p for k in ("\\start menu\\", "\\menu démarrer\\", "\\desktop\\"))


def open_path(path: str, cfg) -> str:
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    if not p.exists():
        return "Ce chemin n'existe pas."
    if is_shortcut(str(p)):
        try:
            os.startfile(str(p))
        except OSError:
            return open_app(p.stem)  # raccourci cassé : on passe par l'appli installée (Store…)
        return f"{p.stem} lancé."
    if not _allowed(p, cfg):
        return "Ce dossier n'est pas dans les dossiers autorisés."
    os.startfile(str(p))
    return f"{p.stem} ouvert."


def open_folder(name: str, cfg=None) -> str:
    known = {"bureau": "Desktop", "documents": "Documents", "telechargements": "Downloads",
             "téléchargements": "Downloads", "musique": "Music", "images": "Pictures", "vidéos": "Videos",
             "videos": "Videos", "photos": "Pictures"}
    sub = known.get(name.lower().strip())
    if sub:
        from . import config as _c
        real = Path(_c.known_folder(sub))
        if real.exists():
            os.startfile(str(real)); bring_to_front(exes=("explorer.exe",), delay=0.8)
            return f"Dossier {name} ouvert."
    from . import config as _c
    hits = _search(name, cfg or _c.load(), dirs_only=True, limit=1)
    if hits:
        os.startfile(hits[0]); bring_to_front(exes=("explorer.exe",), delay=0.8)
        return f"Dossier {Path(hits[0]).name} ouvert."
    return f"Je ne trouve aucun dossier nommé « {name} »."


def organize_downloads(cfg) -> str:
    from . import config as _c
    dl = Path(_c.known_folder("Downloads"))
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


# ---------- Captures d'écran ----------
def _kf(name):
    from . import config as _c
    return _c.known_folder(name)


def screenshot(mode: str = "screen") -> str:
    """Capture RÉELLE : écran entier (tous les écrans si « all ») ou fenêtre active, enregistrée dans
    Images\\Captures d'écran\\Jarvis et copiée dans le presse-papiers. « zone » = outil de sélection Windows."""
    import datetime
    if mode == "zone":
        subprocess.Popen(["explorer", "ms-screenclip:"])
        return "Sélectionnez la zone à capturer."
    from PIL import ImageGrab
    if mode == "window":
        from ctypes import wintypes
        r = wintypes.RECT()
        ctypes.windll.dwmapi.DwmGetWindowAttribute(user32.GetForegroundWindow(), 9, ctypes.byref(r), ctypes.sizeof(r))
        img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
    else:
        img = ImageGrab.grab(all_screens=(mode == "all"))
    folder = Path(_kf("Pictures")) / "Captures d'écran" / "Jarvis"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Capture {datetime.datetime.now():%Y-%m-%d %H-%M-%S}.png"
    img.save(path)
    try:  # copie dans le presse-papiers (Ctrl+V direct dans Discord, WhatsApp…)
        subprocess.run(["powershell", "-NoProfile", "-STA", "-Command",
                        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
                        f"[Windows.Forms.Clipboard]::SetImage([Drawing.Image]::FromFile('{path}'))"],
                       timeout=10, creationflags=0x08000000)
    except Exception:
        pass
    return "Capture enregistrée dans Images, Captures d'écran, Jarvis, et copiée : prête à coller."


def open_last_screenshot() -> str:
    folder = Path(_kf("Pictures")) / "Captures d'écran" / "Jarvis"
    shots = sorted(folder.glob("*.png"), key=lambda p: p.stat().st_mtime) if folder.exists() else []
    if not shots:
        return "Aucune capture pour l'instant."
    os.startfile(str(shots[-1]))
    return "Voici la dernière capture."


# ---------- Système ----------
def system(action: str) -> str:
    if action == "lock":
        user32.LockWorkStation()
        return "Session verrouillée."
    if action == "screenshot":
        return screenshot("screen")
    if action == "shutdown":
        subprocess.run(["shutdown", "/s", "/t", "30"], creationflags=0x08000000)
        return "Arrêt dans 30 secondes. Dites « annule l'arrêt » pour annuler."
    if action == "restart":
        subprocess.run(["shutdown", "/r", "/t", "30"], creationflags=0x08000000)
        return "Redémarrage dans 30 secondes."
    if action == "cancel_shutdown":
        subprocess.run(["shutdown", "/a"], creationflags=0x08000000)
        return "Arrêt annulé."
    if action == "sleep":  # VRAIE veille (rundll32 SetSuspendState part en veille prolongée si elle est activée)
        subprocess.Popen(["powershell", "-NoProfile", "-Command",
                          "Add-Type -AssemblyName System.Windows.Forms; Start-Sleep 2; "
                          "[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)"],
                         creationflags=0x08000000)
        return "Mise en veille de l'ordinateur."
    return "Action système inconnue."


def now() -> str:
    d = datetime.datetime.now()
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    return f"Nous sommes {jours[d.weekday()]} {d:%d/%m/%Y}, il est {d:%H:%M}."


def web_search(query: str) -> str:
    open_url(f"https://www.google.com/search?q={query}")
    return f"Recherche « {query} » ouverte."


def _browser_window(hint=""):
    """Fenêtre de navigateur la plus récente (ou celle dont le titre contient « hint »)."""
    wins = [w for w in _windows() if w[1] in BROWSERS]
    if hint:
        best = max(wins, key=lambda w: _sim(hint, w[2]), default=None)
        if best and _sim(hint, best[2]) >= 0.5:
            return best
        return None
    return wins[0] if wins else None


def _keys(*vks):
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, 2, 0)


def close_tab(name: str = "") -> str:
    """Ferme l'onglet actif du navigateur (ou celui dont le titre correspond à « name »)."""
    w = _browser_window(name)
    if not w:
        return f"Je ne trouve pas d'onglet « {name} »." if name else "Aucun navigateur ouvert."
    _force_front(w[0]); time.sleep(0.3)
    if user32.GetForegroundWindow() != w[0]:
        return "Je n'ai pas pu mettre le navigateur au premier plan."
    _keys(0x11, 0x57)  # Ctrl+W
    return "Onglet fermé."


def close_window(name: str = "") -> str:
    """Ferme la fenêtre au premier plan (ou celle dont le titre correspond), comme la croix."""
    if name:
        best = max(_windows(), key=lambda w: _sim(name, w[2]), default=None)
        if not best or _sim(name, best[2]) < 0.5:
            return f"Je ne trouve pas de fenêtre « {name} »."
        hwnd, exe, title = best
    else:
        hwnd = user32.GetForegroundWindow()
        info = next((w for w in _windows() if w[0] == hwnd), (hwnd, "", ""))
        exe, title = info[1], info[2]
    if exe in PROTECTED:
        return "Je ne ferme pas cette fenêtre système."
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    return f"Fenêtre « {title[:40]} » fermée." if title else "Fenêtre fermée."


def show_images(query: str) -> str:
    import urllib.parse
    open_url("https://www.google.com/search?udm=2&q=" + urllib.parse.quote(query))
    return f"Voici des images de {query}."


def open_website(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    open_url(url)
    return f"{url} ouvert."


def type_text(text: str, submit: bool = False) -> str:
    """Tape du texte dans la fenêtre active (presse-papiers + Ctrl+V), puis Entrée si submit."""
    if text.strip() == "" and "\n" in text:
        _press(0x0D); return "Entrée."
    subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
                   input=text, text=True, creationflags=0x08000000)
    time.sleep(0.15)
    user32.keybd_event(0x11, 0, 0, 0); user32.keybd_event(0x56, 0, 0, 0)
    user32.keybd_event(0x56, 0, 2, 0); user32.keybd_event(0x11, 0, 2, 0)
    if submit:
        time.sleep(0.2); _press(0x0D)
        return "Texte tapé et validé."
    return "Texte tapé."


# ---------- Modes d'alimentation ----------
POWER_MODES = {"economie": ("961cc777-2547-4f9d-8174-7d86181b8a7a", "Mode économie d'énergie activé."),
               "equilibre": ("00000000-0000-0000-0000-000000000000", "Mode équilibré activé."),
               "performance": ("ded574b5-45a0-4f42-8737-46345c09c238", "Mode performances maximales activé.")}


def power_mode(mode: str) -> str:
    """Mode d'alimentation Windows (le curseur « Mode de gestion de l'alimentation »)."""
    import unicodedata
    m = "".join(c for c in unicodedata.normalize("NFD", mode.lower()) if unicodedata.category(c) != "Mn")
    key = "economie" if any(k in m for k in ("eco", "batterie", "energie")) else \
          "performance" if any(k in m for k in ("perf", "max", "jeu", "puissan")) else "equilibre"
    guid, msg = POWER_MODES[key]
    r = subprocess.run(["powercfg", "/overlaysetactive", guid], capture_output=True, text=True, creationflags=0x08000000)
    if r.returncode != 0:
        os.startfile("ms-settings:powersleep")
        return "Je n'ai pas pu changer le mode directement ; j'ai ouvert les réglages d'alimentation."
    return msg


# ---------- Disposition des fenêtres ----------
def _find_window(name: str, exclude=()):
    import unicodedata
    def n(t):
        return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    want = n(name).split()
    best, best_s = None, 0.0
    for w in _windows():
        if w[0] in exclude or not w[2]:
            continue
        hay = n(w[2] + " " + w[1].removesuffix(".exe"))
        hit = sum(1 for x in want if x in hay.split() or x in hay)
        if not hit:
            continue
        sc = hit / len(want) - 0.02 * len(n(w[2]).split())  # titre court = plus probable (« YouTube » ≠ « YouTube Music »)
        if sc > best_s:
            best, best_s = w, sc
    return best if best_s >= 0.5 else None


ZONES = {"gauche": (0, 0, .5, 1), "droite": (.5, 0, .5, 1), "haut": (0, 0, 1, .5), "bas": (0, .5, 1, .5),
         "haut gauche": (0, 0, .5, .5), "haut droite": (.5, 0, .5, .5), "bas gauche": (0, .5, .5, .5),
         "bas droite": (.5, .5, .5, .5)}


def arrange_window(name: str, position: str, exclude=()) -> str:
    """Place une fenêtre : gauche, droite, haut gauche…, plein écran, réduire, autre écran."""
    from ctypes import wintypes
    import unicodedata
    pos = "".join(c for c in unicodedata.normalize("NFD", position.lower()) if unicodedata.category(c) != "Mn")
    pos = " ".join(w for w in pos.replace("-", " ").split() if w in ("haut", "bas", "gauche", "droite")) or pos
    w = _find_window(name, exclude) if name else next(((h, "", "") for h in [user32.GetForegroundWindow()]), None)
    if not w:
        return f"Je ne trouve pas de fenêtre « {name} »."
    hwnd = w[0]
    if any(k in pos for k in ("plein", "agrandi", "maxim", "grand")):
        user32.ShowWindow(hwnd, 3); return f"{name or 'Fenêtre'} en plein écran."
    if any(k in pos for k in ("redui", "cache", "minim")):
        user32.ShowWindow(hwnd, 6); return f"{name or 'Fenêtre'} réduite."
    user32.ShowWindow(hwnd, 9)  # restaure si agrandie
    class MI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]
    mon = user32.MonitorFromWindow(hwnd, 2)
    if "autre" in pos or "ecran" in pos and "deux" in pos:
        mons = []
        cb = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double)(
            lambda h, *_: mons.append(h) or 1)
        user32.EnumDisplayMonitors(None, None, cb, 0)
        if len(mons) > 1:
            mon = next(m for m in mons if m != mon)
        pos = "plein"
    mi = MI(); mi.cbSize = ctypes.sizeof(MI)
    user32.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi))
    r = mi.rcWork
    x, y, ww, hh = ZONES.get(pos, (0, 0, 1, 1))
    W, H = r.right - r.left, r.bottom - r.top
    user32.SetWindowPos(hwnd, 0, int(r.left + x * W), int(r.top + y * H), int(ww * W), int(hh * H), 0x0040)
    if pos == "plein":
        user32.ShowWindow(hwnd, 3)
    _force_front(hwnd)
    return f"{name or 'Fenêtre'} placée {('à ' + pos) if pos in ZONES else ''}".strip() + "."


def arrange_two(a: str, pa: str, b: str, pb: str) -> str:
    # le nom le plus précis d'abord (« YouTube Music » avant « YouTube »), puis on l'exclut pour le second
    pairs = sorted([(a, pa), (b, pb)], key=lambda t: -len(t[0]))
    w1 = _find_window(pairs[0][0])
    r1 = arrange_window(pairs[0][0], pairs[0][1])
    r2 = arrange_window(pairs[1][0], pairs[1][1], exclude=(w1[0],) if w1 else ())
    return f"{r1} {r2}"


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
SENSITIVE = {("system", "shutdown"), ("system", "restart"), ("system", "sleep"), ("organize_downloads", None),
             ("close_app", None), ("open_website", None), ("open_path", None)}
# type_text : confirmé seulement pour un long texte (voir brain), un code ou un mot court se tape directement
# outils qui lisent du contenu extérieur (web, écran) : après eux, plus d'action automatique dans le même tour
READERS = {"ask_web", "look_at_screen"}
