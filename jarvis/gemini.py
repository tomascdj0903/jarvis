"""Client Gemini « natif » (même méthode que le bot GlobalExam).

- Les nouvelles clés « AQ.… » ne sont acceptées QUE dans l'en-tête x-goog-api-key, sur l'API REST
  native (pas sur l'endpoint compatible OpenAI avec « Authorization: Bearer »).
- Les nouveaux comptes gratuits n'ont plus toujours accès à gemini-2.5 : on lit la liste des modèles
  de la clé et on construit une chaîne (Flash-Lite d'abord = gros quota gratuit, puis Flash).
  Quand un modèle est refusé ou que son quota du jour est épuisé, on passe au suivant.
- Plusieurs clés possibles (séparées par une virgule ou un espace) : rotation si l'une est saturée.
"""
import json
import re
import time
import uuid

import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"
FALLBACK = ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.5-flash",
            "gemini-2.0-flash"]

_chains = {}        # clé -> liste ordonnée de modèles
_dead = {}          # (clé, modèle) -> heure jusqu'à laquelle on l'évite
_no_think = set()   # modèles qui refusent thinkingConfig
LAST = {"model": ""}  # dernier modèle qui a répondu
_signatures = {}    # id d'appel d'outil -> thoughtSignature (obligatoire à renvoyer pour Gemini 3)


class GeminiError(Exception):
    pass


def keys(raw) -> list:
    return [k for k in re.split(r"[\s,;]+", (raw or "").strip()) if k]


def looks_like_key(k: str) -> bool:
    return k.startswith(("AIza", "AQ."))


def _h(key):
    return {"x-goog-api-key": key, "Content-Type": "application/json"}


def models(key) -> list:
    """Chaîne de modèles utilisables avec cette clé (en cache)."""
    if key in _chains:
        return _chains[key]
    try:
        r = requests.get(f"{BASE}/models?pageSize=1000", headers=_h(key), timeout=15)
        names = [m["name"].split("/", 1)[-1] for m in r.json().get("models", [])
                 if "generateContent" in (m.get("supportedGenerationMethods") or [])] if r.ok else []
    except Exception:
        names = []
    if not names:
        return list(FALLBACK)  # pas mis en cache : on réessaiera la liste la prochaine fois

    def ranked(lite):
        pat = re.compile(r"^gemini-(\d+(?:\.\d+)?)-flash" + (r"-lite" if lite else r"(?!-lite)")
                         + r"(-latest|-preview[\w-]*|-\d+)?$")
        found = []
        for n in names:
            m = pat.match(n)
            if not m or any(x in n for x in ("image", "tts", "live", "audio")):
                continue
            stable = 0 if (m.group(2) or "").startswith("-preview") else 1
            found.append((stable, float(m.group(1)), 0 if m.group(2) else 1, n))
        return [f[3] for f in sorted(found, reverse=True)]

    alias = [n for n in ("gemini-flash-lite-latest", "gemini-flash-latest") if n in names]
    chain = list(dict.fromkeys(alias[:1] + ranked(True) + alias[1:] + ranked(False)))
    _chains[key] = chain or list(FALLBACK)
    return _chains[key]


# ---------- conversion format OpenAI <-> Gemini ----------
def _schema(p):
    out = {k: v for k, v in p.items() if k in ("type", "description", "enum", "items", "properties", "required")}
    if "properties" in out:
        out["properties"] = {k: _schema(v) for k, v in out["properties"].items()}
    if "items" in out:
        out["items"] = _schema(out["items"])
    return out


def _tools(tools):
    decl = []
    for t in tools or []:
        f = t["function"]
        d = {"name": f["name"], "description": f.get("description", "")}
        params = f.get("parameters") or {}
        if params.get("properties"):
            d["parameters"] = _schema(params)
        decl.append(d)
    return [{"functionDeclarations": decl}] if decl else None


def _image_part(url):
    m = re.match(r"data:([^;]+);base64,(.+)", url, re.S)
    return {"inline_data": {"mime_type": m.group(1), "data": m.group(2)}} if m else {"text": url}


def _contents(messages):
    system, contents, names = [], [], {}
    for msg in messages:
        role, content = msg.get("role"), msg.get("content")
        if role == "system":
            system.append(content if isinstance(content, str) else "")
            continue
        if role == "tool":
            part = {"functionResponse": {"name": names.get(msg.get("tool_call_id"), "outil"),
                                         "response": {"result": str(content)}}}
            if contents and contents[-1]["role"] == "user" and "functionResponse" in contents[-1]["parts"][0]:
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
            continue
        parts = []
        if isinstance(content, list):
            for c in content:
                if c.get("type") == "text":
                    parts.append({"text": c["text"]})
                elif c.get("type") == "image_url":
                    parts.append(_image_part(c["image_url"]["url"]))
        elif content:
            parts.append({"text": content})
        for call in msg.get("tool_calls") or []:
            fn = call["function"]
            names[call["id"]] = fn["name"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            p = {"functionCall": {"name": fn["name"], "args": args}}
            # Gemini 3 exige une signature sur chaque appel d'outil de l'historique ; pour ceux faits par
            # un autre modèle (Groq), Google prévoit cette valeur spéciale qui saute la vérification.
            p["thoughtSignature"] = _signatures.get(call["id"], "skip_thought_signature_validator")
            parts.append(p)
        if parts:
            contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
    return "\n\n".join(system), contents


def _to_openai(data):
    cand = (data.get("candidates") or [{}])[0]
    text, calls = "", []
    for p in (cand.get("content") or {}).get("parts") or []:
        if p.get("thought"):
            continue
        if "functionCall" in p:
            cid = "call_" + uuid.uuid4().hex[:12]
            if p.get("thoughtSignature"):
                _signatures[cid] = p["thoughtSignature"]
            calls.append({"id": cid, "type": "function", "function": {
                "name": p["functionCall"]["name"], "arguments": json.dumps(p["functionCall"].get("args") or {})}})
        elif "text" in p:
            text += p["text"]
    msg = {"role": "assistant", "content": text.strip()}
    if calls:
        msg["tool_calls"] = calls
    return msg


# ---------- appel ----------
def _body(model, system, contents, tools, temperature, max_tokens):
    cfg = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if model not in _no_think:
        if model.startswith("gemini-3"):
            cfg["thinkingConfig"] = {"thinkingLevel": "low"}       # rapide : c'est un assistant vocal
        elif "2.5-flash" in model:
            cfg["thinkingConfig"] = {"thinkingBudget": 0}
    body = {"contents": contents, "generationConfig": cfg}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    t = _tools(tools)
    if t:
        body["tools"] = t
    return body


def _explain(code, text):
    low = text.lower()
    if code == 402 or "prepay" in low or "credits" in low:
        return "402 : crédits prépayés épuisés sur le projet de cette clé (projet facturé) — crée la clé dans un projet sans facturation"
    if code in (400, 401, 403) and ("api key" in low or "api_key" in low or "permission" in low or code == 401):
        return f"{code} : clé Gemini refusée"
    if code == 429:
        return "429 : quota Gemini atteint" + (" pour aujourd'hui" if "perday" in low.replace("_", "") else "")
    return f"{code} : {text[:120]}"


def chat(raw_keys, messages, tools=None, temperature=0.4, max_tokens=250, timeout=30):
    """Renvoie un message au format OpenAI ({content, tool_calls?}). Essaie chaque clé, chaque modèle."""
    ks = keys(raw_keys)
    if not ks:
        raise GeminiError("aucune clé Gemini")
    system, contents = _contents(messages)
    errors = []
    for key in ks:
        for model in models(key):
            if _dead.get((key, model), 0) > time.time():
                continue
            body = _body(model, system, contents, tools, temperature, max_tokens)
            r = requests.post(f"{BASE}/models/{model}:generateContent", headers=_h(key), json=body, timeout=timeout)
            if not r.ok and r.status_code == 400 and "thinking" in r.text.lower():
                _no_think.add(model)
                body = _body(model, system, contents, tools, temperature, max_tokens)
                r = requests.post(f"{BASE}/models/{model}:generateContent", headers=_h(key), json=body, timeout=timeout)
            if r.ok:
                LAST["model"] = model
                return _to_openai(r.json())
            why = _explain(r.status_code, r.text)
            errors.append(f"{model} {why}")
            if r.status_code == 402 or why.endswith("clé Gemini refusée"):
                break                                     # inutile d'essayer les autres modèles avec cette clé
            if r.status_code == 429:
                _dead[(key, model)] = time.time() + (3600 if "aujourd'hui" in why else 60)
            elif r.status_code in (403, 404):
                _dead[(key, model)] = time.time() + 86400  # modèle non ouvert à ce compte
    raise GeminiError(errors[-1] if errors else "aucun modèle Gemini disponible")


def check(raw_keys) -> tuple:
    """Pour le bouton « Tester » des Réglages : (ok, message)."""
    ks = keys(raw_keys)
    if not ks:
        return False, "✗ Aucune clé"
    bad = [k for k in ks if not looks_like_key(k)]
    if bad:
        return False, "✗ Une clé ne ressemble pas à une clé Gemini (elle commence par « AIza » ou « AQ. »)"
    out = []
    for i, k in enumerate(ks, 1):
        _chains.pop(k, None)
        try:
            chat(k, [{"role": "user", "content": "Réponds juste : OK"}], max_tokens=10, timeout=20)
            out.append((True, f"clé {i} ✓ {LAST['model']}"))
        except Exception as e:
            out.append((False, f"clé {i} ✗ {e}"))
    ok = all(o for o, _ in out)
    return ok, ("✓ " if ok else "") + " · ".join(t for _, t in out)
