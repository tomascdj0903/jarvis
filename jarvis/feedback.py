"""Rapports d'erreurs récurrentes, pour que Jarvis s'améliore tout seul.

Sur CHAQUE PC (même sans compte Claude) : quand une même erreur revient (outil qui échoue, phrase non
comprise, plantage), Jarvis la note dans %APPDATA%\\Jarvis\\a_corriger.jsonl puis envoie un rapport court et
anonyme (version, type d'erreur, phrase masquée) vers une table « boîte aux lettres » en écriture seule.
Chaque soir, une tâche planifiée Claude lit ces rapports, corrige le code, teste et publie la mise à jour :
tous les PC la reçoivent ensuite par la mise à jour automatique habituelle.
Désactivable dans Réglages → Vie privée.
"""
import datetime
import json
import re
import threading
import uuid

import requests

from . import __version__
from .config import APP_DIR

# Boîte aux lettres : la clé publique ne permet QUE d'ajouter un rapport (ni lire, ni modifier, ni effacer).
URL = "https://jkecsanrqktnrsibyiod.supabase.co/rest/v1/jarvis_reports"
KEY = "sb_publishable_mnU9TRTBIS00JvETusPPEA_yq-sE_Rq"

LOCAL = APP_DIR / "a_corriger.jsonl"
FAIL = re.compile(r"introuvable|je ne trouve pas|impossible|je n'arrive pas|je n'ai rien pu|n'existe pas|"
                  r"aucun(e)? .*trouv|refus|erreur|échec|n'ai pas pu|ne sais pas faire|je ne peux pas", re.I)
_lock = threading.Lock()


def mask(text: str) -> str:
    """Retire ce qui pourrait identifier quelqu'un : e-mails, numéros, liens, chemins personnels."""
    t = str(text or "")[:200]
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<email>", t)
    t = re.sub(r"https?://\S+", "<lien>", t)
    t = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", r"C:\\Users\\<moi>", t)
    t = re.sub(r"\d[\d .-]{3,}\d", "<nombre>", t)
    return t


def _signature(kind, detail):
    d = re.sub(r"« [^»]* »|\"[^\"]*\"|\d+", "…", str(detail).lower())
    return f"{kind}:{d[:100]}"


def _install_id(cfg):
    if not cfg.get("install_id"):
        cfg["install_id"] = uuid.uuid4().hex[:16]
        try:
            from . import config
            config.save(cfg)
        except Exception:
            pass
    return cfg["install_id"]


def record(cfg, kind, phrase, detail):
    """Note l'erreur ; l'envoie si elle revient (2e fois en 7 jours), une seule fois par jour et par erreur."""
    try:
        sig = _signature(kind, detail)
        now = datetime.datetime.now()
        with _lock:
            rows = []
            if LOCAL.exists():
                for line in LOCAL.read_text(encoding="utf-8").splitlines()[-500:]:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        pass
            week = [r for r in rows if r.get("sig") == sig and
                    now - datetime.datetime.fromisoformat(r["t"]) < datetime.timedelta(days=7)]
            sent_today = any(r.get("sent") and r["t"][:10] == now.isoformat()[:10] for r in week)
            send = (len(week) + 1 >= 2 or kind == "exception") and not sent_today and cfg.get("send_reports", True)
            rows.append({"t": now.isoformat(timespec="seconds"), "kind": kind, "sig": sig,
                         "phrase": mask(phrase), "detail": mask(detail)[:400], "sent": send})
            LOCAL.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows[-500:]) + "\n", encoding="utf-8")
        if send:
            body = {"install_id": _install_id(cfg), "version": __version__, "kind": kind, "signature": sig[:120],
                    "phrase": mask(phrase), "detail": mask(detail)[:400], "occurrences": len(week) + 1}
            threading.Thread(target=_post, args=(body,), daemon=True).start()
    except Exception:
        pass


def _post(body):
    try:
        requests.post(URL, json=body, timeout=10,
                      headers={"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "return=minimal"})
    except Exception:
        pass


def check_reply(cfg, phrase, reply):
    """Appelé après chaque réponse : une réponse d'échec devient un rapport (si elle se répète)."""
    if not reply:
        return
    if "rien pu faire" in reply or "pas certain de votre intention" in reply or "préciser" in reply.lower():
        record(cfg, "incompris", phrase, reply)
    elif FAIL.search(reply):
        record(cfg, "echec_outil", phrase, reply)
