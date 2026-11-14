"""Tests sans Windows : routeur, comparaison de versions, cerveau (HTTP simulé)."""
import sys, types
sys.path.insert(0, ".")
import jarvis
calls = []
fake = types.ModuleType("jarvis.actions")
for n in ("media", "volume", "now", "system", "open_folder"):
    setattr(fake, n, (lambda name: (lambda *a, **k: calls.append((name, a)) or f"{name}:{a}"))(n))
fake.open_app = lambda n: f"open:{n}"
fake.play_music = lambda q, s: f"play[{s}]:{q}"
fake.resume = lambda: "RESUME"; fake.pause_music = lambda: "PAUSE"; fake.what_is_playing = lambda: "NOWPLAYING"
fake.WEB_APPS = {"youtube music": "", "youtube": "", "deezer": "", "netflix": ""}
fake._find_app = lambda n: (n, "x") if n in ("spotify", "discord", "brawlhalla") else (None, None)
fake.WEB_APPS["youtube musique"] = ""
fake.SENSITIVE = {("system", "shutdown")}
sys.modules["jarvis.actions"] = fake; jarvis.actions = fake
import jarvis.config as config
config.load = lambda: dict(config.DEFAULTS)
from jarvis.router import route

YT, YTM, DEF = "youtube", "youtube_music", "youtube"
CASES = {
    # contrôle
    "Hey Jarvis, change de musique": "media:('next',)",
    "musique suivante": "media:('next',)",
    "passe à la chanson suivante": "media:('next',)",
    "pause": "PAUSE",
    "mets en pause": "PAUSE",
    "arrête la musique": "PAUSE",
    "mets de la musique": "RESUME",
    "Lance la lecture.": "RESUME",
    "reprends la lecture": "RESUME",
    "relance la musique": "RESUME",
    "lecture": "RESUME",
    "c'est quoi cette musique": "NOWPLAYING",
    "monte le son": "volume:('up', 5)",
    "tu peux baisser le volume stp": "volume:('down', 5)",
    "quelle heure est-il": "now:()",
    # applis / sites (nom exact)
    "lance Spotify": "open:spotify",
    "lance YouTube Music": "open:youtube music",
    "ouvre YouTube": "open:youtube",
    "lance youtube": "open:youtube",
    "ouvre Discord": "open:discord",
    "lance Brawlhalla": "open:brawlhalla",
    "Hé Jarvis, ouvre YouTube Musique": "open:youtube music",
    # musique
    "mets du Dua Lipa": f"play[{DEF}]:dua lipa",
    "joue Stromae sur deezer": "play[deezer]:stromae",
    "Lance PNL sur YouTube Music.": f"play[{YTM}]:pnl",
    "Hey Jarvis, lance PNL sur YouTube Music": f"play[{YTM}]:pnl",
    "Hé Jarvis, lance-moi PNL sur YouTube": f"play[{YT}]:pnl",
    "Et Jarvis lance PNL sur YouTube Musique": f"play[{YTM}]:pnl",
    "Je veux écouter PNL sur YouTube": f"play[{YT}]:pnl",
    "Tu peux mettre du PNL sur YouTube ?": f"play[{YT}]:pnl",
    "Lance une musique de PNL sur YouTube Music": f"play[{YTM}]:pnl",
    "Ouvre YouTube et mets PNL": f"play[{YT}]:pnl",
    "Ouvre YouTube Music et mets Ninho": f"play[{YTM}]:ninho",
    "Lance la vidéo de Squeezie sur YouTube": f"play[{YT}]:squeezie",
    "Lance Au DD sur YouTube Music": f"play[{YTM}]:au dd",
    "Jarvis, PNL sur YouTube Music": f"play[{YTM}]:pnl",
    "lance PNL": f"play[{DEF}]:pnl",
    "Lance moi du Jul": f"play[{DEF}]:jul",
    "mets Ninho sur Spotify": "play[spotify]:ninho",
    "lance Jul sur YouTube": f"play[{YT}]:jul",
    "joue l'album Deux frères de PNL": f"play[{DEF}]:deux freres de pnl",
    "mets la chanson Alors on danse": f"play[{DEF}]:alors on danse",
    "j'aimerais écouter Aya Nakamura s'il te plaît": f"play[{DEF}]:aya nakamura",
    "ouvre mes téléchargements": "open_folder:('telechargements',)",
    # vers l'IA
    "raconte-moi une blague": None,
    "qui a gagné la coupe du monde 2018": None,
    "cherche des recettes de crêpes": None,
}


def test_router():
    bad = [(p, route(p), w) for p, w in CASES.items() if route(p) != w]
    for b in bad:
        print("ÉCHEC", b)
    assert not bad, f"{len(bad)} phrases mal comprises"


def test_weather_routing():
    import jarvis.weather as w
    got = []
    w.weather = lambda city, day: got.append((city, day)) or "meteo"
    for phrase, want in {"quelle température fait-il demain": ("", "demain"),
                         "quel temps fait-il à Nice": ("nice", "aujourd'hui"),
                         "est-ce qu'il va pleuvoir samedi": ("", "samedi"),
                         "météo à Lisbonne après-demain": ("lisbonne", "après-demain")}.items():
        got.clear(); assert route(phrase) == "meteo", phrase; assert got[0] == want, (phrase, got)


def test_versions():
    from jarvis.updater import _v
    assert _v("v1.10.0") > _v("1.9.9") and _v("v1.3.3") == _v("1.3.3")


def test_brain_tool_loop():
    import json
    from jarvis import brain
    seq = [
        {"tool_calls": [{"id": "1", "function": {"name": "media", "arguments": json.dumps({"action": "next"})}}]},
        {"content": "Piste suivante, Monsieur."},
    ]

    class R:
        def __init__(self, m): self.m = m; self.status_code = 200; self.text = ""
        def json(self): return {"choices": [{"message": self.m}]}
    brain.requests.post = lambda *a, **k: R(seq.pop(0))
    b = brain.Brain(dict(config.DEFAULTS, groq_api_key="x"), print, lambda q: True)
    assert b.ask("change de musique") == "Piste suivante, Monsieur."
    assert len(b.history) == 2


if __name__ == "__main__":
    pass


def test_open_app_real():
    """La vraie fonction open_app (celle appelée par l'IA) ne doit jamais ouvrir YouTube par erreur."""
    import importlib, os as _os, webbrowser
    sys.modules.pop("jarvis.actions", None)
    real = importlib.import_module("jarvis.actions")
    opened = []
    webbrowser.open = lambda u: opened.append(u)
    _os.startfile = lambda t: opened.append(t)
    real._APPS.clear(); real._APPS.update({"spotify": "S.lnk", "discord": "D.lnk"})
    real.scan_apps = lambda: real._APPS
    real.play_music = lambda q, s: f"play[{s}]:{q}"
    exp = {"youtube": "https://www.youtube.com", "YouTube Music": "https://music.youtube.com",
           "le site youtube": "https://www.youtube.com", "Spotify": "S.lnk", "discord": "D.lnk"}
    for name, url in exp.items():
        opened.clear(); real.open_app(name); assert opened == [url], (name, opened)
    for name, want in {"PNL sur YouTube": "play[youtube]:pnl", "pnl sur youtube music": "play[youtube_music]:pnl"}.items():
        opened.clear(); assert real.open_app(name) == want and not opened, (name, opened)
    opened.clear(); assert "introuvable" in real.open_app("radio canada youtube") and not opened
    sys.modules["jarvis.actions"] = fake; jarvis.actions = fake


if __name__ == "__main__":
    test_router(); test_weather_routing(); test_versions(); test_brain_tool_loop(); test_open_app_real()
    print(f"TOUS LES TESTS OK ({len(CASES)} phrases)")
