"""Test RÉEL sur Windows : une appli Chrome (--app, comme YouTube Music installée) avec une liste de titres.
Jarvis doit trouver « Armistice de Jossman » (titre et artiste dans deux éléments de la même ligne) puis cliquer dessus.
Sans réveil de l'accessibilité, Chrome n'expose rien : c'est exactement le bug vu le 16/11 (« best: rien »)."""
import ctypes
import io
import os
import pathlib
import subprocess
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from jarvis import uiclick  # noqa: E402

d = pathlib.Path(tempfile.mkdtemp())
page = d / "ytm.html"
rows = [("Sec", "Jossman"), ("Limpide", "Owen"), ("Armistice (Live)", "Autre Artiste"), ("Armistice", "Jossman"), ("ODD", "PNL")]
items = "".join(f'<div role="listitem" class="row"><a href="#" onclick="document.title=\'CLIQUE {t} - {a}\';return false">{t}</a>'
                f'<span> {a}</span><span> 3:12</span></div>' for t, a in rows)
carousel = ('<div style="width:300px;overflow:hidden;white-space:nowrap;border:1px solid #ccc">'
            '<div style="display:inline-block;width:240px">Mix rose</div>'
            '<a href="#" style="display:inline-block;width:260px" '
            'onclick="document.title=\'CLIQUE Pistolet\';return false">Pistolet Rose 2 - A COLORS SHOW</a></div>')
page.write_text(f"<!doctype html><html><head><meta charset=utf-8><title>Test Jarvis</title></head>"
                f"<body><h1>Résultats</h1><div role=list>{items}</div><h2>Carrousel</h2>{carousel}</body></html>",
                encoding="utf-8")
chrome = next(p for p in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"] if os.path.exists(p))
proc = subprocess.Popen([chrome, f"--app={page.as_uri()}", f"--user-data-dir={d / 'profil'}", "--no-first-run",
                         "--no-default-browser-check", "--window-size=900,700"])
user32 = ctypes.windll.user32


def window(title):
    buf = ctypes.create_unicode_buffer(256)
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        user32.GetWindowTextW(h, buf, 256)
        if user32.IsWindowVisible(h) and buf.value.startswith(title):
            found.append(h)
        return True
    user32.EnumWindows(cb, 0)
    return found[0] if found else None


hwnd = None
for _ in range(60):
    hwnd = window("Test Jarvis")
    if hwnd:
        break
    time.sleep(0.5)
assert hwnd, "fenêtre Chrome --app introuvable"
time.sleep(2)
print("zones de page Chrome :", uiclick.wake_chrome(hwnd))
ctrl, sc = uiclick.find("la musique armistice de jossman", hwnd=hwnd)
print("trouvé :", ctrl.Name if ctrl else None, round(sc, 2))
try:
    assert ctrl is not None and ctrl.Name.startswith("Armistice") and "Live" not in ctrl.Name, \
        "le titre n'a pas été trouvé dans l'appli Chrome"
    assert sc >= 0.85, f"score trop bas ({sc:.2f}) : Jarvis passerait à la vision"
    user32.SetForegroundWindow(hwnd)
    res = uiclick.click_here("armistice de jossman", (ctrl, sc))
    time.sleep(1)
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    print("clic :", res, "| titre de la fenêtre :", buf.value)
    assert buf.value.startswith("CLIQUE Armistice - Jossman"), "le clic n'a pas atteint le bon titre"
    print("CLIC PRÉCIS DANS UNE APPLI CHROME : OK")
    # élément à moitié caché dans un carrousel (cas « Pistolet Rose 2 » du 16/11 : trouvé mais clic à côté)
    ctrl, sc = uiclick.find("pistolet rose 2 a l'ecran", hwnd=hwnd)
    print("carrousel, trouvé :", ctrl.Name if ctrl else None, round(sc, 2))
    assert ctrl is not None and ctrl.Name.startswith("Pistolet Rose 2"), "titre du carrousel introuvable"
    res = uiclick.click_here("pistolet rose 2", (ctrl, sc))
    time.sleep(1)
    user32.GetWindowTextW(hwnd, buf, 256)
    print("clic :", res, "| titre de la fenêtre :", buf.value)
    assert buf.value == "CLIQUE Pistolet", "le titre à moitié caché n'a pas été déclenché"
    print("ÉLÉMENT À MOITIÉ CACHÉ : OK")
finally:
    proc.kill()
