"""Clic « précis » : on lit l'arbre d'accessibilité de Windows (UI Automation) de la fenêtre active
— titres de vidéos, liens, boutons, profils, menus — et on clique au centre exact de l'élément.
Aucune IA, aucun token, précis au pixel. La vision (capture + IA) ne sert qu'en secours."""
import re
import time
import unicodedata

FILLER = r"^(sur |la |le |les |l'|un |une |ce |cette |cet )*"
KINDS = r"(video|bouton|lien|profil|onglet|icone|menu|image|photo|case|option|element|titre|chaine|playlist|dossier|fichier|article|message|conversation|contact)s?"
WHERE = r"\b(a|sur|dans) (l'ecran|la page|la fenetre)\b|\ben (haut|bas)( a (gauche|droite))?\b|\ba (gauche|droite)\b"


def _norm(t):
    t = unicodedata.normalize("NFD", str(t).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9' ]+", " ", t).strip()


def clean_target(target: str):
    """« la vidéo devine le pokémon à l'écran » -> ('devine le pokemon', 'video', '') ;
    « le profil T-O-M-A-S » -> ('tomas', 'profil', '') ; « le profil en haut à gauche » -> ('', 'profil', 'en haut a gauche')."""
    t = _norm(target)
    t = re.sub(r"\b((?:[a-z] ){2,}[a-z])\b", lambda m: m.group(1).replace(" ", ""), t)  # t o m a s -> tomas
    where = " ".join(m.group(0) for m in re.finditer(WHERE, t))
    t = re.sub(WHERE, " ", t)
    t = re.sub(FILLER, "", t.strip())
    kind = ""
    m = re.match(KINDS + r"( (de |du |des |d'|nomme |appele |qui s'appelle ))?", t)
    if m:
        kind = re.sub(r"s$", "", m.group(0).split()[0])
        t = t[m.end():]
    t = re.sub(FILLER, "", t.strip())
    return re.sub(r"\s+", " ", t).strip(), kind, where.strip()


def _score(want, name):
    w = [x for x in want.split() if len(x) > 1]
    n = _norm(name)
    if not w or not n:
        return 0.0
    words = set(n.split())
    hit = sum(1 for x in w if x in words or (len(x) >= 4 and any(y.startswith(x[:4]) for y in words)))
    s = hit / len(w)
    if n == want:
        s += 1.0
    elif n.startswith(want):
        s += 0.3
    s -= min(0.3, max(0, len(n.split()) - len(w)) * 0.01)  # nom bien plus long = moins sûr
    return s


def find(target: str, deadline=4.0):
    """Meilleur élément visible de la fenêtre active dont le nom correspond. (ctrl, score) ou (None, 0)."""
    import ctypes
    import uiautomation as auto
    want, kind, where = clean_target(target)
    if not want:
        return None, 0.0
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    root = auto.ControlFromHandle(hwnd)
    if root is None:
        return None, 0.0
    good_types = {auto.ControlType.HyperlinkControl, auto.ControlType.ButtonControl, auto.ControlType.ListItemControl,
                  auto.ControlType.MenuItemControl, auto.ControlType.TabItemControl, auto.ControlType.TreeItemControl,
                  auto.ControlType.ImageControl, auto.ControlType.CheckBoxControl, auto.ControlType.RadioButtonControl,
                  auto.ControlType.DataItemControl, auto.ControlType.SplitButtonControl}
    best, best_s = None, 0.0
    end = time.time() + deadline
    for _ in range(2):  # Chrome ne remplit son arbre qu'au 1er passage d'un lecteur d'accessibilité
        for ctrl, _depth in auto.WalkControl(root, includeTop=False, maxDepth=60):
            if time.time() > end:
                break
            try:
                name = ctrl.Name
                if not name or len(name) > 300:
                    continue
                sc = _score(want, name)
                if sc < 0.6:
                    continue
                if ctrl.ControlType in good_types:
                    sc += 0.15
                if kind == "profil" and ctrl.ControlType in (auto.ControlType.ImageControl, auto.ControlType.ButtonControl):
                    sc += 0.1
                if ctrl.IsOffscreen:
                    continue
                r = ctrl.BoundingRectangle
                if r.width() <= 2 or r.height() <= 2:
                    continue
                if sc > best_s:
                    best, best_s = ctrl, sc
            except Exception:
                continue
        if best is not None or time.time() > end:
            break
        time.sleep(0.4)
    return best, best_s


def click(target: str):
    """Clique l'élément trouvé. Renvoie un message, ou None si rien de sûr n'a été trouvé (=> vision)."""
    try:
        ctrl, sc = find(target)
    except Exception:
        return None
    if ctrl is None or sc < 0.85:
        return None
    name = ctrl.Name.strip()
    try:
        ctrl.Click(simulateMove=False, waitTime=0.1)
    except Exception:
        try:
            ctrl.GetInvokePattern().Invoke()
        except Exception:
            return None
    return f"Clic sur « {name[:60]} »."
