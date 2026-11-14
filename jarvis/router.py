"""Routeur local : traite les commandes courantes SANS appeler l'IA.
→ réponse instantanée, zéro token consommé, fonctionne même quota épuisé.
Renvoie (texte_a_dire) ou None si la phrase doit partir au LLM."""
import re
import unicodedata

from . import actions, config


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s']", " ", t).strip()


WAKE = r"^(hey |he |ok |dis )?jarvis[ ,]*"

RULES = [
    (r"\b(musique|morceau|chanson|son|titre|piste) suivant|\bchange (de|la) (musique|chanson|son)|\bsuivant(e)?$|\bnext\b",
     lambda m: actions.media("next")),
    (r"\b(musique|morceau|chanson|piste) precedent|\bprecedent(e)?$|\bremets? la (musique|chanson) d'avant",
     lambda m: actions.media("previous")),
    (r"^(mets? (en )?)?pause$|^(reprends?|relance|play|lecture)( la musique)?$|^stop la musique$",
     lambda m: actions.media("play_pause")),
    (r"\b(monte|augmente|plus fort)( le (son|volume))?", lambda m: actions.volume("up", 5)),
    (r"\b(baisse|diminue|moins fort)( le (son|volume))?", lambda m: actions.volume("down", 5)),
    (r"^(coupe|mute)( le)? (son|volume)$|^silence$", lambda m: actions.volume("mute")),
    (r"\b(meteo|temps fait|quel temps|temperature|fait (il |t il )?(chaud|froid)|va t il pleuvoir|il va pleuvoir|pleuvoir)\b",
     lambda m: _weather(m.string)),
    (r"\bquelle heure|\bquel jour|\bon est quel|\bla date\b", lambda m: actions.now()),
    (r"^verrouille( le pc| l'ordi(nateur)?| la session)?$", lambda m: actions.system("lock")),
    (r"^annule l'arret$", lambda m: actions.system("cancel_shutdown")),
    (r"^(mets|joue|lance|ecoute)( moi)? (de la musique de |la musique |la chanson |le son |l'album |du |de la |des |de l'|de )?(?P<q>.+?)( (sur|avec|dans) (?P<svc>youtube music|yt music|youtube|spotify|deezer))?$",
     lambda m: _music(m)),
    (r"^(lance|ouvre|demarre) (?!le dossier|mes |mon dossier|le site|youtube\.|google\.)(.+)$",
     lambda m: _open(m.group(2))),
    (r"^(ouvre|affiche) (mes |le dossier |mon dossier )(bureau|documents|telechargements|musique|images|videos)$",
     lambda m: actions.open_folder(m.group(3))),
]


SERVICES = {"youtube music": "youtube_music", "yt music": "youtube_music", "youtube": "youtube",
            "spotify": "spotify", "deezer": "deezer"}


def _is_app(name: str) -> bool:
    """Vrai si « name » est une appli installée ou un site connu (Spotify, Discord, YouTube Music…)."""
    web = getattr(actions, "WEB_APPS", {})
    if any(k == name or k in name for k in web):
        return True
    find = getattr(actions, "_find_app", None)
    try:
        return bool(find and find(name)[1])
    except Exception:
        return False


def _music(m):
    q = m.group("q").strip()
    svc = m.group("svc")
    if svc:  # « lance PNL sur YouTube Music » : forcément de la musique
        return actions.play_music(q, SERVICES[svc])
    if q in SERVICES:  # « lance YouTube Music » tout seul = ouvrir le service
        return None
    if m.group(1) in ("lance", "ecoute") and not m.group(3) and _is_app(q):
        return None  # « lance Discord » = ouvrir l'appli
    return actions.play_music(q, config.load().get("music_service", "youtube"))


def _weather(t):
    from . import weather
    day = next((d for d in ("apres demain", "demain", "lundi", "mardi", "mercredi", "jeudi", "vendredi",
                            "samedi", "dimanche") if d in t), "aujourd'hui")
    day = "après-demain" if day == "apres demain" else day
    m = re.search(r"\b(?:a|sur|pour) ([a-z][a-z' -]+?)(?: demain| apres demain| aujourd'hui| ce| cette|$)", t)
    city = m.group(1).strip() if m and m.group(1) not in ("quelle", "combien") else ""
    try:
        return weather.weather(city, day)
    except Exception:
        return None  # l'IA prendra le relais


def _open(name):
    res = actions.open_app(name)
    return None if "introuvable" in res else res  # sinon on laisse l'IA chercher mieux


def route(text: str):
    t = re.sub(WAKE, "", _norm(text)).strip()
    if not t:
        return None
    for pat, fn in RULES:
        m = re.search(pat, t)
        if m:
            try:
                res = fn(m)
            except Exception:
                res = None
            if res is not None:
                return res
    return None
