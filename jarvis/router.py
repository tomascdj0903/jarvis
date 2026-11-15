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
ALIASES = [(r"\bcloud ?code\b", "claude code"), (r"\b(cloud|clode|clod|klode) (ia|ai)\b", "claude"),
           (r"\b(sur|avec|dans|ouvre|lance) (cloud|clode|clod|klode)$", r"\1 claude"),(r"\byoutube musique\b", "youtube music"), (r"\byou tube\b", "youtube"), (r"\bdeezeur\b", "deezer"),
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

def _remind(t):
    from . import assistant
    when = assistant.parse_when(t)
    if not when:
        return None
    m = re.search(r"\b(?:de |d'|que |qu'|pour )(.+)$", re.sub(r"^rappelle(?: moi)?\s*", "", t))
    what = m.group(1) if m else "votre rappel"
    what = re.sub(r"\s*(dans \d+.*|dans une? demi.*|(?:demain |apres-demain |lundi |mardi |mercredi |jeudi |vendredi |samedi |dimanche )?(?:a|vers) \d{1,2}\s*(?:h|heures?).*)$", "", what).strip() or "votre rappel"
    return assistant.add_reminder(what, when)


def _click(target):
    import threading
    from . import vision
    st = {}
    # confirmation vocale fournie par l'appli (voir app.py) ; sans elle, pas de clic
    conf = getattr(route, "confirm", None)
    if conf is None:
        return None
    return vision.click_on(target, config.load(), conf)


def _timer(t):
    from . import assistant
    when = assistant.parse_when("dans " + re.sub(r"^.*?(de |d')", "", t, count=1))
    if not when:
        return None
    return assistant.add_reminder("minuteur terminé", when).replace("je vous le rappelle", "minuteur lancé, je vous préviens")


AI_CHATS = {"claude": "https://claude.ai/new", "claude code": "https://claude.ai/code",
            "chatgpt": "https://chatgpt.com/", "chat gpt": "https://chatgpt.com/", "gemini": "https://gemini.google.com/app",
            "perplexity": "https://www.perplexity.ai/", "mistral": "https://chat.mistral.ai/chat", "le chat": "https://chat.mistral.ai/chat"}


def _new_chat(m):
    svc = m.group("ai").strip()
    url = AI_CHATS.get(svc)
    if not url:
        return None
    actions.open_url(url)
    return f"Nouvelle conversation ouverte sur {svc.title()}."


RULES = [
    (r"\b(affiche|montre|cherche|trouve|ouvre|mets)( moi)? (une |des |la |les )?(photos?|images?|portraits?) (de |d'|du |des )(?P<q>.+?)( sur (google|internet|le web|le navigateur))?$",
     lambda m: actions.show_images(m.group("q"))),
    (r"^ferme( moi)? (l'onglet|cet onglet|l'onglet actif|la page|cette page)$", lambda m: actions.close_tab()),
    (r"^ferme( moi)? (l'onglet|la page) (de |d'|du |des |sur )?(?P<n>.+)$", lambda m: actions.close_tab(m.group("n"))),
    (r"^ferme( moi)? (la fenetre|cette fenetre)$", lambda m: actions.close_window()),
    (r"^(ouvre|va sur) google (et |puis )?(cherche|recherche|tape|trouve)( moi)? (?P<q>.+)$",
     lambda m: actions.web_search(m.group("q"))),
    (r"^(cherche|recherche|tape)( moi)? (?P<q>.+?) sur google$", lambda m: actions.web_search(m.group("q"))),
    (r"(nouveau|nouvelle) (chat|conversation|discussion|session)( (sur|avec|dans))? (?P<ai>claude code|claude|chat ?gpt|gemini|perplexity|mistral|le chat)\b",
     _new_chat),
    (r"\b(devoirs?|controles?)\b.*\b(aujourd'hui|demain|a faire|du jour|de nico|reste|rappel)|^(mes |les |quels sont les |c'est quoi les )?devoirs\b",
     lambda m: __import__("jarvis.assistant", fromlist=["x"]).planning_devoirs()),
    (r"^(ouvre|lance|affiche)( le| mon)? planning( partage)?$", lambda m: actions.open_app("planning partage")),
    (r"^(clique|clic|appuie) (sur )?(?P<c>.+)$", lambda m: _click(m.group("c"))),
    (r"^rappelle(?: moi)?\b", lambda m: _remind(m.string)),
    (r"^(mets |lance |demarre )?(un )?minuteur (de |d')?.*\d", lambda m: _timer(m.string)),
    (r"^(quels sont |liste |dis moi |lis )?(mes|les) rappels$|^j'ai des rappels$", lambda m: __import__("jarvis.assistant", fromlist=["x"]).list_reminders()),
    (r"^(supprime|efface|annule) (tous )?(mes|les) rappels$", lambda m: __import__("jarvis.assistant", fromlist=["x"]).clear_reminders()),
    (r"^(prends |prend |ajoute )?(une )?note (que |: )?(?P<n>.+)$|^note (que )?(?P<n2>.+)$",
     lambda m: __import__("jarvis.assistant", fromlist=["x"]).add_note(m.group("n") or m.group("n2"))),
    (r"^(lis|relis|dis moi) mes (dernieres )?notes$", lambda m: __import__("jarvis.assistant", fromlist=["x"]).read_notes()),
    (r"^(briefing|mon briefing|fais moi (le|mon) (point|briefing)|quoi de neuf aujourd'hui)$",
     lambda m: __import__("jarvis.assistant", fromlist=["x"]).briefing(config.load().get("user_name", ""))),
    (r"\b(batterie|autonomie)\b", lambda m: __import__("jarvis.assistant", fromlist=["x"]).battery()),
    (r"^(coupe|desactive|eteins|deconnecte)( le)? wifi$", lambda m: __import__("jarvis.assistant", fromlist=["x"]).wifi(False)),
    (r"^(active|allume|ouvre|reconnecte)( le| les)? (wifi|bluetooth|mode avion|economie d'energie|parametres du son|ne pas deranger)$",
     lambda m: __import__("jarvis.assistant", fromlist=["x"]).open_settings_page(m.string)),
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
    (r"\b(son|volume)\b\D*?(?P<v>\d{1,3})\s*(%|pour ?cent)?\s+(et|puis)\b.*\bluminosite\b\D*?(?P<l>\d{1,3})",
     lambda m: actions.set_volume(int(m.group("v"))) + " " + actions.set_brightness(int(m.group("l")))),
    (r"\b(son|volume)\b\D*?\b(a|au|sur)\s*(?P<v>\d{1,3})\s*(%|pour ?cent)?(?!.*lumin)", lambda m: actions.set_volume(int(m.group("v")))),
    (r"\b(luminosite|lumiere de l'ecran)\b\D*?\b(a|au|sur)\s*(?P<v>\d{1,3})\s*(%|pour ?cent)?(?!.*(son|volume))",
     lambda m: actions.set_brightness(int(m.group("v")))),
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
    NOT_MUSIC = ("nouveau", "nouvelle", "chat", "conversation", "onglet", "fenetre", "page", "site", "recherche",
                 "document", "fichier", "mail", "message", "appel", "partie", "jeu", "minuteur", "rappel", "programme",
                 "logiciel", "application", "appli", "projet", "session", "film", "serie")
    if m.group("verb") in ("lance", "cherche") and (len(raw.split()) >= 4 or any(w in raw.split() for w in NOT_MUSIC)):
        return None  # phrase qui ne ressemble pas à un titre : l'IA décide
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


DICT = re.compile(r"^\W*(?:(?:hey|hé|he|ok|dis|et)\W+)?(?:jarvis\W+)?(?:écris|écrit|ecris|tape|dicte)(?:[- ]moi)?\s*[:,]?\s+(.+)$", re.I)


def route(text: str):
    d = DICT.match(text.strip())
    if d:  # dictée : le texte est tapé tel que dit (accents, majuscules, ponctuation)
        return actions.type_text(d.group(1).strip())
    t = clean(text)
    try:
        from . import macros
        steps = macros.match(t)
        if steps:
            return macros.run(steps)
    except Exception:
        pass
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


def looks_like_command(text: str) -> bool:
    """Vrai si la phrase ressemble à une commande connue (sans rien exécuter)."""
    t = clean(text)
    return bool(t) and any(re.search(pat, t) for pat, _ in RULES)
