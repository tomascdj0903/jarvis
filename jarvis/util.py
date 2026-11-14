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


