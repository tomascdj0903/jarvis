"""« Regarde mon écran » : capture l'écran et le fait analyser par un modèle de vision Groq (même clé)."""
import base64
import io

import requests

PREFERRED = ["meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"]


def _model(key):
    try:
        ids = {m["id"] for m in requests.get("https://api.groq.com/openai/v1/models", timeout=10,
                                             headers={"Authorization": f"Bearer {key}"}).json().get("data", [])}
        for m in PREFERRED:
            if m in ids:
                return m
        vis = [i for i in ids if "llama-4" in i or "vision" in i or "-vl" in i]
        if vis:
            return sorted(vis)[0]
    except Exception:
        pass
    return PREFERRED[0]


def capture_jpeg(max_w=1280, size_out=None) -> bytes:
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=False).convert("RGB")
    if size_out is not None:
        size_out.extend(img.size)
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


def look(question: str, cfg) -> str:
    key = cfg["groq_api_key"].strip()
    b64 = base64.b64encode(capture_jpeg()).decode()
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", timeout=40,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": _model(key), "max_tokens": 300, "messages": [{"role": "user", "content": [
                          {"type": "text", "text": "Voici une capture de l'écran de l'utilisateur. Réponds en français, "
                           "en 1 à 3 phrases courtes, sans markdown (ce sera lu à voix haute). Question : " + question},
                          {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]})
    if not r.ok:
        return f"Je n'arrive pas à analyser l'écran ({r.status_code})."
    return r.json()["choices"][0]["message"]["content"].strip()


def locate(target: str, cfg):
    """Demande au modèle de vision où se trouve « target » à l'écran. Renvoie (x, y) en pixels écran ou None."""
    import json
    import re
    key = cfg["groq_api_key"].strip()
    size = []
    b64 = base64.b64encode(capture_jpeg(size_out=size)).decode()
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", timeout=40,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": _model(key), "max_tokens": 80, "temperature": 0, "messages": [{"role": "user", "content": [
                          {"type": "text", "text": "Trouve l'élément cliquable suivant sur cette capture d'écran : « "
                           + target + " ». Réponds UNIQUEMENT en JSON : {\"found\": true/false, \"x\": 0-1000, "
                           "\"y\": 0-1000} où x et y sont le centre de l'élément en millièmes de la largeur/hauteur."},
                          {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]})
    if not r.ok:
        return None
    m = re.search(r"\{.*\}", r.json()["choices"][0]["message"]["content"], re.S)
    if not m:
        return None
    d = json.loads(m.group(0))
    if not d.get("found"):
        return None
    import ctypes
    u = ctypes.windll.user32
    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)  # coordonnées écran logiques
    return int(float(d["x"]) / 1000 * sw), int(float(d["y"]) / 1000 * sh)


def click_on(target: str, cfg, confirm) -> str:
    """Clique sur un élément décrit à voix haute (expérimental, toujours avec confirmation)."""
    import ctypes
    import time
    pos = locate(target, cfg)
    if not pos:
        return f"Je ne trouve pas « {target} » à l'écran."
    u = ctypes.windll.user32
    u.SetCursorPos(*pos)  # on montre d'abord où l'on va cliquer
    if not confirm(f"Je clique ici, sur {target} ?"):
        return "Clic annulé."
    u.SetCursorPos(*pos); time.sleep(0.05)
    u.mouse_event(0x0002, 0, 0, 0, 0); u.mouse_event(0x0004, 0, 0, 0, 0)
    return f"Clic sur {target}."
