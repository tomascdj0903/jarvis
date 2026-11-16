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

# Ce que Jarvis a fait pendant l'échange précédent (outils, clics…), pour comprendre une plainte.
COMPLAINT = re.compile(
    r"\b(tu (n'?as|as) pas|t'?as pas|tu n'?as rien|t'?as rien) (clique|lance|ouvert|ferme|fait|compris|mis|trouve|joue|cherche|"
    r"affiche|tape|selectionne)|\b(c'?est|ce n'?est) pas (ca|ce que|la bonne|le bon|celle|celui)|\brien a voir\b|"
    r"\btu t'?es trompe|\bmauvais(e)? (musique|video|fenetre|page|appli|application|endroit|bouton|titre|chanson)|"
    r"\bca (n'?a pas|a pas) marche|\bca (ne )?marche pas\b|\bnon,? (pas ca|c'?est pas|tu as|t'as)|\bt'?as (clique|lance|ouvert) (a cote|n'importe)")


class _Recent:
    """Garde les lignes du journal de l'échange en cours et du précédent."""
    def __init__(self):
        self.current, self.previous = [], []

    def add(self, msg):
        if msg.startswith("USER:"):
            self.previous, self.current = self.current, []
        elif not msg.startswith(("JARVIS:", "réveil", "voix prête", "Imported", "Using writeable", "Creating",
                                 "Could not import", "# Generating")):
            self.current = (self.current + [msg])[-8:]


RECENT = _Recent()


class _Handler(__import__("logging").Handler):
    def emit(self, record):
        try:
            RECENT.add(record.getMessage())
        except Exception:
            pass


def install():
    import logging
    logging.getLogger("jarvis").addHandler(_Handler())


def _norm(t):
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFD", str(t).lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[’`]", "'", t)


def check_complaint(cfg, text, prev_text, prev_reply):
    """L'utilisateur dit que Jarvis s'est trompé : on envoie TOUT DE SUITE un rapport « correction »
    (demande d'avant, réponse de Jarvis, ce qu'il a fait, la plainte). Renvoie True si c'en est une."""
    if not prev_text or not COMPLAINT.search(_norm(text)):
        return False
    actions = " ; ".join(RECENT.previous)[-220:]
    detail = f"Jarvis a répondu : {prev_reply} | Plainte : {text} | Actions : {actions}"
    record(cfg, "correction", prev_text, detail)
    return True


def mask(text: str) -> str:
    """Retire ce qui pourrait identifier quelqu'un : e-mails, numéros, liens, chemins personnels."""
    t = str(text or "")[:200]
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<email>", t)
    t = re.sub(r"https?://\S+", "<lien>", t)
    t = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", r"C:\\Users\\<moi>", t)
    t = re.sub(r"\d[\d .-]{3,}\d", "<nombre>", t)
    return t


def _signature(kind, detail):
    if kind == "correction":  # même genre d'erreur = même début de réponse de Jarvis
        detail = str(detail).split(" | ")[0]
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
            send = (len(week) + 1 >= 2 or kind in ("exception", "correction")) and not sent_today \
                and cfg.get("send_reports", True)
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
