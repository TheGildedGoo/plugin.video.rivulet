"""One lazy Kodi monitor for Home's cooperative background waits."""
import threading

_monitor = None
_lock = threading.Lock()


def monitor():
    global _monitor
    with _lock:
        if _monitor is None:
            import xbmc

            _monitor = xbmc.Monitor()
        return _monitor
