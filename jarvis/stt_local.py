"""Transcription LOCALE (hors ligne, privée) : Whisper au format ONNX, sur Snapdragon comme sur Intel/AMD.

Accélération choisie automatiquement, de la plus rapide à la plus universelle :
  1. puce IA Qualcomm (QNN)       — si onnxruntime-qnn est présent (PC Snapdragon X)
  2. puce IA / iGPU Intel (OpenVINO) — si onnxruntime-openvino est présent (Intel Core Ultra)
  3. carte graphique (DirectML)   — si onnxruntime-directml est présent
  4. processeur (CPU), modèle quantifié int8 — fonctionne partout
Le modèle (~75 Mo) est téléchargé une seule fois dans %APPDATA%\\Jarvis\\models.
"""
import json
import threading
from pathlib import Path

import numpy as np

from . import config

REPO = "https://huggingface.co/onnx-community/whisper-base/resolve/main/"
FILES = {"encoder.onnx": "onnx/encoder_model_quantized.onnx",
         "decoder.onnx": "onnx/decoder_model_quantized.onnx",
         "vocab.json": "vocab.json"}
DIR = config.APP_DIR / "models" / "whisper-base"
SR, N_FFT, HOP, N_MELS, N_SAMPLES = 16000, 400, 160, 80, 480000
SOT, EOT, TRANSCRIBE, NO_TS = 50258, 50257, 50359, 50363
LANG = {"en": 50259, "de": 50261, "es": 50262, "fr": 50265, "pt": 50267, "it": 50274}
_lock = threading.Lock()
_state = {}


# ------------------------------------------------------------------ téléchargement
def ready() -> bool:
    return all((DIR / f).exists() for f in FILES)


def download(progress=lambda p: None):
    import requests
    DIR.mkdir(parents=True, exist_ok=True)
    for i, (name, path) in enumerate(FILES.items()):
        dst = DIR / name
        if dst.exists():
            continue
        tmp = dst.with_suffix(".part")
        with requests.get(REPO + path, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0)) or 1
            done = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    progress((i + done / total) / len(FILES))
        tmp.replace(dst)
    progress(1.0)


# ------------------------------------------------------------------ moteur
def providers():
    import onnxruntime as ort
    avail = ort.get_available_providers()
    order = ["QNNExecutionProvider", "OpenVINOExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"]
    return [p for p in order if p in avail]


def _load():
    if "enc" in _state:
        return _state
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    provs = providers()
    used = None
    for p in provs:  # on garde le premier accélérateur qui accepte le modèle
        try:
            enc = ort.InferenceSession(str(DIR / "encoder.onnx"), opts, providers=[p])
            dec = ort.InferenceSession(str(DIR / "decoder.onnx"), opts, providers=[p])
            used = p
            break
        except Exception:
            continue
    if used is None:
        raise RuntimeError("aucun moteur ONNX n'a pu charger Whisper")
    vocab = json.loads((DIR / "vocab.json").read_text(encoding="utf-8"))
    inv = {v: k for k, v in vocab.items()}
    _state.update(enc=enc, dec=dec, inv=inv, provider=used, mel=_mel_filters())
    return _state


def engine_name() -> str:
    names = {"QNNExecutionProvider": "puce IA Snapdragon (NPU)", "OpenVINOExecutionProvider": "puce IA Intel (OpenVINO)",
             "DmlExecutionProvider": "carte graphique (DirectML)", "CPUExecutionProvider": "processeur (int8)"}
    try:
        return names.get(_load()["provider"], "?")
    except Exception as e:
        return f"indisponible ({e})"


# ------------------------------------------------------------------ audio -> log-mel (identique à Whisper)
def _mel_filters():
    def hz_to_mel(f):
        f = np.asanyarray(f, dtype=np.float64)
        mels = f / (200.0 / 3)
        log_t = f >= 1000.0
        mels = np.where(log_t, 15.0 + np.log(np.maximum(f, 1e-10) / 1000.0) / (np.log(6.4) / 27.0), mels)
        return mels

    def mel_to_hz(m):
        m = np.asanyarray(m, dtype=np.float64)
        f = (200.0 / 3) * m
        log_t = m >= 15.0
        return np.where(log_t, 1000.0 * np.exp((np.log(6.4) / 27.0) * (m - 15.0)), f)

    fftfreqs = np.linspace(0, SR / 2, 1 + N_FFT // 2)
    mel_f = mel_to_hz(np.linspace(hz_to_mel(0.0), hz_to_mel(SR / 2), N_MELS + 2))
    fdiff = np.diff(mel_f)
    ramps = np.subtract.outer(mel_f, fftfreqs)
    w = np.zeros((N_MELS, len(fftfreqs)))
    for i in range(N_MELS):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        w[i] = np.maximum(0, np.minimum(lower, upper))
    enorm = 2.0 / (mel_f[2:N_MELS + 2] - mel_f[:N_MELS])
    return (w * enorm[:, None]).astype(np.float32)


def log_mel(audio: np.ndarray, mel) -> np.ndarray:
    audio = audio.astype(np.float32)
    audio = np.pad(audio[:N_SAMPLES], (0, max(0, N_SAMPLES - len(audio))))
    padded = np.pad(audio, (N_FFT // 2, N_FFT // 2), mode="reflect")
    win = np.hanning(N_FFT + 1)[:-1].astype(np.float32)
    n_frames = 1 + (len(padded) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    spec = np.abs(np.fft.rfft(padded[idx] * win, axis=1)) ** 2  # (frames, 201)
    spec = spec[:-1].T  # 3000 trames
    m = np.log10(np.maximum(mel @ spec, 1e-10))
    m = np.maximum(m, m.max() - 8.0)
    return ((m + 4.0) / 4.0).astype(np.float32)[None]  # (1, 80, 3000)


# ------------------------------------------------------------------ texte
_BYTE_DEC = None


def _bytes_decoder():
    global _BYTE_DEC
    if _BYTE_DEC is None:
        bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
        cs = bs[:]
        n = 0
        for b in range(256):
            if b not in bs:
                bs.append(b); cs.append(256 + n); n += 1
        _BYTE_DEC = {chr(c): b for b, c in zip(bs, cs)}
    return _BYTE_DEC


def _detok(ids, inv):
    dec = _bytes_decoder()
    text = "".join(inv.get(i, "") for i in ids if i < EOT)
    return bytearray(dec[c] for c in text if c in dec).decode("utf-8", errors="ignore").strip()


# ------------------------------------------------------------------ transcription
def transcribe_pcm(pcm16: np.ndarray, language="fr", max_tokens=96) -> str:
    """pcm16 : audio mono 16 kHz int16. Décodage glouton (rapide, suffisant pour des commandes)."""
    if not ready():
        raise RuntimeError("modèle local non téléchargé")
    with _lock:
        st = _load()
        feats = log_mel(pcm16.astype(np.float32) / 32768.0, st["mel"])
        enc_out = st["enc"].run(None, {st["enc"].get_inputs()[0].name: feats})[0]
        names = [i.name for i in st["dec"].get_inputs()]
        tokens = [SOT, LANG.get(language, LANG["fr"]), TRANSCRIBE, NO_TS]
        for _ in range(max_tokens):
            feed = {names[0]: np.array([tokens], dtype=np.int64)}
            feed[[n for n in names if "encoder" in n][0]] = enc_out
            logits = st["dec"].run(None, feed)[0]
            nxt = int(np.argmax(logits[0, -1]))
            if nxt == EOT:
                break
            tokens.append(nxt)
        return _detok(tokens[4:], st["inv"])


def transcribe_wav(wav: bytes, language="fr") -> str:
    import io
    import wave
    with wave.open(io.BytesIO(wav)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return transcribe_pcm(pcm, language)
