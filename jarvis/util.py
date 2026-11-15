"""Petites fonctions pures (testables sans interface)."""


YES = ("oui", "ouais", "confirme", "vas-y", "vas y", "ok", "okay", "d'accord", "affirmatif", "yes", "go", "valide")
NO = ("non", "pas", "annule", "arrête", "arrete", "stop", "surtout pas", "jamais", "no")


def is_yes(ans: str) -> bool:
    """Oui franc et court ; toute négation l'emporte (« non pas ok » = non)."""
    import re
    words = re.findall(r"[a-zà-ÿ'-]+", ans.lower())
    if not words or any(w in NO for w in words):
        return False
    return len(words) <= 6 and any(w in YES or " ".join(words).startswith(w) for w in YES)


WAKE_FORMS = ("jarvis", "jervis", "jarvi", "jarvice", "djarvis", "charvis", "jarviz", "service", "jervice", "harvis", "garvis")


def _dist(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def has_wake_word(text: str) -> bool:
    """Le mot « Jarvis » (ou une transcription approchante) dans les premiers mots."""
    import re
    words = re.findall(r"[a-zà-ÿ]+", text.lower())[:6]
    return any(w in WAKE_FORMS or (len(w) >= 5 and _dist(w, "jarvis") <= 2) for w in words)


def strip_wake_word(text: str) -> str:
    import re
    return re.sub(r"^\W*((hey|hé|he|eh|et|ok|okay|dis|salut)\W+)?\w*(jarvis|jervis|jarvi|service)\w*\W*", "", text,
                  flags=re.I).strip() or text


def _privacy(text: str, cfg) -> str:
    """Journal : phrases masquées par défaut (RGPD)."""
    return text if cfg.get("log_utterances") else f"<{len(text)} caractères>"


def session_locked() -> bool:
    import ctypes
    u = ctypes.windll.user32
    h = u.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
    if not h:
        return True
    ok = u.SwitchDesktop(h)
    u.CloseDesktop(h)
    return not ok




def speakable(text: str) -> str:
    """Texte à lire à voix haute : sans ponctuation « parlée » ni chemins/liens complets."""
    import re
    t = str(text)
    # lien -> nom du site (« youtube »), chemin Windows -> nom du fichier sans extension
    t = re.sub(r"https?://(?:www\.|m\.)?([\w-]+)(?:\.[\w-]+)*\S*?(?=[.,;!?]?(?:\s|$))", lambda m: m.group(1), t)
    t = re.sub(r"\b[A-Za-z]:\\(?:[^\\\n]*\\)*([^\\\n.]+?)(?:\.\w{1,5})?(?=[\s.,;!?]|$)", lambda m: m.group(1), t)
    t = re.sub(r"(?<=\w)[\u2010\u2011\u2012](?=\w)", "-", t)      # puis‑je -> puis-je
    t = re.sub(r"\s[\u2013\u2014-]{1,2}\s", ", ", t)                 # tirets de phrase -> pause
    t = t.replace("…", ".").replace("...", ".").replace("°C", " degrés").replace("°", " degrés")
    t = re.sub(r"[«»\"“”„*#_`~|\\\[\]{}<>^=]", " ", t)
    t = re.sub(r"\s*[()]\s*", ", ", t)
    t = re.sub(r"(?<=[a-zà-ÿ])/(?=[a-zà-ÿ])", " ou ", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", t)  # émojis
    t = re.sub(r"([.!?])(?=[A-ZÀ-Ý])", r"\1 ", t)                        # « Maître.Comment »
    t = re.sub(r"\s+([,.])", r"\1", t)
    t = re.sub(r"([,;:])\1+|,\s*([.!?])", lambda m: m.group(1) or m.group(2), t)
    t = re.sub(r"^[\s,;:]+", "", re.sub(r"\s{2,}", " ", t))
    return t.strip()
