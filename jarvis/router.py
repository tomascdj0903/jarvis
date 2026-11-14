"""Routeur local : traite les commandes courantes SANS appeler l'IA.
→ réponse instantanée, zéro token consommé, fonctionne même quota épuisé.
Renvoie (texte_a_dire) ou None si la phrase doit partir au LLM."""
import re
import unicodedata

from . import actions


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
    (r"\bquelle heure|\bquel jour|\bon est quel|\bla date\b", lambda m: actions.now()),
    (r"^verrouille( le pc| l'ordi(nateur)?| la session)?$", lambda m: actions.system("lock")),
    (r"^annule l'arret$", lambda m: actions.system("cancel_shutdown")),
    (r"^(lance|ouvre|demarre) (?!le dossier|mes |mon dossier|le site|youtube\.|google\.)(.+)$",
     lambda m: _open(m.group(2))),
    (r"^(ouvre|affiche) (mes |le dossier |mon dossier )(bureau|documents|telechargements|musique|images|videos)$",
     lambda m: actions.open_folder(m.group(3))),
]


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
                return fn(m)
            except Exception:
                return None
    return None
