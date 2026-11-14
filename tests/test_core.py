"""Tests sans Windows : routeur, comparaison de versions, cerveau (HTTP simulé)."""
import sys, types
sys.path.insert(0, ".")
import jarvis
calls = []
fake = types.ModuleType("jarvis.actions")
for n in ("media", "volume", "now", "system", "open_folder"):
    setattr(fake, n, (lambda name: (lambda *a, **k: calls.append((name, a)) or f"{name}:{a}"))(n))
fake.open_app = lambda n: f"open:{n}"
fake.play_music = lambda q, s: f"play[{s}]:{q}"
fake.SENSITIVE = {("system", "shutdown")}
sys.modules["jarvis.actions"] = fake; jarvis.actions = fake
import jarvis.config as config
config.load = lambda: dict(config.DEFAULTS)
from jarvis.router import route

CASES = {
    "Hey Jarvis, change de musique": "media:('next',)",
    "musique suivante": "media:('next',)",
    "pause": "media:('play_pause',)",
    "monte le son": "volume:('up', 5)",
    "baisse le volume": "volume:('down', 5)",
    "quelle heure est-il": "now:()",
    "lance Spotify": "open:spotify",
    "lance YouTube Music": "open:youtube music",
    "ouvre Discord": "open:discord",
    "mets du Dua Lipa": "play[youtube]:dua lipa",
    "joue Stromae sur deezer": "play[deezer]:stromae",
    "mets la chanson Alors on danse": "play[youtube]:alors on danse",
    "ouvre mes téléchargements": "open_folder:('telechargements',)",
    "raconte-moi une blague": None,
    "qui a gagné la coupe du monde 2018": None,
}


def test_router():
    for phrase, want in CASES.items():
        assert route(phrase) == want, (phrase, route(phrase), want)


def test_versions():
    from jarvis.updater import _v
    assert _v("v1.10.0") > _v("1.9.9") and _v("v1.3.3") == _v("1.3.3")


def test_brain_tool_loop():
    import json
    from jarvis import brain
    seq = [
        {"tool_calls": [{"id": "1", "function": {"name": "media", "arguments": json.dumps({"action": "next"})}}]},
        {"content": "Piste suivante, Monsieur."},
    ]

    class R:
        def __init__(self, m): self.m = m; self.status_code = 200; self.text = ""
        def json(self): return {"choices": [{"message": self.m}]}
    brain.requests.post = lambda *a, **k: R(seq.pop(0))
    b = brain.Brain(dict(config.DEFAULTS, groq_api_key="x"), print, lambda q: True)
    assert b.ask("change de musique") == "Piste suivante, Monsieur."
    assert len(b.history) == 2


if __name__ == "__main__":
    test_router(); test_versions(); test_brain_tool_loop(); print("TOUS LES TESTS OK")
