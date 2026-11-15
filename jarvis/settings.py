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
        w.resizable(True, True)
        w.minsize(520, 420)
        try:
            w.iconbitmap(str(config.resource("assets/jarvis.ico")))
        except Exception:
            pass
        W = 600
        H = min(900, w.winfo_screenheight() - 100)  # jamais plus haut que l'écran
        w.geometry(f"{W}x{H}+{(w.winfo_screenwidth()-W)//2}+{max(10, (w.winfo_screenheight()-H)//2 - 30)}")
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

        # barre du bas fixe : le bouton reste toujours visible
        bar = tk.Frame(w, bg=CARD, highlightthickness=1, highlightbackground="#12324A")
        bar.pack(side="bottom", fill="x")
        self._btn(bar, "Terminer" if first_run else "Enregistrer", self.save, CYAN, big=True).pack(side="right", padx=16, pady=10)
        self._btn(bar, "Annuler", self.close, GREY).pack(side="right", pady=10)
        tk.Label(bar, text="Faites défiler pour tout voir · fenêtre agrandissable", fg=GREY, bg=CARD,
                 font=("Segoe UI", 9)).pack(side="left", padx=16)
        # zone de réglages défilante
        holder = tk.Frame(w, bg=BG); holder.pack(fill="both", expand=True)
        cv = tk.Canvas(holder, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(holder, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); cv.pack(side="left", fill="both", expand=True)
        f = tk.Frame(cv, bg=BG)
        win = cv.create_window((28, 0), window=f, anchor="nw")
        f.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width - 56))
        self._cv = cv
        w.bind_all("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units") if self.w.winfo_exists() else None)
        # une liste déroulante survolée ne doit JAMAIS changer de valeur à la molette (bug du réglage musique)
        w.bind_class("TCombobox", "<MouseWheel>", lambda e: (cv.yview_scroll(int(-e.delta / 120), "units"), "break")[1])

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

        label("1 bis · CLÉS DE SECOURS (facultatif) — si Groq est saturé, Jarvis passe sur celles-ci")
        self.extra = {}
        for k, nm, link in (("gemini_api_key", "Gemini", "https://aistudio.google.com/apikey"),
                            ("openrouter_api_key", "OpenRouter", "https://openrouter.ai/settings/keys")):
            r = tk.Frame(f, bg=BG); r.pack(fill="x", pady=(2, 0))
            tk.Label(r, text=nm, width=11, anchor="w", fg=WHITE, bg=BG, font=("Segoe UI", 10)).pack(side="left")
            e = tk.Entry(r, bg=CARD, fg=WHITE, insertbackground=CYAN, relief="flat", font=("Segoe UI", 10),
                         highlightthickness=1, highlightbackground="#12324A", highlightcolor=CYAN, show="•")
            e.insert(0, cfg.get(k, "")); e.pack(side="left", fill="x", expand=True, ipady=4)
            self._btn(r, "Obtenir", (lambda u=link: webbrowser.open(u)), GOLD).pack(side="left", padx=(6, 0))
            if k == "gemini_api_key":
                self._btn(r, "Tester", self.test_gemini).pack(side="left", padx=(6, 0))
            self.extra[k] = e
        tk.Label(f, text="Gemini : clé « AIza… » ou nouvelle clé « AQ.… » ; plusieurs clés possibles, séparées par une virgule",
                 fg=GREY, bg=BG, font=("Segoe UI", 8), anchor="w").pack(fill="x")
        self.gem_status = tk.Label(f, text="", fg=GREY, bg=BG, font=("Segoe UI", 9), anchor="w", justify="left",
                                   wraplength=520)
        self.gem_status.pack(fill="x")

        label("1 quater · PLANNING PARTAGÉ — clé du raccourci iPhone (RAPPELS_SECRET)")
        prow0 = tk.Frame(f, bg=BG); prow0.pack(fill="x")
        self.pkey = tk.Entry(prow0, bg=CARD, fg=WHITE, insertbackground=CYAN, relief="flat", font=("Segoe UI", 10),
                             highlightthickness=1, highlightbackground="#12324A", highlightcolor=CYAN, show="•")
        self.pkey.insert(0, cfg.get("planning_key", "")); self.pkey.pack(side="left", fill="x", expand=True, ipady=4)
        self._btn(prow0, "Tester", self.test_planning).pack(side="left", padx=(6, 0))
        self.pstatus = tk.Label(f, text="", fg=GREY, bg=BG, font=("Segoe UI", 9), anchor="w"); self.pstatus.pack(fill="x")

        label("1 ter · LANGUE")
        self.langs = [("fr", "Français"), ("pt", "Português"), ("en", "English")]
        self.lang = ttk.Combobox(f, values=[n for _, n in self.langs], state="readonly", style="J.TCombobox",
                                 font=("Segoe UI", 10))
        self.lang.current(next((i for i, (c, _) in enumerate(self.langs) if c == cfg.get("language", "fr")), 0))
        self.lang.pack(fill="x", ipady=4)

        label("1 quinquies · CARACTÈRE DE JARVIS")
        self.persos = [("poli", "Poli — majordome classique, vouvoiement"),
                       ("complice", "Complice — humour, taquin, tutoie si vous tutoyez"),
                       ("cash", "Cash — du répondant, parle cru, vannes et gros mots s'il le faut")]
        self.perso = ttk.Combobox(f, values=[n for _, n in self.persos], state="readonly", style="J.TCombobox",
                                  font=("Segoe UI", 10))
        self.perso.current(next((i for i, (c, _) in enumerate(self.persos) if c == cfg.get("personality", "cash")), 2))
        self.perso.pack(fill="x", ipady=4)

        label("2 · COMMENT DOIS-JE VOUS APPELER ?")
        self.name = entry(cfg.get("user_name", "Monsieur"))

        label("2 bis · VOTRE VILLE (météo) — vide = position automatique de l'ordinateur")
        self.city = entry(cfg.get("home_city", ""))

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
        trow = tk.Frame(f, bg=BG); trow.pack(fill="x", pady=(6, 0))
        self._btn(trow, "Tester ce micro", self.test_mic).pack(side="left")
        self.mic_status = tk.Label(trow, text="Enregistre 3 s puis te fait réécouter ta voix",
                                   fg=GREY, bg=BG, font=("Segoe UI", 9))
        self.mic_status.pack(side="left", padx=8)

        label("3 bis · TRANSCRIPTION DE LA VOIX")
        self.stts = [("auto", "Auto : Groq, et locale si pas d'internet ou quota épuisé"),
                     ("local", "Locale uniquement (rien n'est envoyé, puce IA ou processeur)"),
                     ("groq", "Groq uniquement (en ligne)")]
        self.stt = ttk.Combobox(f, values=[n for _, n in self.stts], state="readonly", style="J.TCombobox",
                                font=("Segoe UI", 10))
        self.stt.current(next((i for i, (c, _) in enumerate(self.stts) if c == cfg.get("stt_engine", "auto")), 0))
        self.stt.pack(fill="x", ipady=4)
        srow2 = tk.Frame(f, bg=BG); srow2.pack(fill="x", pady=(4, 0))
        self._btn(srow2, "Installer / tester la transcription locale", self.setup_local_stt).pack(side="left")
        self.stt_status = tk.Label(f, text="", fg=GREY, bg=BG, font=("Segoe UI", 9), anchor="w", wraplength=520,
                                   justify="left")
        self.stt_status.pack(fill="x")
        try:
            from . import stt_local
            if stt_local.ready():
                self.stt_status.config(text="Modèle local installé.", fg=GREEN)
        except Exception:
            pass

        label("4 · MUSIQUE — où lancer « mets du Dua Lipa »")
        self.services = [("youtube", "YouTube"), ("youtube_music", "YouTube Music"),
                         ("spotify", "Spotify (appli)"), ("deezer", "Deezer")]
        self.music = ttk.Combobox(f, values=[n for _, n in self.services], state="readonly",
                                  style="J.TCombobox", font=("Segoe UI", 10))
        self.music.current(next((k for k, (v, _) in enumerate(self.services)
                                 if v == cfg.get("music_service", "youtube")), 0))
        self.music.pack(fill="x", ipady=4)

        label("5 · VOIX DE JARVIS")
        self.voices = [("fr-FR-HenriNeural", "Henri (homme, défaut)"), ("fr-FR-RemyMultilingualNeural", "Rémy (homme)"),
                       ("fr-FR-DeniseNeural", "Denise (femme)"), ("fr-FR-VivienneMultilingualNeural", "Vivienne (femme)"),
                       ("en-GB-RyanNeural", "Ryan (anglais britannique, façon film)")]
        vrow = tk.Frame(f, bg=BG); vrow.pack(fill="x")
        self.voice = ttk.Combobox(vrow, values=[n for _, n in self.voices], state="readonly",
                                  style="J.TCombobox", font=("Segoe UI", 10))
        self.voice.current(next((k for k, (v, _) in enumerate(self.voices) if v == cfg.get("voice")), 0))
        self.voice.pack(side="left", fill="x", expand=True, ipady=4)
        self._btn(vrow, "Écouter", self.test_voice).pack(side="left", padx=(6, 0))

        label("6 · OPTIONS")
        self.autostart = tk.BooleanVar(value=cfg.get("_autostart", True))
        self.orb = tk.BooleanVar(value=cfg.get("show_idle_orb", True))
        self.conv = tk.BooleanVar(value=cfg.get("conversation_mode", True))
        self.duck = tk.BooleanVar(value=cfg.get("duck_music", True))
        self.brief = tk.BooleanVar(value=cfg.get("morning_briefing", True))
        for var, txt in ((self.autostart, "Lancer Jarvis au démarrage de Windows (en arrière-plan)"),
                         (self.orb, "Afficher l'orbe de veille en bas à droite"),
                         (self.conv, "Mode conversation : après une réponse, écouter la suite sans « Hey Jarvis »"),
                         (self.duck, "Mettre la musique en pause pendant que Jarvis m'écoute"),
                         (self.brief, "Briefing du matin (météo, rappels) au premier allumage entre 6 h et 11 h")):
            tk.Checkbutton(f, text=txt, variable=var, bg=BG, fg=WHITE, selectcolor=CARD, activebackground=BG,
                           activeforeground=WHITE, font=("Segoe UI", 10), anchor="w").pack(fill="x")
        srow = tk.Frame(f, bg=BG); srow.pack(fill="x", pady=(4, 0))
        tk.Label(srow, text="Sensibilité de « Hey Jarvis »", fg=WHITE, bg=BG, font=("Segoe UI", 10)).pack(side="left")
        self.sens = tk.Scale(srow, from_=1, to=10, orient="horizontal", bg=BG, fg=WHITE, troughcolor=CARD,
                             highlightthickness=0, length=200, showvalue=False)
        self.sens.set(round((0.75 - cfg.get("wake_threshold", 0.35)) / 0.06))
        self.sens.pack(side="right")

        label("7 · VIE PRIVÉE")
        self.logu = tk.BooleanVar(value=cfg.get("log_utterances", False))
        self.lockp = tk.BooleanVar(value=cfg.get("pause_when_locked", True))
        for var, txt in ((self.lockp, "Ne pas écouter quand la session Windows est verrouillée"),
                         (self.logu, "Journal détaillé : enregistrer mes phrases (pour le débogage)")):
            tk.Checkbutton(f, text=txt, variable=var, bg=BG, fg=WHITE, selectcolor=CARD, activebackground=BG,
                           activeforeground=WHITE, font=("Segoe UI", 10), anchor="w").pack(fill="x")
        tk.Label(f, justify="left", wraplength=500, fg=GREY, bg=BG, font=("Segoe UI", 9), anchor="w", text=(
            "• « Hey Jarvis » est détecté sur ce PC : rien n'est envoyé tant que Jarvis ne s'est pas réveillé.\n"
            "• Après le réveil, la phrase (audio) est envoyée à Groq pour être transcrite et comprise.\n"
            "• « Regarde mon écran » envoie une capture à Groq, seulement quand vous le demandez.\n"
            "• Votre clé est chiffrée par Windows (lisible seulement par votre compte sur ce PC).\n"
            "• Le journal est limité à 3 Mo et ne contient pas vos phrases, sauf si vous cochez la case.")
        ).pack(fill="x", pady=(4, 0))
        prow = tk.Frame(f, bg=BG); prow.pack(fill="x", pady=(6, 0))
        self._btn(prow, "Effacer le journal", self.clear_log, GREY).pack(side="left")
        self._btn(prow, "Ouvrir le dossier Jarvis", lambda: __import__("os").startfile(str(config.APP_DIR)), GREY
                  ).pack(side="left", padx=6)

        label("8 · VÉRIFICATION DU PC")
        self.diag = tk.Frame(f, bg=CARD); self.diag.pack(fill="x")
        threading.Thread(target=self.run_checks, daemon=True).start()

        tk.Frame(f, bg=BG, height=20).pack()
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

    def test_mic(self):
        """Enregistre 3 secondes avec le micro choisi puis les rejoue."""
        import numpy as np
        import sounddevice as sd
        dev = self.device()
        if self.stream:
            try: self.stream.close()
            except Exception: pass
            self.stream = None
        self.mic_status.config(text="● Parlez maintenant… (3 s)", fg=RED)

        def run():
            try:
                rec = sd.rec(int(3 * 16000), samplerate=16000, channels=1, dtype="int16", device=dev)
                sd.wait()
                peak = int(np.abs(rec).max())
                self.w.after(0, lambda: self.mic_status.config(text="▶ Réécoute…", fg=CYAN))
                sd.play(rec, 16000); sd.wait()
                if peak < 300:
                    msg, col = "✗ Presque rien capté : essayez un autre micro", RED
                else:
                    msg, col = "✓ Ce micro fonctionne", GREEN
            except Exception as e:
                msg, col = f"✗ Micro inutilisable ({e.__class__.__name__})", RED
            self.w.after(0, lambda: (self.mic_status.config(text=msg, fg=col), self.start_meter()))
        threading.Thread(target=run, daemon=True).start()

    def test_voice(self):
        v = self.voices[max(0, self.voice.current())][0]
        name = self.name.get().strip() or "Monsieur"
        def run():
            from .voice import Voice
            fake = type("V", (), {})()
            fake.cfg = dict(self.cfg, voice=v); fake.speaking = threading.Event(); fake.on_state = lambda *a: None
            try:
                Voice.speak(fake, f"Bonjour {name}. Je suis Jarvis, à votre service.")
            except Exception as e:
                self.w.after(0, lambda: self.mic_status.config(text=f"Voix indisponible : {e}", fg=RED))
        threading.Thread(target=run, daemon=True).start()

    def setup_local_stt(self):
        def run():
            from . import stt_local
            try:
                if not stt_local.ready():
                    stt_local.download(lambda p: self.w.after(0, lambda: self.stt_status.config(
                        text=f"Téléchargement du modèle Whisper (~75 Mo)… {int(p * 100)} %", fg=GREY)))
                eng = stt_local.engine_name()
                import time
                import numpy as np
                t0 = time.time()
                stt_local.transcribe_pcm(np.zeros(16000, dtype=np.int16))
                ms = int((time.time() - t0) * 1000)
                msg, col = f"✓ Transcription locale prête — moteur : {eng} — {ms} ms pour 1 s d'audio.", GREEN
            except Exception as e:
                msg, col = f"✗ Transcription locale indisponible : {e}", RED
            self.w.after(0, lambda: self.stt_status.config(text=msg, fg=col))
        threading.Thread(target=run, daemon=True).start()

    def test_planning(self):
        self.pstatus.config(text="Test en cours…", fg=GREY)

        def run():
            from . import assistant
            msg = assistant.planning_devoirs(dict(self.cfg, planning_key=self.pkey.get().strip()))
            bad = msg.startswith(("Planning partagé n'est", "Je n'arrive", "La clé", "Planning partagé ne"))
            self.w.after(0, lambda: self.pstatus.config(text=("✗ " if bad else "✓ ") + msg[:90], fg=RED if bad else GREEN))
        threading.Thread(target=run, daemon=True).start()

    def clear_log(self):
        import logging
        for h in logging.getLogger().handlers:
            try:
                h.flush(); h.stream.seek(0); h.stream.truncate()
            except Exception:
                pass
        for f in config.APP_DIR.glob("jarvis.log*"):
            try:
                if f.name != "jarvis.log":
                    f.unlink()
            except OSError:
                pass
        self.mic_status.config(text="Journal effacé.", fg=GREEN)

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

    def test_gemini(self):
        self.gem_status.config(text="Test Gemini en cours…", fg=GREY)
        raw = self.extra["gemini_api_key"].get()
        def run():
            from . import gemini
            try:
                ok, msg = gemini.check(raw)
            except Exception as e:
                ok, msg = False, f"✗ {e}"
            self.w.after(0, lambda: self.gem_status.config(text=msg, fg=GREEN if ok else RED))
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
            self.key_status.config(text="La clé Groq est nécessaire (elle sert aussi à comprendre votre voix).", fg=RED)
            return
        self.cfg.update(groq_api_key=self.key.get().strip(), user_name=self.name.get().strip() or "Monsieur",
                        input_device=self.device(), show_idle_orb=self.orb.get(),
                        music_service=self.services[max(0, self.music.current())][0],
                        voice=self.voices[max(0, self.voice.current())][0],
                        home_city=self.city.get().strip(),
                        log_utterances=self.logu.get(), pause_when_locked=self.lockp.get(),
                        conversation_mode=self.conv.get(), duck_music=self.duck.get(),
                        morning_briefing=self.brief.get(), planning_key=self.pkey.get().strip(),
                        stt_engine=self.stts[max(0, self.stt.current())][0],
                        language=self.langs[max(0, self.lang.current())][0],
                        personality=self.persos[max(0, self.perso.current())][0],
                        **{k: e.get().strip() for k, e in self.extra.items()},
                        wake_threshold=round(0.75 - self.sens.get() * 0.06, 2), _autostart=self.autostart.get())
        config.save(self.cfg)
        if self.stream:
            try: self.stream.close()
            except Exception: pass
        self.w.destroy()
        if self.on_done:
            self.on_done(True)
