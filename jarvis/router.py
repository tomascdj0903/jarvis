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


WAKE = r"^((hey|he|hey|eh|et|ok|okay|dis|salut|ah|oh|bon) )*jarvis\b[ ,]*"
POLITE = [
    r"^(est ce que |est-ce que )?(tu peux|tu pourrais|peux tu|pourrais tu|tu veux bien|veux tu) ",
    r"^(je veux|je voudrais|j'aimerais|j'ai envie d'|j'ai envie de|on va|on peut|vas y) ",
    r"\b(s'il te plait|s'il vous plait|stp|svp|merci)\b",
]
INFINITIVES = {"mettre": "mets", "lancer": "lance", "jouer": "joue", "ecouter": "ecoute", "ouvrir": "ouvre",
               "demarrer": "demarre", "fermer": "ferme", "monter": "monte", "baisser": "baisse", "couper": "coupe",
               "passer": "passe", "chercher": "cherche", "mettre en pause": "pause"}
ALIASES = [(r"\byoutube musique\b", "youtube music"), (r"\byou tube\b", "youtube"), (r"\bdeezeur\b", "deezer"),
           (r"\bspotifaille\b", "spotify"), (r"\bytb\b", "youtube")]
FILLER = r"^(une |un |la |le |les |des |du |de la |de l'|l'|de )?(musique|chanson|son|sons|titre|morceau|clip|video|album|playlist)s? (de |d'|du |des )?"


def clean(text: str) -> str:
    t = _norm(text)
    t = re.sub(WAKE, "", t).strip()
    for a, b in ALIASES:
        t = re.sub(a, b, t)
    for p in POLITE:
        t = re.sub(p, "", t).strip()
    t = re.sub(WAKE, "", t).strip()
    w = t.split(" ", 1)
    if w and w[0] in INFINITIVES:
        t = INFINITIVES[w[0]] + (" " + w[1] if len(w) > 1 else "")
    t = re.sub(r"^(\w+) moi ", r"\1 ", t)  # « lance-moi » -> « lance »
    return re.sub(r"\s+", " ", t).strip()

RULES = [
    (r"\b(musique|morceau|chanson|son|titre|piste) suivant|\bchange (de|la) (musique|chanson|son)|\bsuivant(e)?$|\bnext\b",
     lambda m: actions.media("next")),
    (r"\b(musique|morceau|chanson|piste) precedent|\bprecedent(e)?$|\bremets? la (musique|chanson) d'avant",
     lambda m: actions.media("previous")),
    (r"^(mets? (en )?|fais )?pause$|^(arrete|stoppe?|coupe)( la)? (musique|lecture|video)$|^stop$",
     lambda m: actions.pause_music()),
    (r"^((lance|mets|reprends?|relance|demarre|remets)( la| le)? (lecture|musique|son|video)|lecture|play|reprends?|reprise|relance|remets)$",
     lambda m: actions.resume()),
    (r"\b(c'est quoi|quelle est|quel est|c est quoi) (cette|la|ce|le) (musique|chanson|son|titre|morceau)\b|\bqu'est ce qui (joue|passe)\b",
     lambda m: actions.what_is_playing()),
    (r"\b(monte|augmente|plus fort)( le (son|volume))?", lambda m: actions.volume("up", 5)),
    (r"\b(baisse|diminue|moins fort)( le (son|volume))?", lambda m: actions.volume("down", 5)),
    (r"^(coupe|mute)( le)? (son|volume)$|^silence$", lambda m: actions.volume("mute")),
    (r"\b(meteo|temps fait|quel temps|temperature|fait (il |t il )?(chaud|froid)|va t il pleuvoir|il va pleuvoir|pleuvoir)\b",
     lambda m: _weather(m.string)),
    (r"\bquelle heure|\bquel jour|\bon est quel|\bla date\b", lambda m: actions.now()),
    (r"^verrouille( le pc| l'ordi(nateur)?| la session)?$", lambda m: actions.system("lock")),
    (r"^annule l'arret$", lambda m: actions.system("cancel_shutdown")),
    (r"^(mets|lance|joue)( de la| une)? musique$", lambda m: actions.resume()),
    (r"^(ouvre|lance|va sur|demarre) (?P<svc>youtube music|yt music|youtube|spotify|deezer) (et|puis|pour) (mets|joue|lance|cherche|ecoute)( moi)? (?P<q>.+)$",
     lambda m: actions.play_music(_q(m.group("q")), SERVICES[m.group("svc")])),
    (r"^(?P<verb>mets|joue|lance|ecoute|cherche)( moi)? (?P<q>.+?)( (sur|avec|dans|via) (?P<svc>youtube music|yt music|youtube|spotify|deezer))?$",
     lambda m: _music(m)),
    (r"^(?P<q>.+?) (sur|avec|dans|via) (?P<svc>youtube music|yt music|youtube|spotify|deezer)$",
     lambda m: actions.play_music(_q(m.group("q")), SERVICES[m.group("svc")])),
    (r"^(lance|ouvre|demarre) (?!le dossier|mes |mon dossier|le site|youtube\.|google\.)(.+)$",
     lambda m: _open(m.group(2))),
    (r"^(ouvre|affiche|montre)( moi)? (mes |le dossier |mon dossier |les dossiers? )(?P<f>.+)$",
     lambda m: actions.open_folder(m.group("f"))),
]


SERVICES = {"youtube music": "youtube_music", "yt music": "youtube_music", "youtube": "youtube",
            "spotify": "spotify", "deezer": "deezer"}


def _is_app(name: str) -> bool:
    """Vrai si « name » est une appli installée ou un site connu (Spotify, Discord, YouTube Music…)."""
    web = getattr(actions, "WEB_APPS", {})
    if name in web:
        return True
    find = getattr(actions, "_find_app", None)
    try:
        return bool(find and find(name)[1])
    except Exception:
        return False


def _q(q: str) -> str:
    q = re.sub(FILLER, "", q.strip()).strip()
    return re.sub(r"^(du |de la |des |de l'|de |d')", "", q).strip()


def _music(m):
    raw = m.group("q").strip()
    svc = m.group("svc")
    if svc:  # « lance PNL sur YouTube Music » : forcément de la musique
        return actions.play_music(_q(raw), SERVICES[svc])
    if raw in SERVICES or raw in ("le site " + k for k in SERVICES):
        return None  # « lance YouTube Music » tout seul = ouvrir le service
    if m.group("verb") in ("lance", "ecoute", "cherche") and _is_app(raw):
        return None  # « lance Discord » = ouvrir l'appli
    if m.group("verb") == "cherche":
        return None
    return actions.play_music(_q(raw), config.load().get("music_service", "youtube"))


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
    t = clean(text)
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
