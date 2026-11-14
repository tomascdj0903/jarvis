"""Météo et localisation, sans clé API et sans ouvrir de navigateur.
Localisation : ville dans la phrase > ville des Réglages > localisation Windows > adresse IP."""
import datetime
import json
import subprocess

import requests

from . import config

CODES = {0: "ciel dégagé", 1: "plutôt dégagé", 2: "partiellement nuageux", 3: "couvert", 45: "brouillard",
         48: "brouillard givrant", 51: "bruine légère", 53: "bruine", 55: "forte bruine", 61: "pluie faible",
         63: "pluie", 65: "forte pluie", 66: "pluie verglaçante", 67: "forte pluie verglaçante", 71: "neige faible",
         73: "neige", 75: "forte neige", 77: "grésil", 80: "averses", 81: "averses", 82: "violentes averses",
         85: "averses de neige", 86: "fortes averses de neige", 95: "orages", 96: "orages avec grêle",
         99: "violents orages avec grêle"}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_cache = {}


def _windows_location():
    """Coordonnées via le service de localisation Windows (s'il est activé)."""
    ps = ("Add-Type -AssemblyName System.Device;"
          "$w=New-Object System.Device.Location.GeoCoordinateWatcher('High');$w.Start();"
          "$t=0;while(($w.Status -ne 'Ready') -and ($t -lt 60)){Start-Sleep -Milliseconds 100;$t++};"
          "$c=$w.Position.Location;if(-not $c.IsUnknown){\"$($c.Latitude);$($c.Longitude)\"}")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=10, creationflags=0x08000000).stdout.strip()
        if ";" in out:
            lat, lon = (float(x.replace(",", ".")) for x in out.split(";"))
            return lat, lon
    except Exception:
        pass
    return None


def _reverse(lat, lon):
    try:
        r = requests.get("https://nominatim.openstreetmap.org/reverse", timeout=6,
                         params={"lat": lat, "lon": lon, "format": "json", "zoom": 10, "accept-language": "fr"},
                         headers={"User-Agent": "Jarvis-assistant/1.0"}).json()
        a = r.get("address", {})
        return a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or ""
    except Exception:
        return ""


def _geocode(city):
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search", timeout=6,
                     params={"name": city, "count": 1, "language": "fr"}).json()
    res = (r.get("results") or [None])[0]
    if not res:
        return None
    return res["latitude"], res["longitude"], res["name"]


def locate(city: str = ""):
    """(lat, lon, nom_ville, source)"""
    cfg = config.load()
    city = (city or "").strip() or cfg.get("home_city", "").strip()
    if city:
        g = _geocode(city)
        if g:
            return (*g, "ville")
    if "here" in _cache and (datetime.datetime.now() - _cache["here_t"]).seconds < 1800:
        return _cache["here"]
    w = _windows_location()
    if w:
        res = (w[0], w[1], _reverse(*w) or "votre position", "windows")
    else:
        ip = requests.get("https://ipwho.is/", timeout=6, params={"lang": "fr"}).json()
        res = (ip["latitude"], ip["longitude"], ip.get("city", "votre ville"), "ip")
    _cache["here"], _cache["here_t"] = res, datetime.datetime.now()
    return res


def weather(city: str = "", day: str = "aujourd'hui") -> str:
    """Résumé parlé de la météo. day : aujourd'hui, demain, après-demain, ou un jour de la semaine."""
    lat, lon, name, _ = locate(city)
    d = requests.get("https://api.open-meteo.com/v1/forecast", timeout=15, params={
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 7,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}).json()
    day = (day or "aujourd'hui").lower()
    today = datetime.date.today()
    if day in ("demain",):
        idx = 1
    elif day in ("apres-demain", "après-demain"):
        idx = 2
    elif day in JOURS:
        idx = (JOURS.index(day) - today.weekday()) % 7 or 7
        idx = min(idx, 6)
    else:
        idx = 0
    dl = d["daily"]
    tmin, tmax = round(dl["temperature_2m_min"][idx]), round(dl["temperature_2m_max"][idx])
    desc = CODES.get(dl["weather_code"][idx], "temps variable")
    pluie = dl["precipitation_probability_max"][idx]
    if idx == 0:
        c = d["current"]
        txt = (f"À {name}, il fait actuellement {round(c['temperature_2m'])} degrés, {CODES.get(c['weather_code'], '')}, "
               f"ressenti {round(c['apparent_temperature'])}. Aujourd'hui entre {tmin} et {tmax} degrés")
    else:
        label = "Demain" if idx == 1 else ("Après-demain" if idx == 2 else JOURS[(today.weekday() + idx) % 7].capitalize())
        txt = f"{label} à {name} : {desc}, entre {tmin} et {tmax} degrés"
    if pluie is not None and pluie >= 30:
        txt += f", avec {pluie} % de risque de pluie"
    return txt + "."


def ask_web(question: str, cfg) -> str:
    """Réponse à jour (actualité, résultats, prix…) via le modèle Groq avec recherche web intégrée."""
    for model in ("groq/compound-mini", "groq/compound"):
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", timeout=40,
                              headers={"Authorization": f"Bearer {cfg['groq_api_key'].strip()}"},
                              json={"model": model, "max_tokens": 300, "messages": [
                                  {"role": "system", "content": "Réponds en français, en 1 à 3 phrases courtes, "
                                   "sans liens ni markdown : le texte sera lu à voix haute."},
                                  {"role": "user", "content": question}]})
            if r.ok:
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            continue
    return "Je n'ai pas pu trouver la réponse en ligne."
