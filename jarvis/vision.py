"""« Regarde mon écran » : capture l'écran et le fait analyser par un modèle de vision Groq (même clé)."""
import base64
import io

import requests

PREFERRED = ["meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"]


def _model(key):
    """Un modèle Groq qui voit les images, ou None s'il n'y en a plus."""
    try:
        data = requests.get("https://api.groq.com/openai/v1/models", timeout=10,
                            headers={"Authorization": f"Bearer {key}"}).json().get("data", [])
        ids = {m["id"] for m in data if m.get("active", True)}
        for m in PREFERRED:
            if m in ids:
                return m
        vis = [i for i in ids if any(k in i.lower() for k in ("llama-4", "vision", "-vl", "scout", "maverick", "llava"))]
        if vis:
            return sorted(vis)[0]
    except Exception:
        pass
    return None


def _ask_image(cfg, prompt, b64, max_tokens=300):
    """Envoie image + question : Groq si un modèle de vision existe, sinon Gemini (clé de secours)."""
    msg = [{"role": "user", "content": [{"type": "text", "text": prompt},
                                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
    tries = []
    gk = (cfg.get("groq_api_key") or "").strip()
    gm = _model(gk) if gk else None
    if gm:
        tries.append(("https://api.groq.com/openai/v1/chat/completions", gk, gm))
    ge = (cfg.get("gemini_api_key") or "").strip()
    if ge:
        for m in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"):
            tries.append(("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", ge, m))
    if not tries:
        raise RuntimeError("aucun modèle de vision disponible : ajoutez une clé Gemini (gratuite) dans les Réglages")
    last = None
    for url, key, model in tries:
        r = requests.post(url, timeout=40, headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "max_tokens": max_tokens, "temperature": 0, "messages": msg})
        if r.ok:
            return r.json()["choices"][0]["message"]["content"].strip()
        last = f"{r.status_code}"
    raise RuntimeError(f"analyse d'image refusée ({last})")


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
    b64 = base64.b64encode(capture_jpeg()).decode()
    try:
        return _ask_image(cfg, "Voici une capture de l'écran de l'utilisateur. Réponds en français, en 1 à 3 phrases "
                          "courtes, sans markdown (ce sera lu à voix haute). Question : " + question, b64)
    except Exception as e:
        return f"Je n'arrive pas à analyser l'écran : {e}."


def locate(target: str, cfg):
    """Demande au modèle de vision où se trouve « target » à l'écran. Renvoie (x, y) en pixels écran ou None."""
    import json
    import re
    size = []
    b64 = base64.b64encode(capture_jpeg(size_out=size)).decode()
    try:
        txt = _ask_image(cfg, "Trouve l'élément cliquable suivant sur cette capture d'écran : « " + target +
                         " ». Réponds UNIQUEMENT en JSON : {\"found\": true/false, \"x\": 0-1000, \"y\": 0-1000} où x et y "
                         "sont le centre de l'élément en millièmes de la largeur/hauteur.", b64, 80)
    except Exception:
        return None
    m = re.search(r"\{.*\}", txt, re.S)
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
