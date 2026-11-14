"""Contrôle des lecteurs média via Windows (le même système que les touches média et le panneau
de volume) : sait ce qui joue et peut lancer la lecture, sans clé API, pour YouTube, YouTube Music,
Spotify, Deezer… dans le navigateur ou dans leur appli."""
import asyncio
import threading
import time


def _manager():
    from winrt.windows.media.control import \
        GlobalSystemMediaTransportControlsSessionManager as M
    return asyncio.run(_await(M.request_async()))


async def _await(op):
    return await op


def sessions():
    """[(appli, titre, artiste, en_lecture, session)]"""
    out = []
    mgr = _manager()
    for s in mgr.get_sessions():
        try:
            info = asyncio.run(_await(s.try_get_media_properties_async()))
            title, artist = info.title, info.artist
        except Exception:
            title, artist = "", ""
        status = s.get_playback_info().playback_status  # 4 = Playing
        out.append((s.source_app_user_model_id or "", title, artist, int(status) == 4, s))
    return out


def now_playing() -> str:
    try:
        for app, title, artist, playing, _ in sessions():
            if playing and title:
                return f"{title}" + (f" de {artist}" if artist else "")
    except Exception:
        pass
    return ""


def ensure_playing(keywords=("chrome", "msedge", "firefox", "opera", "brave", "spotify", "deezer"),
                   timeout=12.0, after: float = 0.0):
    """Attend qu'un lecteur apparaisse puis lance la lecture s'il est en pause (en arrière-plan)."""
    def run():
        t0 = time.time()
        time.sleep(after)
        while time.time() - t0 < timeout:
            try:
                for app, title, _, playing, s in sessions():
                    if any(k in app.lower() for k in keywords) and title:
                        if not playing:
                            asyncio.run(_await(s.try_play_async()))
                        return
            except Exception:
                return
            time.sleep(0.8)
    threading.Thread(target=run, daemon=True).start()


def play() -> bool:
    """Lance la lecture du lecteur actif (au lieu de basculer pause/lecture à l'aveugle)."""
    try:
        mgr = _manager()
        s = mgr.get_current_session()
        if s:
            asyncio.run(_await(s.try_play_async()))
            return True
    except Exception:
        pass
    return False


def pause() -> bool:
    try:
        s = _manager().get_current_session()
        if s:
            asyncio.run(_await(s.try_pause_async()))
            return True
    except Exception:
        pass
    return False
