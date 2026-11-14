"""HUD : petit réacteur animé en bas à droite, visible quand Jarvis écoute, analyse ou parle.
DA : nuit #03060C, cyan #29D8FF, or Stark #FFB547, plasma #E8FBFF."""
import math
import time
import queue
import tkinter as tk

BG = "#010203"  # rendue transparente
CYAN, GOLD, WHITE, DIM = "#29D8FF", "#FFB547", "#E8FBFF", "#12324A"


class HUD:
    SIZE = 170

    def __init__(self, root: tk.Tk, on_click=None, show_idle=True):
        self.root = root
        self.on_click = on_click
        self.show_idle = show_idle
        self.idle_until = 0
        self.q = queue.Queue()
        self.state, self.level, self.t, self.text = "idle", 0.0, 0.0, ""
        w = tk.Toplevel(root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=BG)
        try:
            w.attributes("-transparentcolor", BG)
        except tk.TclError:
            pass
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        self.W, self.H = 440, self.SIZE + 40
        w.geometry(f"{self.W}x{self.H}+{sw - self.W - 24}+{sh - self.H - 70}")
        self.c = tk.Canvas(w, width=self.W, height=self.H, bg=BG, highlightthickness=0)
        self.c.pack()
        self.c.bind("<Button-1>", lambda e: self.on_click and self.on_click())
        self.c.configure(cursor="hand2")
        self.win = w
        w.withdraw()
        self._tick()

    note, note_until = "", 0.0

    def notify(self, text, seconds=6):
        self.note, self.note_until = text, time.time() + seconds

    def set(self, state, level=0.0, text=None):
        self.q.put((state, level, text))

    def _tick(self):
        while not self.q.empty():
            s, lvl, txt = self.q.get()
            self.state, self.level = s, lvl
            if txt is not None:
                self.text = txt
        if self.state == "idle" and not self.show_idle:
            self.win.withdraw()
            self.text = ""
        elif self.state == "idle":
            self.text = ""
            self.win.deiconify()
            self._draw_idle()
        else:
            self.win.deiconify()
            self._draw()
        self.t += 0.06
        self.root.after(33, self._tick)

    def _draw_idle(self):
        """Petite orbe de veille : respire doucement, réagit au micro, clic = écouter."""
        c, t = self.c, self.t
        c.delete("all")
        cx, cy = self.W - self.SIZE // 2 - 6, self.SIZE // 2 + 4
        b = 0.5 + 0.5 * math.sin(t * 1.5)
        r = 16 + 4 * b + 12 * self.level
        c.create_oval(cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6, outline=CYAN, width=2)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#145E73", outline="")
        c.create_oval(cx - r * .55, cy - r * .55, cx + r * .55, cy + r * .55, fill=CYAN, outline="")
        if time.time() < self.note_until:  # message d'état / erreur temporaire
            right = cx - 40
            c.create_rectangle(4, cy - 30, right, cy + 30, fill="#06111D", outline=GOLD)
            c.create_text((right + 4) / 2, cy, text=self.note, fill=WHITE, font=("Segoe UI", 10),
                          width=right - 20, justify="center")

    def _draw(self):
        c, t = self.c, self.t
        c.delete("all")
        cx, cy = self.W - self.SIZE // 2 - 6, self.SIZE // 2 + 4
        if self.state == "listening":
            pulse = self.level
        elif self.state == "speaking":
            pulse = (0.5 + 0.5 * math.sin(t * 6)) * 0.6
        else:
            pulse = 0.25
        R = 72
        speed = 90 if self.state == "thinking" else 25
        for i in range(12):
            c.create_arc(cx - R, cy - R, cx + R, cy + R, start=i * 30 + t * speed, extent=20,
                         style="arc", outline=CYAN, width=6)
        R2 = 57
        c.create_arc(cx - R2, cy - R2, cx + R2, cy + R2, start=-t * (160 if self.state == "thinking" else 40),
                     extent=300, style="arc", outline=GOLD, width=3)
        for k, col in enumerate(("#0E3A4A", "#145E73", "#1FA9CC", CYAN, WHITE)):
            r = (42 - k * 7) * (0.8 + 0.4 * pulse)
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col, outline="")
        pts = []
        for k in range(3):
            a = math.radians(-90 + k * 120)
            pts += [cx + 26 * math.cos(a), cy + 26 * math.sin(a)]
        c.create_polygon(pts, outline="#03060C", fill="", width=3)
        label = {"listening": "À L'ÉCOUTE", "thinking": "ANALYSE…", "speaking": "J.A.R.V.I.S."}.get(self.state, "")
        c.create_text(cx, self.SIZE + 18, text=label, fill=CYAN, font=("Segoe UI Black", 10))
        if self.text:
            txt = self.text if len(self.text) < 110 else self.text[:107] + "…"
            right = cx - 84
            c.create_rectangle(4, cy - 34, right, cy + 34, fill="#06111D", outline=DIM)
            c.create_text((right + 4) / 2, cy, text=txt, fill=WHITE, font=("Segoe UI", 10),
                          width=right - 20, justify="center")
