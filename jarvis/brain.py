"""Le cerveau : LLM via l'API Groq (gratuite, compatible OpenAI) avec appel d'outils.
Pour changer de fournisseur, il suffit de modifier API_URL / le modèle."""
import datetime
import json

import requests

from . import actions

API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODELS_URL = "https://api.groq.com/openai/v1/models"
# Ordre de préférence (tous gèrent l'appel d'outils chez Groq)
PREFERRED = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b",
             "moonshotai/kimi-k2-instruct", "qwen/qwen3-32b", "llama-3.1-8b-instant"]


class GroqError(Exception):
    pass


def _tool(name, desc, props=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}


S = {"type": "string"}
TOOLS = [
    _tool("open_app", "Lance une application, un logiciel ou un jeu installé (Spotify, Discord, Chrome, Minecraft...).",
          {"name": S}, ["name"]),
    _tool("close_app", "Ferme une application par son nom de processus (ex: spotify, discord, chrome).",
          {"name": S}, ["name"]),
    _tool("list_apps", "Liste les applications installées contenant un mot.", {"query": S}),
    _tool("media", "Contrôle la musique/vidéo en cours (Spotify, YouTube...).",
          {"action": {"type": "string", "enum": ["next", "previous", "play_pause", "stop"]}}, ["action"]),
    _tool("volume", "Change le volume du PC. steps = nombre de crans (1 cran = 2%).",
          {"action": {"type": "string", "enum": ["up", "down", "mute"]}, "steps": {"type": "integer"}},
          ["action"]),
    _tool("play_music", "Lance un titre, un artiste ou un style de musique sur le service de musique de l'utilisateur.",
          {"query": S}, ["query"]),
    _tool("find_files", "Cherche des fichiers par nom dans les dossiers autorisés.", {"query": S}, ["query"]),
    _tool("open_path", "Ouvre un fichier ou dossier par son chemin complet.", {"path": S}, ["path"]),
    _tool("open_folder", "Ouvre un dossier courant : bureau, documents, téléchargements, musique, images, vidéos.",
          {"name": S}, ["name"]),
    _tool("organize_downloads", "Range le dossier Téléchargements par type de fichier."),
    _tool("system", "Action système.",
          {"action": {"type": "string",
                      "enum": ["lock", "screenshot", "shutdown", "restart", "cancel_shutdown", "sleep"]}},
          ["action"]),
    _tool("web_search", "Ouvre une recherche Google.", {"query": S}, ["query"]),
    _tool("open_website", "Ouvre un site web.", {"url": S}, ["url"]),
    _tool("type_text", "Tape du texte dans la fenêtre active.", {"text": S}, ["text"]),
    _tool("set_timer", "Lance un minuteur.", {"seconds": {"type": "integer"}, "label": S}, ["seconds"]),
]


class Brain:
    def __init__(self, cfg, speak, confirm):
        self.cfg, self.speak, self.confirm = cfg, speak, confirm
        self.history = []

    def _system(self):
        return (
            "Tu es J.A.R.V.I.S., l'assistant personnel de l'utilisateur sur son PC Windows, "
            "dans le style du Jarvis d'Iron Man : poli, efficace, légèrement pince-sans-rire. "
            f"Tu t'adresses à lui en l'appelant « {self.cfg['user_name']} ». "
            "Tes réponses sont LUES À VOIX HAUTE : une ou deux phrases courtes, sans markdown, sans liste, sans emoji. "
            "Utilise les outils dès qu'une action est demandée. « Change de musique » = media next. "
            f"Date et heure actuelles : {datetime.datetime.now():%A %d/%m/%Y %H:%M}. Réponds en français."
        )

    def _headers(self):
        return {"Authorization": f"Bearer {self.cfg['groq_api_key'].strip()}"}

    def pick_model(self):
        """Choisit un modèle réellement disponible sur le compte Groq."""
        r = requests.get(MODELS_URL, headers=self._headers(), timeout=15)
        if r.status_code == 401:
            raise GroqError("401 : clé API Groq invalide")
        r.raise_for_status()
        ids = {m["id"] for m in r.json().get("data", []) if m.get("active", True)}
        for m in PREFERRED:
            if m in ids:
                return m
        chat = sorted(i for i in ids if "whisper" not in i and "tts" not in i and "guard" not in i)
        if not chat:
            raise GroqError("aucun modèle de discussion disponible sur ce compte Groq")
        return chat[0]

    def _post(self, messages):
        return requests.post(API_URL, timeout=30, headers=self._headers(),
                             json={"model": self.cfg["llm_model"], "messages": messages,
                                   "tools": TOOLS, "tool_choice": "auto", "temperature": 0.4,
                                   "max_tokens": 250})

    def _call(self, messages):
        r = self._post(messages)
        if r.status_code in (400, 404) and "model" in r.text.lower():
            # modèle retiré ou inaccessible : on en choisit un autre et on le garde
            from . import config
            new = self.pick_model()
            self.cfg["llm_model"] = new
            config.save(self.cfg)
            r = self._post(messages)
        if r.status_code >= 400:
            try:
                detail = r.json().get("error", {}).get("message", r.text)
            except Exception:
                detail = r.text
            raise GroqError(f"{r.status_code} : {detail[:150]}")
        return r.json()["choices"][0]["message"]

    def _run_tool(self, name, args):
        a = actions
        if (name, args.get("action")) in a.SENSITIVE or (name, None) in a.SENSITIVE:
            if not self.confirm(f"Vous confirmez : {name.replace('_', ' ')} {args.get('action', '')} ?"):
                return "Action annulée par l'utilisateur."
        cfg = self.cfg
        table = {
            "open_app": lambda: a.open_app(args["name"]),
            "close_app": lambda: a.close_app(args["name"]),
            "list_apps": lambda: a.list_apps(args.get("query", "")),
            "media": lambda: a.media(args["action"]),
            "volume": lambda: a.volume(args["action"], args.get("steps", 5)),
            "play_music": lambda: a.play_music(args["query"], cfg.get("music_service", "youtube")),
            "find_files": lambda: a.find_files(args["query"], cfg),
            "open_path": lambda: a.open_path(args["path"], cfg),
            "open_folder": lambda: a.open_folder(args["name"]),
            "organize_downloads": lambda: a.organize_downloads(cfg),
            "system": lambda: a.system(args["action"]),
            "web_search": lambda: a.web_search(args["query"]),
            "open_website": lambda: a.open_website(args["url"]),
            "type_text": lambda: a.type_text(args["text"]),
            "set_timer": lambda: a.set_timer(args["seconds"], args.get("label", "minuteur"), self.speak),
        }
        try:
            return table[name]() if name in table else "Outil inconnu."
        except Exception as e:
            return f"Erreur : {e}"

    def ask(self, text: str) -> str:
        self.history = self.history[-6:]  # 3 échanges suffisent
        self.history.append({"role": "user", "content": text})
        messages = [{"role": "system", "content": self._system()}] + self.history
        for _ in range(4):  # quelques tours d'outils max
            msg = self._call(messages)
            calls = msg.get("tool_calls") or []
            if not calls:
                reply = (msg.get("content") or "C'est fait.").strip()
                self.history.append({"role": "assistant", "content": reply})
                return reply
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for c in calls:
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self._run_tool(c["function"]["name"], args)
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
        return "C'est fait."
