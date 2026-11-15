"""Point d'entrée : écran de démarrage, icône de la barre système, boucle « Hey Jarvis »."""
import logging
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog

from . import actions, config
from .brain import Brain
from .hud import HUD

from logging.handlers import RotatingFileHandler
_h = RotatingFileHandler(config.LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_h])
log = logging.getLogger("jarvis")

STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup\Jarvis.lnk"
from .util import is_yes, has_wake_word, strip_wake_word, _privacy, session_locked  # noqa


# ---------- Écran de démarrage ----------
def splash(root, done):
    s = tk.Toplevel(root)
    s.overrideredirect(True)
    s.configure(bg="#03060C")
    W, H = 460, 340
    s.geometry(f"{W}x{H}+{(s.winfo_screenwidth()-W)//2}+{(s.winfo_screenheight()-H)//2}")
    s.attributes("-topmost", True)
    try:
        img = tk.PhotoImage(file=str(config.resource("assets/logo.png"))).subsample(3, 3)
        lbl = tk.Label(s, image=img, bg="#03060C"); lbl.image = img; lbl.pack(pady=(30, 10))
    except Exception:
        pass
    tk.Label(s, text="J.A.R.V.I.S.", fg="#E8FBFF", bg="#03060C", font=("Segoe UI Black", 22)).pack()
    bar = tk.Canvas(s, width=280, height=4, bg="#12324A", highlightthickness=0); bar.pack(pady=14)
    msg = tk.Label(s, text="INITIALISATION DES SYSTÈMES…", fg="#8FA8B8", bg="#03060C", font=("Segoe UI", 9))
    msg.pack()
    state = {"p": 0}

    def step():
        state["p"] = min(280, state["p"] + 7)
        bar.delete("all"); bar.create_rectangle(0, 0, state["p"], 4, fill="#29D8FF", width=0)
        if state["p"] < 280 or not done.is_set():
            s.after(30, step)
        else:
            s.destroy()
    step()
    return msg


# ---------- Startup Windows ----------
def set_autostart(enable: bool):
    if enable:
        target = sys.executable if getattr(sys, "frozen", False) else sys.executable.replace("python.exe", "pythonw.exe")
        args = "" if getattr(sys, "frozen", False) else f'-m jarvis'
        cwd = str(Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent)
        ps = (f'$s=(New-Object -ComObject WScript.Shell).CreateShortcut("{STARTUP_LNK}");'
              f'$s.TargetPath="{target}";$s.Arguments="{args}";$s.WorkingDirectory="{cwd}";$s.Save()')
        import subprocess
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=0x08000000)
    elif STARTUP_LNK.exists():
        STARTUP_LNK.unlink()


class Jarvis:
    def __init__(self):
        self.cfg = config.load()
        self.root = tk.Tk()
        self.root.withdraw()
        try:
            # default= : toutes les fenêtres (réglages, mise à jour, messages) prennent le logo Jarvis
            self.root.iconbitmap(default=str(config.resource("assets/jarvis.ico")))
        except Exception:
            pass
        self.hud = HUD(self.root, on_click=self.listen_now, show_idle=self.cfg.get("show_idle_orb", True))
        self.ready = threading.Event()
        self.running = True

    # ----- déclenchement manuel -----
    def listen_now(self):
        """Clic sur l'orbe / Ctrl+Alt+J : coupe Jarvis s'il parle, sinon l'écoute."""
        v = getattr(self, "voice", None)
        if not v:
            return
        if v.speaking.is_set():
            v.stop_speech.set()
        else:
            v.trigger.set()

    def hotkey_thread(self):
        """Raccourci global (Ctrl+Alt+J par défaut) via RegisterHotKey."""
        import ctypes
        from ctypes import wintypes
        mods = {"alt": 1, "ctrl": 2, "shift": 4, "win": 8}
        parts = self.cfg.get("hotkey", "ctrl+alt+j").lower().split("+")
        m = sum(mods.get(x, 0) for x in parts[:-1])
        key = ord(parts[-1].upper()) if len(parts[-1]) == 1 else 0x20
        if not ctypes.windll.user32.RegisterHotKey(None, 1, m | 0x4000, key):
            log.warning("raccourci %s indisponible", self.cfg.get("hotkey"))
            return
        msg = wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:
                self.listen_now()

    # ----- configuration -----
    def open_settings(self, first_run=False, then=None):
        from .settings import Wizard

        def done(saved):
            if saved:
                set_autostart(self.cfg.get("_autostart", True))
                self.hud.show_idle = self.cfg.get("show_idle_orb", True)
            if then:
                then(saved)
        Wizard(self.root, self.cfg, first_run=first_run, on_done=done)

    # ----- parole/écoute -----
    def on_state(self, state, level=0.0):
        if self.cfg.get("show_hud", True):
            self.hud.set(state, level)

    def say(self, text):
        log.info("JARVIS: %s", _privacy(text, self.cfg))
        self.hud.set("speaking", 0, text)
        self.voice.speak(text)

    def confirm(self, question) -> bool:
        self.say(question)
        self.voice.beep()
        ans = self.voice.listen().lower()
        ok = is_yes(ans)
        log.info("CONFIRM: %s", "oui" if ok else "non")
        return ok

    def loop(self):
        from .voice import Voice
        try:
            self.voice = Voice(self.cfg, self.on_state)
        except Exception as e:
            log.exception("voice init")
            self.hud.notify("Micro ou détecteur indisponible — voir le Journal", 30)
            self.root.after(0, lambda: messagebox.showerror("J.A.R.V.I.S.", f"Micro ou détecteur indisponible :\n{e}"))
            self.ready.set()
            return
        self.brain = Brain(self.cfg, self.say, self.confirm)
        from . import router as _r
        _r.route.confirm = self.confirm  # « clique sur… » demande toujours confirmation
        try:  # au démarrage : ne remplace le modèle que s'il n'existe plus
            model = self.brain.pick_model(keep=self.cfg.get("llm_model"))
            if model != self.cfg.get("llm_model"):
                log.info("modèle %s -> %s", self.cfg.get("llm_model"), model)
                self.cfg["llm_model"] = model
                config.save(self.cfg)
        except Exception as e:
            log.warning("pick_model: %s", e)
        threading.Thread(target=actions.scan_apps, daemon=True).start()
        from . import assistant
        assistant.start_scheduler(self.say, self.hud.notify)
        self.ready.set()
        threading.Thread(target=self.hotkey_thread, daemon=True).start()
        hk = self.cfg.get("hotkey", "ctrl+alt+j").upper()
        self.say(f"Systèmes en ligne. À votre service, {self.cfg['user_name']}.")
        self.hud.notify(f"Dites « Hey Jarvis », appuyez sur {hk} ou cliquez sur l'orbe", 10)
        fails, announced, follow_up = 0, False, False
        self._maybe_briefing()
        while self.running:
            try:
                if self.cfg.get("pause_when_locked", True) and session_locked():
                    import time as _t
                    while self.running and session_locked():
                        _t.sleep(2)  # personne ne doit commander un PC verrouillé
                    self._maybe_briefing()  # au déverrouillage du matin
                    continue
                if follow_up:  # mode conversation : on écoute la suite sans « Hey Jarvis »
                    how = "suite"
                    self.voice.preroll = []; self.voice.needs_verify = False
                else:
                    how = self.voice.wait_for_wake()
                score = self.voice.last_score
                log.info("réveil: %s (score %.2f)", how, score)
                follow_up = False
                ducked = self._duck() if self.cfg.get("duck_music", True) else False
                self.voice.beep()
                self.hud.set("listening", 0, "")
                try:
                    text = self.voice.listen(start_timeout=4.0 if how == "suite" else 5.0)
                finally:
                    if ducked and not getattr(self, "_keep_paused", False):
                        self._unduck()
                if how == "suite" and len(text) < 2:
                    self.hud.set("idle")
                    continue
                fails, announced = 0, False
                if how == "wake" and self.voice.needs_verify:
                    from .router import looks_like_command
                    if not has_wake_word(text) and not looks_like_command(text):
                        log.info("réveil incertain rejeté (pas de « Jarvis » entendu)")
                        self.hud.set("idle")
                        continue
                text = strip_wake_word(text)
                log.info("USER: %s", _privacy(text, self.cfg))
                if len(text) < 2:
                    self.hud.set("idle")
                    self.hud.notify("Je n'ai rien entendu.", 3)
                    continue
                self.hud.set("thinking", 0, text)
                from .router import route
                reply = route(text)  # commandes courantes : instantané, 0 token
                if reply is None:
                    reply = self.brain.ask(text)
                    # une question ou une discussion appelle souvent une suite : on réécoute brièvement
                    follow_up = self.cfg.get("conversation_mode", True) and (
                        reply.rstrip().endswith("?") or not any(k in reply.lower() for k in (
                            "lancé", "ouvert", "fermé", "réglé", "lecture", "pause", "minuteur")))
                else:
                    log.info("routeur local")
                self.say(reply)
                from . import feedback
                feedback.check_reply(self.cfg, text, reply)
            except Exception as e:
                import time as _t
                log.exception("loop")
                msg = str(e)
                try:
                    import traceback
                    from . import feedback
                    where = traceback.extract_tb(e.__traceback__)[-1]
                    feedback.record(self.cfg, "exception", "",
                                    f"{type(e).__name__}: {msg[:200]} @ {where.filename.split(chr(92))[-1]}:{where.lineno}")
                except Exception:
                    pass
                fails += 1
                audio = any(k in msg.lower() for k in ("portaudio", "device", "stream", "host error", "mme"))
                if "401" in msg:
                    self.say("Ma clé API semble invalide. Vérifiez-la dans les réglages.")
                elif "429" in msg:
                    self.say("Quota gratuit atteint pour le moment. Réessayez dans une minute.")
                elif audio:
                    if not announced:  # une seule annonce, puis réessais silencieux
                        self.hud.notify("Micro indisponible — je réessaie automatiquement", 15)
                        announced = True
                elif fails <= 2:
                    self.say("Désolé, un problème est survenu.")
                self.hud.set("idle")
                if not audio:
                    self.hud.notify(f"Erreur : {msg[:80]}", 8)
                _t.sleep(min(60, 2 ** min(fails, 6)))  # 2, 4, 8… 60 s : jamais de boucle folle

    def _rollback(self):
        from . import updater
        if not messagebox.askyesno("J.A.R.V.I.S.", "Revenir à la version précédente de Jarvis ?"):
            return
        if updater.rollback():
            self.running = False; self.root.destroy(); os._exit(0)
        messagebox.showinfo("J.A.R.V.I.S.", "Aucune version précédente disponible.")

    def _uninstall(self):
        from . import updater
        if not messagebox.askyesno("J.A.R.V.I.S.", "Désinstaller Jarvis ?\n\nSeront supprimés : le programme, vos "
                                   "réglages (clés comprises), le journal, le démarrage automatique et les raccourcis."):
            return
        updater.uninstall()
        self.running = False; self.root.destroy(); os._exit(0)

    def _maybe_briefing(self):
        """Briefing automatique, une fois par jour, au premier démarrage/déverrouillage entre 6 h et 11 h."""
        import datetime as _d
        now = _d.datetime.now()
        if not self.cfg.get("morning_briefing", True) or not 6 <= now.hour < 11:
            return
        if self.cfg.get("_last_briefing") == now.date().isoformat():
            return
        self.cfg["_last_briefing"] = now.date().isoformat()
        config.save(self.cfg)
        from . import assistant
        try:
            self.say(assistant.briefing(self.cfg.get("user_name", "")))
        except Exception:
            log.exception("briefing")

    # ----- musique baissée pendant l'écoute -----
    def _duck(self) -> bool:
        try:
            from . import media
            if any(p for _, _, _, p, _ in media.sessions()):
                return media.pause()
        except Exception:
            pass
        return False

    def _unduck(self):
        def run():
            import time as _t
            _t.sleep(0.3)
            try:
                from . import media
                media.play()
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    # ----- icône système -----
    def tray(self):
        import pystray
        from PIL import Image

        def pause(icon, item):
            self.voice.paused = not self.voice.paused

        def settings(icon, item):
            self.root.after(0, self.open_settings)

        def logs(icon, item):
            os.startfile(str(config.LOG_FILE))

        def autostart(icon, item):
            set_autostart(not STARTUP_LNK.exists())

        def toggle_orb(icon, item):
            self.hud.show_idle = not self.hud.show_idle
            self.cfg["show_idle_orb"] = self.hud.show_idle
            config.save(self.cfg)

        def rescan(icon, item):
            threading.Thread(target=actions.scan_apps, daemon=True).start()

        def quit_(icon, item):
            self.running = False
            icon.stop()
            self.root.after(0, self.root.destroy)

        menu = pystray.Menu(
            pystray.MenuItem("J.A.R.V.I.S. — dites « Hey Jarvis »", None, enabled=False),
            pystray.MenuItem("Écouter maintenant", lambda i, it: self.listen_now(), default=True),
            pystray.MenuItem("Afficher l'orbe de veille", toggle_orb, checked=lambda i: self.hud.show_idle),
            pystray.MenuItem("Micro en pause", pause,
                             checked=lambda i: getattr(getattr(self, "voice", None), "paused", False)),
            pystray.MenuItem("Lancer au démarrage", autostart, checked=lambda i: STARTUP_LNK.exists()),
            pystray.MenuItem("Réindexer les applications", rescan),
            pystray.MenuItem("Rechercher une mise à jour",
                             lambda i, it: threading.Thread(target=self.check_update, args=(True,), daemon=True).start()),
            pystray.MenuItem("Réglages…", settings),
            pystray.MenuItem("Revenir à la version précédente", lambda i, it: self.root.after(0, self._rollback)),
            pystray.MenuItem("Désinstaller Jarvis…", lambda i, it: self.root.after(0, self._uninstall)),
            pystray.MenuItem("Mes macros vocales…", lambda i, it: (__import__("jarvis.macros", fromlist=["load"]).load(),
                                                                os.startfile(str(config.APP_DIR / "macros.json")))),
            pystray.MenuItem("Journal", logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", quit_),
        )
        icon = pystray.Icon("jarvis", Image.open(config.resource("assets/tray.png")), "J.A.R.V.I.S.", menu)
        icon.run_detached()

    def check_update(self, manual=False):
        from . import updater, __version__
        info = updater.check()
        if not info:
            if manual:
                self.root.after(0, lambda: messagebox.showinfo("J.A.R.V.I.S.", f"Jarvis est à jour (v{__version__})."))
            return
        tag, url, notes = info

        def ask():
            if messagebox.askyesno("J.A.R.V.I.S. — mise à jour",
                                   f"Nouvelle version {tag} disponible (actuelle : v{__version__}).\n\n{notes}\n\nInstaller maintenant ?"):
                try:
                    if updater.install(url):
                        self.running = False
                        self.root.destroy()
                        os._exit(0)
                    else:
                        messagebox.showinfo("J.A.R.V.I.S.", "Mode script : relance INSTALLER JARVIS.bat après avoir téléchargé la nouvelle version.")
                except Exception as e:
                    messagebox.showerror("J.A.R.V.I.S.", f"Échec de la mise à jour :\n{e}")
        self.root.after(0, ask)

    def update_before_start(self) -> bool:
        """Vérifie les mises à jour avant de lancer quoi que ce soit. True = on quitte pour mettre à jour."""
        from . import updater, __version__
        info = updater.check()
        if not info or not getattr(sys, "frozen", False):
            return False
        tag, url, notes = info
        if not messagebox.askyesno("J.A.R.V.I.S. — mise à jour",
                                   f"Nouvelle version {tag} disponible (actuelle : v{__version__}).\n\n{notes}\n\n"
                                   "Installer maintenant ? Jarvis redémarrera tout seul."):
            return False
        w = tk.Toplevel(self.root)
        w.title("J.A.R.V.I.S."); w.configure(bg="#03060C"); w.attributes("-topmost", True)
        w.geometry(f"360x110+{(w.winfo_screenwidth()-360)//2}+{(w.winfo_screenheight()-110)//2}")
        lbl = tk.Label(w, text="Téléchargement de la mise à jour…", fg="#E8FBFF", bg="#03060C",
                       font=("Segoe UI", 11)); lbl.pack(pady=(22, 10))
        bar = tk.Canvas(w, width=300, height=6, bg="#12324A", highlightthickness=0); bar.pack()

        def prog(p):
            bar.delete("all"); bar.create_rectangle(0, 0, int(300 * p), 6, fill="#29D8FF", width=0)
            lbl.config(text=f"Téléchargement de la mise à jour… {int(p*100)} %")
            w.update()
        try:
            ok = updater.install(url, prog)
            lbl.config(text="Installation… Jarvis va redémarrer."); w.update()
            return ok
        except Exception as e:
            log.exception("update")
            messagebox.showerror("J.A.R.V.I.S.", f"Échec du téléchargement de la mise à jour :\n{e}")
            return False

    def start(self):
        splash(self.root, self.ready)
        threading.Thread(target=self.loop, daemon=True).start()
        self.tray()

    def run(self):
        try:
            from .updater import cleanup_temp
            threading.Thread(target=cleanup_temp, daemon=True).start()
        except Exception:
            pass
        if self.update_before_start():
            self.root.destroy()
            os._exit(0)
        if not self.cfg.get("groq_api_key"):
            self.open_settings(first_run=True,
                               then=lambda ok: self.start() if ok else (self.root.destroy(), os._exit(0)))
        else:
            self.start()
        self.root.mainloop()


def single_instance() -> bool:
    """Empêche deux Jarvis en même temps (un seul en arrière-plan)."""
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\JarvisAssistantMutex")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def selftest() -> int:
    """Jarvis.exe --selftest : vérifie que tout est bien embarqué (utilisé par GitHub à chaque version)."""
    out, ok = [], True
    def step(name, fn):
        nonlocal ok
        try:
            r = fn(); out.append(f"OK   {name} {r or ''}")
        except Exception as e:
            ok = False; out.append(f"FAIL {name}: {e!r}")
    from . import __version__
    step("version", lambda: __version__)
    step("assets", lambda: all(config.resource(f"assets/{f}").exists() for f in ("jarvis.ico", "logo.png", "tray.png")) or 1/0)
    step("numpy+sounddevice", lambda: __import__("sounddevice").__version__)
    step("edge_tts", lambda: __import__("edge_tts").__name__)
    step("uiautomation", lambda: __import__("uiautomation").GetRootControl().ClassName or "ok")
    step("pystray", lambda: __import__("pystray").__name__)
    def oww():
        from openwakeword.model import Model
        m = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        import numpy as np
        return f"score silence={max(m.predict(np.zeros(1280, dtype=np.int16)).values()):.3f}"
    step("openwakeword hey_jarvis", oww)
    step("chiffrement de la clé (DPAPI)", lambda: config._unprotect(config._protect("test")) == "test" or 1/0)
    step("architecture", lambda: ("ARM64 natif" if __import__("platform").machine().upper() == "ARM64" else
                                  __import__("platform").machine()) + (" sur PC ARM64" if __import__("jarvis.updater", fromlist=["x"]).native_arm64() else ""))
    step("moteurs ONNX (accélération)", lambda: ", ".join(__import__("jarvis.stt_local", fromlist=["x"]).providers()))
    step("dossiers Windows réels", lambda: config.known_folder("Documents"))
    step("contrôle média Windows (winrt)", lambda: f"{len(__import__('jarvis.media', fromlist=['sessions']).sessions())} session(s)")
    step("modules", lambda: [__import__(f"jarvis.{m}") for m in ("actions", "brain", "router", "settings", "updater", "hud", "voice", "util", "media", "vision", "gemini", "uiclick", "feedback", "weather", "macros", "assistant", "stt_local")] and "ok")
    step("routeur", lambda: __import__("jarvis.router", fromlist=["route"]).route("raconte une blague") is None or 1/0)
    offline = "--offline" in sys.argv
    try:  # test réseau réel (informatif, ne bloque pas la publication)
        if offline:
            raise RuntimeError("hors ligne")
        from .weather import weather
        out.append("INFO météo Nice demain : " + weather("Nice", "demain"))
        out.append("INFO météo position auto : " + weather("", "aujourd'hui"))
    except Exception as e:
        out.append(f"WARN météo : {e!r}")
    try:
        if offline:
            raise RuntimeError("hors ligne")
        from . import actions
        for q in ("nahar pnl", "naha pnl", "au dd pnl", "alors on dance stromae"):
            cq = actions.correct_query(q)
            vid = actions._youtube_id(cq + " audio")
            out.append(f"INFO musique « {q} » -> « {cq} » -> https://youtu.be/{vid}")
    except Exception as e:
        out.append(f"WARN musique : {e!r}")
    report = Path(sys.executable).parent / "selftest.txt"
    report.write_text("\n".join(out) + f"\nRESULT {'OK' if ok else 'FAIL'}\n", encoding="utf-8")
    return 0 if ok else 1


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(selftest())
    if len(sys.argv) >= 5 and sys.argv[1] == "--apply-update":
        from .updater import apply_update
        apply_update(*sys.argv[2:5])
        return
    try:  # icône Jarvis dans la barre des tâches (au lieu de celle de Python)
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Jarvis.Assistant")
    except Exception:
        pass
    from .updater import updating
    if updating():  # une mise à jour s'installe : ne surtout pas bloquer ses fichiers
        r = tk.Tk(); r.withdraw()
        messagebox.showinfo("J.A.R.V.I.S.", "Une mise à jour est en cours d'installation.\n"
                            "Jarvis redémarrera tout seul dans quelques secondes.")
        return
    if not single_instance():
        r = tk.Tk(); r.withdraw()
        try:
            r.iconbitmap(default=str(config.resource("assets/jarvis.ico")))
        except Exception:
            pass
        messagebox.showinfo("J.A.R.V.I.S.", "Jarvis tourne déjà en arrière-plan.\n"
                            "Dites « Hey Jarvis », Ctrl+Alt+J, ou clic droit sur l'icône près de l'horloge.")
        return
    Jarvis().run()


if __name__ == "__main__":
    main()
