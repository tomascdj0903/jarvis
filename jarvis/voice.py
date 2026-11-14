"""Oreilles et voix : mot d'activation (openWakeWord « hey jarvis », local),
enregistrement de la commande, transcription (Whisper via Groq), synthèse (edge-tts)."""
import asyncio
import ctypes
import io
import os
import tempfile
import threading
import time
import wave

import numpy as np
import requests
import sounddevice as sd

RATE = 16000
CHUNK = 1280  # 80 ms, format attendu par openWakeWord


class Voice:
    def __init__(self, cfg, on_state=lambda s, lvl=0: None):
        self.cfg = cfg
        self.on_state = on_state
        self.paused = False
        self.speaking = threading.Event()
        self.trigger = threading.Event()  # écoute forcée (raccourci / clic sur l'orbe)
        self.last_score = 0.0
        self.needs_verify = False
        from openwakeword.model import Model
        import openwakeword.utils
        try:
            openwakeword.utils.download_models(["hey_jarvis"])
        except Exception:
            pass
        self.oww = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")

    # ---------- écoute ----------
    def _open(self):
        return sd.InputStream(device=self.cfg.get("input_device"), samplerate=RATE, channels=1,
                              dtype="int16", blocksize=CHUNK)

    def wait_for_wake(self):
        """Bloque jusqu'à « Hey Jarvis » (ou déclenchement manuel).
        Garde le flux ouvert et les 1,5 dernières secondes : la commande dite d'une traite n'est pas perdue."""
        import collections
        self.oww.reset()
        self.trigger.clear()
        self.stream = self._open(); self.stream.start()
        ring = collections.deque(maxlen=int(1.5 * RATE / CHUNK))
        n, hot = 0, 0
        thr = self.cfg["wake_threshold"]
        while True:
            data, _ = self.stream.read(CHUNK)
            ring.append(data.copy())
            if self.trigger.is_set():
                self.trigger.clear(); self.preroll = []; self.needs_verify = False
                return "manual"
            if self.paused or self.speaking.is_set():
                continue
            score = max(self.oww.predict(data[:, 0]).values())
            self.last_score = max(self.last_score * 0.9, score)
            n += 1
            if n % 3 == 0:
                lvl = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
                self.on_state("idle", min(1.0, lvl / 3000))
            # déclenche sur un pic franc OU sur deux trames moyennement sûres d'affilée
            hot = hot + 1 if score >= thr * 0.6 else 0
            if score >= thr or hot >= 2:
                peak = max(score, self.last_score)
                # réveil incertain : on garde le mot de réveil dans l'audio pour le vérifier à la transcription
                self.needs_verify = peak < max(0.5, thr * 2)
                self.preroll = list(ring) if self.needs_verify else []
                return "wake"

    def record_command(self, max_s=9.0, silence_s=1.1) -> bytes:
        """Continue sur le MÊME flux micro (aucune coupure après le réveil), s'arrête au silence."""
        st = getattr(self, "stream", None)
        own = st is None
        if own:
            st = self._open(); st.start()
        frames = list(getattr(self, "preroll", []))
        silent, started = 0.0, False
        t0 = time.time()
        try:
            while time.time() - t0 < max_s:
                data, _ = st.read(CHUNK)
                frames.append(data.copy())
                lvl = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
                self.on_state("listening", min(1.0, lvl / 3000))
                if lvl > 450:
                    started, silent = True, 0.0
                else:
                    silent += CHUNK / RATE
                if started and silent >= silence_s:
                    break
                if not started and time.time() - t0 > 5:
                    break
        finally:
            try: st.stop(); st.close()
            except Exception: pass
            self.stream = None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(np.concatenate(frames).tobytes())
        return buf.getvalue()

    def transcribe(self, wav: bytes) -> str:
        def post(model):
            return requests.post("https://api.groq.com/openai/v1/audio/transcriptions", timeout=30,
                                 headers={"Authorization": f"Bearer {self.cfg['groq_api_key'].strip()}"},
                                 files={"file": ("cmd.wav", wav, "audio/wav")},
                                 data={"model": model, "language": self.cfg["language"], "temperature": "0",
                                       # vocabulaire attendu : aide Whisper sur les noms d'applis et d'artistes
                                       "prompt": "Jarvis, lance, mets, joue, ouvre, ferme, YouTube, YouTube Music, "
                                                 "Spotify, Deezer, Discord, Chrome, PNL, Ninho, Jul, SCH, Stromae, "
                                                 "Aya Nakamura, Dua Lipa, The Weeknd, musique suivante, volume."})
        r = post(self.cfg["stt_model"])
        if r.status_code in (400, 404) and "model" in r.text.lower():
            for alt in ("whisper-large-v3-turbo", "whisper-large-v3"):
                if alt != self.cfg["stt_model"]:
                    r = post(alt)
                    if r.ok:
                        self.cfg["stt_model"] = alt
                        break
        if r.status_code >= 400:
            raise RuntimeError(f"Transcription {r.status_code} : {r.text[:150]}")
        return r.json().get("text", "").strip()

    HALLU = ("sous-titrage", "sous titrage", "radio-canada", "radio canada", "amara.org", "merci d'avoir regardé",
             "sous-titres réalisés", "abonnez-vous", "st' 501", "sous-titres par", "♪")

    def listen(self) -> str:
        wav = self.record_command()
        pcm = np.frombuffer(wav[44:], dtype=np.int16)
        if pcm.size == 0 or float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) < 120:
            return ""  # silence : on n'envoie rien (évite les phrases inventées par Whisper)
        text = self.transcribe(wav)
        if any(h in text.lower() for h in self.HALLU):
            return ""
        return text

    # ---------- parole ----------
    def speak(self, text: str):
        import edge_tts
        self.speaking.set()
        self.on_state("speaking")
        try:
            path = os.path.join(tempfile.gettempdir(), f"jarvis_{int(time.time()*1000)}.mp3")
            try:
                asyncio.run(edge_tts.Communicate(text, self.cfg["voice"], rate="+5%").save(path))
                _play_mp3(path)
            except Exception:
                _speak_windows(text)  # voix Windows hors ligne
            try:
                os.remove(path)
            except OSError:
                pass
        finally:
            self.speaking.clear()
            self.on_state("idle")

    def beep(self):
        """Bip en arrière-plan : on n'attend pas la fin du son pour écouter."""
        def run():
            try:
                import winsound
                winsound.Beep(1320, 60); winsound.Beep(1760, 80)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()


def _play_mp3(path):
    """Lecture via l'API MCI de Windows (aucune dépendance)."""
    mci = ctypes.windll.winmm.mciSendStringW
    mci(f'open "{path}" type mpegvideo alias jv', None, 0, None)
    mci("play jv wait", None, 0, None)
    mci("close jv", None, 0, None)


def _speak_windows(text):
    import subprocess
    t = text.replace("'", "''")
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Add-Type -AssemblyName System.Speech;"
                    f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{t}')"],
                   creationflags=0x08000000)
