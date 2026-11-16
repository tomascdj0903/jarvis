"""Clic « précis » : on lit l'arbre d'accessibilité de Windows (UI Automation) de la fenêtre active
— titres de vidéos, liens, boutons, profils, menus — et on clique au centre exact de l'élément.
Aucune IA, aucun token, précis au pixel. La vision (capture + IA) ne sert qu'en secours."""
import re
import time
import unicodedata

FILLER = r"^(toi |moi |sur |la |le |les |l'|un |une |ce |cette |cet )*"
KINDS = r"(video|bouton|lien|profil|onglet|icone|menu|image|photo|case|option|element|titre|chaine|playlist|dossier|fichier|article|message|conversation|contact|musique|chanson|son|morceau|album|artiste|clip|son)s?"
STOP = {"de", "du", "des", "la", "le", "les", "un", "une", "et", "a", "en", "d'", "l'", "sur", "par"}
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
    w = [x for x in want.split() if len(x) > 1 and x not in STOP] or [x for x in want.split() if len(x) > 1]
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


def _row_score(want, ctrl, name):
    """Liste de musiques / vidéos : le titre est un élément, l'artiste un autre de la même ligne.
    Si tous les mots du nom sont dans la demande, on complète avec les textes de la ligne (parent, grand-parent)."""
    nw = [x for x in _norm(name).split() if x not in STOP]
    ww = set(want.split())
    if not nw or not all(x in ww for x in nw):
        return 0.0
    texts, node = [name], ctrl
    for _ in range(2):
        try:
            node = node.GetParentControl()
            if node is None:
                break
            texts += [c.Name for c in node.GetChildren()[:12] if c.Name and len(c.Name) < 120]
        except Exception:
            break
        if _score(want, " ".join(texts)) >= 0.99:
            break
    return min(_score(want, " ".join(texts)), 1.0) - 0.05


def wake_chrome(hwnd) -> int:
    """Chrome / Edge (et leurs applis installées comme YouTube Music) n'exposent le contenu de la page
    à l'accessibilité qu'après qu'un « lecteur » l'a demandé. On le demande sur chaque zone de page
    (Chrome_RenderWidgetHostHWND) : c'est la méthode utilisée par les lecteurs d'écran. Renvoie le nombre de zones."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    oleacc = ctypes.windll.oleacc
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, buf, 64)
        if buf.value == "Chrome_RenderWidgetHostHWND":
            found.append(h)
        return True
    user32.EnumChildWindows(hwnd, cb, 0)

    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]
    iid = GUID(0x618736E0, 0x3C3D, 0x11CF, (ctypes.c_ubyte * 8)(0x81, 0x0C, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71))  # IAccessible
    for h in found:
        ptr = ctypes.c_void_p()
        try:
            oleacc.AccessibleObjectFromWindow(h, wintypes.DWORD(0xFFFFFFFC), ctypes.byref(iid), ctypes.byref(ptr))  # OBJID_CLIENT
            user32.SendMessageTimeoutW(h, 0x003D, 0, 0xFFFFFFE7, 2, 500, None)  # WM_GETOBJECT, UiaRootObjectId
        except Exception:
            pass
    return len(found)


def find(target: str, deadline=8.0, hwnd=None):
    """Meilleur élément visible de la fenêtre (active par défaut) dont le nom correspond. (ctrl, score) ou (None, 0)."""
    import ctypes
    import uiautomation as auto
    want, kind, where = clean_target(target)
    if not want:
        return None, 0.0
    hwnd = hwnd or ctypes.windll.user32.GetForegroundWindow()
    try:
        if wake_chrome(hwnd):
            time.sleep(0.8)  # Chrome construit l'arbre de la page
    except Exception:
        pass
    root = auto.ControlFromHandle(hwnd)
    if root is None:
        return None, 0.0
    good_types = {auto.ControlType.HyperlinkControl, auto.ControlType.ButtonControl, auto.ControlType.ListItemControl,
                  auto.ControlType.MenuItemControl, auto.ControlType.TabItemControl, auto.ControlType.TreeItemControl,
                  auto.ControlType.ImageControl, auto.ControlType.CheckBoxControl, auto.ControlType.RadioButtonControl,
                  auto.ControlType.DataItemControl, auto.ControlType.SplitButtonControl}
    best, best_s = None, 0.0
    end = time.time() + deadline
    for _ in range(6):  # l'arbre de la page arrive par morceaux : on repasse jusqu'à la limite de temps
        for ctrl, _depth in auto.WalkControl(root, includeTop=False, maxDepth=60):
            if time.time() > end:
                break
            try:
                name = ctrl.Name
                if not name or len(name) > 300:
                    continue
                sc = _score(want, name)
                if sc < 0.85:
                    sc = max(sc, _row_score(want, ctrl, name))
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
        time.sleep(0.6)
    return best, best_s


def click(target: str):
    """Clic précis, fait dans un PETIT PROCESSUS À PART : la bibliothèque UI Automation rend le processus
    « conscient du DPI », ce qui déplaçait l'orbe de Jarvis au milieu de l'écran. Isolé, plus aucun effet."""
    import json
    import logging
    import os
    import subprocess
    import sys
    import tempfile
    out = os.path.join(tempfile.gettempdir(), f"jarvis_uiclick_{os.getpid()}.json")
    try:
        os.remove(out)
    except OSError:
        pass
    # Jarvis.exe n'a pas de console (stdout = None) : le résultat passe par un petit fichier
    cmd = [sys.executable, "--uiclick", out, target] if getattr(sys, "frozen", False) else \
          [sys.executable, "-m", "jarvis.uiclick", out, target]
    try:
        subprocess.run(cmd, timeout=16, creationflags=0x08000000 if os.name == "nt" else 0)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        logging.getLogger("jarvis").info("clic précis « %s » : %s", target, data)
        return data.get("result")
    except Exception as e:
        logging.getLogger("jarvis").warning("clic précis « %s » : %s", target, e)
        return None


def click_here(target: str, found=None):
    """(Dans le processus à part) clique l'élément trouvé, ou None si rien de sûr (=> vision)."""
    try:
        ctrl, sc = found or find(target)
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


def cli(out: str, target: str):
    import json
    res, err, best = None, "", ""
    try:
        ctrl, sc = find(target)
        best = f"{ctrl.Name[:60]} ({sc:.2f})" if ctrl is not None else "rien"
        res = click_here(target, (ctrl, sc))
    except Exception as e:
        err = str(e)[:200]
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"result": res, "best": best, "error": err}, f, ensure_ascii=False)


if __name__ == "__main__":
    import sys
    cli(sys.argv[1], " ".join(sys.argv[2:]))
