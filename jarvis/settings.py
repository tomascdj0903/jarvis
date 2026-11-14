"""Assistant de configuration (premier lancement) et fenêtre Réglages.
Vérifie aussi ce qui manque sur le PC et propose de le régler."""
import socket
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

import requests

from . import config

BG, CARD, CYAN, GOLD, WHITE, GREY, RED, GREEN = (
    "#03060C", "#07101C", "#29D8FF", "#FFB547", "#E8FBFF", "#8FA8B8", "#FF6B6B", "#4ADE80")


def list_mics():
    """[(index, nom)] des micros d'entrée, sans doublons d'API audio."""
    import sounddevice as sd
    out, seen = [], set()
    try:
        apis = sd.query_hostapis()
        pref = next((i for i, a in enumerate(apis) if "MME" in a["name"]), None)
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and (pref is None or d["hostapi"] == pref):
                name = d["name"].strip()
                if name not in seen and "mappeur" not in name.lower() and "mapper" not in name.lower():
                    seen.add(name)
                    out.append((i, name))
    except Exception:
        pass
    return out


def checks(cfg):
    """Diagnostic : [(ok, libellé, action_texte, action_fn)]."""
    res = []
    try:
        socket.create_connection(("api.groq.com", 443), timeout=4).close()
        res.append((True, "Connexion internet", None, None))
    except OSError:
        res.append((False, "Pas d'accès internet (l'IA et la voix en ont besoin)", None, None))
    mics = list_mics()
    res.append((bool(mics), f"Micros détectés : {len(mics)}" if mics else "Aucun micro détecté",
                "Réglages micro Windows", lambda: webbrowser.open("ms-settings:privacy-microphone")))
    from . import actions
    if not actions._APPS:
        actions.scan_apps()
    has_spotify = any("spotify" in k for k in actions._APPS)
    res.append((has_spotify, "Spotify installé" if has_spotify else "Spotify non installé (facultatif)",
                None if has_spotify else "Installer Spotify",
                None if has_spotify else (lambda: webbrowser.open("ms-windows-store://pdp/?productid=9NCBCSZSJRSB"))))
    return res


class Wizard:
    """Fenêtre en 1 page : clé, nom, micro (avec vu-mètre), options, diagnostic."""

    def __init__(self, root, cfg, first_run=True, on_done=None):
        self.cfg, self.on_done, self.first_run = cfg, on_done, first_run
        w = self.w = tk.Toplevel(root)
        w.title("J.A.R.V.I.S. — " + ("Bienvenue" if first_run else "Réglages"))
        w.configure(bg=BG)
        w.resizable(False, False)
        try:
            w.iconbitmap(str(config.resource("assets/jarvis.ico")))
        except Exception:
            pass
        W, H = 560, 760
        w.geometry(f"{W}x{H}+{(w.winfo_screenwidth()-W)//2}+{(w.winfo_screenheight()-H)//2}")
        w.attributes("-topmost", True)
        style = ttk.Style(w)
        style.theme_use("clam")
        style.configure("J.TCombobox", fieldbackground=CARD, background=CARD, foreground=WHITE,
                        arrowcolor=CYAN, bordercolor="#12324A")
        self.level = 0.0
        self.stream = None

        tk.Label(w, text="J.A.R.V.I.S.", fg=WHITE, bg=BG, font=("Segoe UI Black", 22)).pack(pady=(18, 0))
        tk.Label(w, text="Configuration" if not first_run else "Configurons votre assistant — 1 minute",
                 fg=CYAN, bg=BG, font=("Segoe UI", 10)).pack(pady=(0, 10))

        f = tk.Frame(w, bg=BG); f.pack(fill="x", padx=28)

        def label(t):
            tk.Label(f, text=t, fg=GREY, bg=BG, font=("Segoe UI Semibold", 9), anchor="w").pack(fill="x", pady=(10, 2))

        def entry(val, show=None):
            e = tk.Entry(f, bg=CARD, fg=WHITE, insertbackground=CYAN, relief="flat", font=("Segoe UI", 11),
                         highlightthickness=1, highlightbackground="#12324A", highlightcolor=CYAN, show=show)
            e.insert(0, val); e.pack(fill="x", ipady=6)
            return e

        label("1 · CLÉ API GROQ (gratuite)")
        row = tk.Frame(f, bg=BG); row.pack(fill="x")
        self.key = tk.Entry(row, bg=CARD, fg=WHITE, insertbackground=CYAN, relief="flat", font=("Segoe UI", 11),
                            highlightthickness=1, highlightbackground="#12324A", highlightcolor=CYAN, show="•")
        self.key.insert(0, cfg.get("groq_api_key", "")); self.key.pack(side="left", fill="x", expand=True, ipady=6)
        self._btn(row, "Obtenir", lambda: webbrowser.open("https://console.groq.com/keys"), GOLD).pack(side="left", padx=(6, 0))
        self._btn(row, "Tester", self.test_key).pack(side="left", padx=(6, 0))
        self.key_status = tk.Label(f, text="", fg=GREY, bg=BG, font=("Segoe UI", 9), anchor="w")
        self.key_status.pack(fill="x")

        label("2 · COMMENT DOIS-JE VOUS APPELER ?")
        self.name = entry(cfg.get("user_name", "Monsieur"))

        label("3 · MICRO — parlez : la barre doit bouger")
        self.mics = list_mics()
        names = ["Micro par défaut de Windows"] + [n for _, n in self.mics]
        self.mic = ttk.Combobox(f, values=names, state="readonly", style="J.TCombobox", font=("Segoe UI", 10))
        cur = cfg.get("input_device")
        idx = next((k + 1 for k, (i, _) in enumerate(self.mics) if i == cur), 0)
        self.mic.current(idx)
        self.mic.pack(fill="x", ipady=4)
        self.mic.bind("<<ComboboxSelected>>", lambda e: self.start_meter())
        self.meter = tk.Canvas(f, height=10, bg="#12324A", highlightthickness=0); self.meter.pack(fill="x", pady=(6, 0))

        label("4 · MUSIQUE — où lancer « mets du Dua Lipa »")
        self.services = [("youtube", "YouTube"), ("youtube_music", "YouTube Music"),
                         ("spotify", "Spotify (appli)"), ("deezer", "Deezer")]
        self.music = ttk.Combobox(f, values=[n for _, n in self.services], state="readonly",
                                  style="J.TCombobox", font=("Segoe UI", 10))
        self.music.current(next((k for k, (v, _) in enumerate(self.services)
                                 if v == cfg.get("music_service", "youtube")), 0))
        self.music.pack(fill="x", ipady=4)

        label("5 · OPTIONS")
        self.autostart = tk.BooleanVar(value=cfg.get("_autostart", True))
        self.orb = tk.BooleanVar(value=cfg.get("show_idle_orb", True))
        for var, txt in ((self.autostart, "Lancer Jarvis au démarrage de Windows (en arrière-plan)"),
                         (self.orb, "Afficher l'orbe de veille en bas à droite")):
            tk.Checkbutton(f, text=txt, variable=var, bg=BG, fg=WHITE, selectcolor=CARD, activebackground=BG,
                           activeforeground=WHITE, font=("Segoe UI", 10), anchor="w").pack(fill="x")
        srow = tk.Frame(f, bg=BG); srow.pack(fill="x", pady=(4, 0))
        tk.Label(srow, text="Sensibilité de « Hey Jarvis »", fg=WHITE, bg=BG, font=("Segoe UI", 10)).pack(side="left")
        self.sens = tk.Scale(srow, from_=1, to=10, orient="horizontal", bg=BG, fg=WHITE, troughcolor=CARD,
                             highlightthickness=0, length=200, showvalue=False)
        self.sens.set(round((0.75 - cfg.get("wake_threshold", 0.35)) / 0.06))
        self.sens.pack(side="right")

        label("6 · VÉRIFICATION DU PC")
        self.diag = tk.Frame(f, bg=CARD); self.diag.pack(fill="x")
        threading.Thread(target=self.run_checks, daemon=True).start()

        self._btn(w, "Terminer" if first_run else "Enregistrer", self.save, CYAN, big=True).pack(pady=18)
        w.protocol("WM_DELETE_WINDOW", self.close)
        self.start_meter()
        self.draw_meter()

    def _btn(self, parent, text, cmd, color=CYAN, big=False):
        return tk.Button(parent, text=text, command=cmd, bg=color, fg=BG, activebackground=WHITE, relief="flat",
                         font=("Segoe UI Black" if big else "Segoe UI Semibold", 11 if big else 9),
                         padx=26 if big else 10, pady=8 if big else 4, cursor="hand2")

    # ---- micro ----
    def device(self):
        k = self.mic.current()
        return None if k <= 0 else self.mics[k - 1][0]

    def start_meter(self):
        import numpy as np
        import sounddevice as sd
        if self.stream:
            try: self.stream.close()
            except Exception: pass
        def cb(data, frames, t, status):
            self.level = min(1.0, float(np.sqrt(np.mean(data.astype(np.float32) ** 2))) / 3000)
        try:
            self.stream = sd.InputStream(device=self.device(), samplerate=16000, channels=1, dtype="int16", callback=cb)
            self.stream.start()
        except Exception:
            self.stream, self.level = None, -1

    def draw_meter(self):
        c = self.meter; c.delete("all")
        wdt = c.winfo_width() or 500
        if self.level < 0:
            c.create_text(wdt / 2, 5, text="micro inutilisable — choisissez-en un autre", fill=RED, font=("Segoe UI", 7))
        else:
            c.create_rectangle(0, 0, int(wdt * self.level), 10, fill=GREEN if self.level > .08 else CYAN, width=0)
        if self.w.winfo_exists():
            self.w.after(60, self.draw_meter)

    # ---- clé ----
    def test_key(self):
        self.key_status.config(text="Test en cours…", fg=GREY)
        def run():
            try:
                r = requests.get("https://api.groq.com/openai/v1/models", timeout=10,
                                 headers={"Authorization": f"Bearer {self.key.get().strip()}"})
                ok, msg = r.ok, ("✓ Clé valide" if r.ok else f"✗ Clé refusée ({r.status_code})")
            except Exception as e:
                ok, msg = False, f"✗ {e.__class__.__name__}"
            self.w.after(0, lambda: self.key_status.config(text=msg, fg=GREEN if ok else RED))
        threading.Thread(target=run, daemon=True).start()

    # ---- diagnostic ----
    def run_checks(self):
        res = checks(self.cfg)
        def show():
            for ok, txt, act, fn in res:
                r = tk.Frame(self.diag, bg=CARD); r.pack(fill="x", padx=10, pady=3)
                tk.Label(r, text="✓" if ok else "!", fg=GREEN if ok else GOLD, bg=CARD,
                         font=("Segoe UI Black", 10), width=2).pack(side="left")
                tk.Label(r, text=txt, fg=WHITE, bg=CARD, font=("Segoe UI", 9), anchor="w").pack(side="left")
                if act and fn:
                    tk.Button(r, text=act, command=fn, bg=CARD, fg=CYAN, relief="flat", cursor="hand2",
                              font=("Segoe UI Semibold", 8)).pack(side="right")
        if self.w.winfo_exists():
            self.w.after(0, show)

    def close(self):
        if self.stream:
            try: self.stream.close()
            except Exception: pass
        self.w.destroy()
        if self.on_done:
            self.on_done(False)

    def save(self):
        if not self.key.get().strip():
            self.key_status.config(text="La clé est nécessaire.", fg=RED)
            return
        self.cfg.update(groq_api_key=self.key.get().strip(), user_name=self.name.get().strip() or "Monsieur",
                        input_device=self.device(), show_idle_orb=self.orb.get(),
                        music_service=self.services[max(0, self.music.current())][0],
                        wake_threshold=round(0.75 - self.sens.get() * 0.06, 2), _autostart=self.autostart.get())
        config.save(self.cfg)
        if self.stream:
            try: self.stream.close()
            except Exception: pass
        self.w.destroy()
        if self.on_done:
            self.on_done(True)
