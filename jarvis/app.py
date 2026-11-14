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

logging.basicConfig(filename=config.LOG_FILE, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
log = logging.getLogger("jarvis")

STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup\Jarvis.lnk"
YES = ("oui", "ouais", "confirme", "vas-y", "vas y", "ok", "d'accord", "affirmatif", "yes")


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
            self.root.iconbitmap(str(config.resource("assets/jarvis.ico")))
        except Exception:
            pass
        self.hud = HUD(self.root)
        self.ready = threading.Event()
        self.running = True

    # ----- première configuration -----
    def ensure_key(self):
        if self.cfg.get("groq_api_key"):
            return True
        messagebox.showinfo("J.A.R.V.I.S.",
                            "Bienvenue. Il me faut une clé API Groq gratuite.\n\n"
                            "1. Va sur console.groq.com et connecte-toi\n"
                            "2. API Keys > Create API Key\n"
                            "3. Colle la clé dans la fenêtre suivante.")
        key = simpledialog.askstring("J.A.R.V.I.S.", "Clé API Groq :", parent=self.root)
        if not key:
            return False
        name = simpledialog.askstring("J.A.R.V.I.S.", "Comment dois-je vous appeler ?",
                                      initialvalue="Monsieur", parent=self.root) or "Monsieur"
        self.cfg.update(groq_api_key=key.strip(), user_name=name.strip())
        config.save(self.cfg)
        if messagebox.askyesno("J.A.R.V.I.S.", "Lancer Jarvis automatiquement au démarrage de Windows ?"):
            set_autostart(True)
        return True

    # ----- parole/écoute -----
    def on_state(self, state, level=0.0):
        if self.cfg.get("show_hud", True):
            self.hud.set(state, level)

    def say(self, text):
        log.info("JARVIS: %s", text)
        self.hud.set("speaking", 0, text)
        self.voice.speak(text)

    def confirm(self, question) -> bool:
        self.say(question)
        self.voice.beep()
        ans = self.voice.listen().lower()
        log.info("CONFIRM: %s", ans)
        return any(w in ans for w in YES)

    def loop(self):
        from .voice import Voice
        try:
            self.voice = Voice(self.cfg, self.on_state)
        except Exception as e:
            log.exception("voice init")
            self.root.after(0, lambda: messagebox.showerror("J.A.R.V.I.S.", f"Micro ou détecteur indisponible :\n{e}"))
            self.ready.set()
            return
        self.brain = Brain(self.cfg, self.say, self.confirm)
        threading.Thread(target=actions.scan_apps, daemon=True).start()
        self.ready.set()
        self.say(f"Systèmes en ligne. À votre service, {self.cfg['user_name']}.")
        while self.running:
            try:
                self.voice.wait_for_wake()
                self.voice.beep()
                self.hud.set("listening", 0, "")
                text = self.voice.listen()
                log.info("USER: %s", text)
                if len(text) < 2:
                    self.hud.set("idle")
                    continue
                self.hud.set("thinking", 0, text)
                reply = self.brain.ask(text)
                self.say(reply)
            except Exception as e:
                log.exception("loop")
                msg = str(e)
                if "401" in msg:
                    self.say("Ma clé API semble invalide. Vérifiez-la dans les réglages.")
                elif "429" in msg:
                    self.say("Quota gratuit atteint pour le moment. Réessayez dans une minute.")
                else:
                    self.say("Désolé, un problème est survenu.")
                self.hud.set("idle")

    # ----- icône système -----
    def tray(self):
        import pystray
        from PIL import Image

        def pause(icon, item):
            self.voice.paused = not self.voice.paused

        def settings(icon, item):
            os.startfile(str(config.CONFIG_FILE))

        def logs(icon, item):
            os.startfile(str(config.LOG_FILE))

        def autostart(icon, item):
            set_autostart(not STARTUP_LNK.exists())

        def rescan(icon, item):
            threading.Thread(target=actions.scan_apps, daemon=True).start()

        def quit_(icon, item):
            self.running = False
            icon.stop()
            self.root.after(0, self.root.destroy)

        menu = pystray.Menu(
            pystray.MenuItem("J.A.R.V.I.S. — dites « Hey Jarvis »", None, enabled=False),
            pystray.MenuItem("Micro en pause", pause,
                             checked=lambda i: getattr(getattr(self, "voice", None), "paused", False)),
            pystray.MenuItem("Lancer au démarrage", autostart, checked=lambda i: STARTUP_LNK.exists()),
            pystray.MenuItem("Réindexer les applications", rescan),
            pystray.MenuItem("Rechercher une mise à jour",
                             lambda i, it: threading.Thread(target=self.check_update, args=(True,), daemon=True).start()),
            pystray.MenuItem("Réglages (config.json)", settings),
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
                    else:
                        messagebox.showinfo("J.A.R.V.I.S.", "Mode script : relance INSTALLER JARVIS.bat après avoir téléchargé la nouvelle version.")
                except Exception as e:
                    messagebox.showerror("J.A.R.V.I.S.", f"Échec de la mise à jour :\n{e}")
        self.root.after(0, ask)

    def run(self):
        if not self.ensure_key():
            return
        threading.Thread(target=self.check_update, daemon=True).start()
        splash(self.root, self.ready)
        threading.Thread(target=self.loop, daemon=True).start()
        self.tray()
        self.root.mainloop()


def main():
    Jarvis().run()


if __name__ == "__main__":
    main()
