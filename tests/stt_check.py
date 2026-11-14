"""Test réel de la transcription locale (lancé par GitHub sur Windows x64 et ARM64).
Une phrase est synthétisée par la voix Windows en WAV 16 kHz, puis transcrite hors ligne."""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis import stt_local  # noqa: E402

PHRASE = "Please turn on the music and open the weather forecast."
wav = os.path.join(tempfile.gettempdir(), "stt_test.wav")
ps = ("Add-Type -AssemblyName System.Speech;"
      "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
      "$f=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono);"
      f"$s.SetOutputToWaveFile('{wav}',$f);$s.Speak('{PHRASE}');$s.Dispose()")
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
stt_local.download()
print("moteurs disponibles :", stt_local.providers())
print("moteur utilisé      :", stt_local.engine_name())
t0 = time.time()
text = stt_local.transcribe_wav(open(wav, "rb").read(), "en")
dt = time.time() - t0
print(f"transcription ({dt:.2f} s) : {text!r}")
low = text.lower()
hits = sum(w in low for w in ("music", "weather", "turn", "open", "forecast"))
assert hits >= 4, f"transcription locale trop mauvaise ({hits}/5 mots)"
print("STT LOCAL OK")
