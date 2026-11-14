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
        from openwakeword.model import Model
        import openwakeword.utils
        try:
            openwakeword.utils.download_models(["hey_jarvis"])
        except Exception:
            pass
        self.oww = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")

    # ---------- écoute ----------
    def wait_for_wake(self):
        """Bloque jusqu'à « Hey/OK Jarvis »."""
        self.oww.reset()
        with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK) as st:
            while True:
                data, _ = st.read(CHUNK)
                if self.paused or self.speaking.is_set():
                    continue
                scores = self.oww.predict(data[:, 0])
                if max(scores.values()) >= self.cfg["wake_threshold"]:
                    return

    def record_command(self, max_s=8.0, silence_s=1.0) -> bytes:
        """Enregistre jusqu'à un silence ; renvoie un WAV."""
        frames, silent, started = [], 0.0, False
        t0 = time.time()
        with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK) as st:
            while time.time() - t0 < max_s:
                data, _ = st.read(CHUNK)
                frames.append(data.copy())
                lvl = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
                self.on_state("listening", min(1.0, lvl / 3000))
                if lvl > 500:
                    started, silent = True, 0.0
                else:
                    silent += CHUNK / RATE
                if started and silent >= silence_s:
                    break
                if not started and time.time() - t0 > 4:
                    break
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(np.concatenate(frames).tobytes())
        return buf.getvalue()

    def transcribe(self, wav: bytes) -> str:
        r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions", timeout=30,
                          headers={"Authorization": f"Bearer {self.cfg['groq_api_key']}"},
                          files={"file": ("cmd.wav", wav, "audio/wav")},
                          data={"model": self.cfg["stt_model"], "language": self.cfg["language"]})
        r.raise_for_status()
        return r.json().get("text", "").strip()

    def listen(self) -> str:
        return self.transcribe(self.record_command())

    # ---------- parole ----------
    def speak(self, text: str):
        import edge_tts
        self.speaking.set()
        self.on_state("speaking")
        try:
            path = os.path.join(tempfile.gettempdir(), f"jarvis_{int(time.time()*1000)}.mp3")
            asyncio.run(edge_tts.Communicate(text, self.cfg["voice"], rate="+5%").save(path))
            _play_mp3(path)
            try:
                os.remove(path)
            except OSError:
                pass
        finally:
            self.speaking.clear()
            self.on_state("idle")

    def beep(self):
        try:
            import winsound
            winsound.Beep(1320, 70); winsound.Beep(1760, 90)
        except Exception:
            pass


def _play_mp3(path):
    """Lecture via l'API MCI de Windows (aucune dépendance)."""
    mci = ctypes.windll.winmm.mciSendStringW
    mci(f'open "{path}" type mpegvideo alias jv', None, 0, None)
    mci("play jv wait", None, 0, None)
    mci("close jv", None, 0, None)
