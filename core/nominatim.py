import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from core.config import get_settings

TIMEOUT_SECONDS = 5
MIN_INTERVAL_SECONDS = 1.0
CACHE_SECONDS = 24 * 60 * 60
CACHE_SIZE = 500


class NominatimError(Exception):
    pass


_lock = threading.Lock()
_last_call = 0.0
_cache: dict[str, tuple[float, list[dict]]] = {}


def _wait_turn() -> None:
    global _last_call
    with _lock:
        delay = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_call)
        if delay > 0:
            time.sleep(delay)
        _last_call = time.monotonic()


def _remember(key: str, results: list[dict]) -> None:
    if len(_cache) >= CACHE_SIZE:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (time.monotonic(), results)


def search(query: str, limit: int = 5) -> list[dict]:
    key = f"{query.lower()}|{limit}"
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]

    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "countrycodes": "ke",
            "limit": limit,
            "accept-language": "en",
        }
    )
    settings = get_settings()
    request = urllib.request.Request(
        f"{settings.nominatim_url}/search?{params}",
        headers={
            "User-Agent": settings.nominatim_user_agent,
            "Accept": "application/json",
        },
    )
    _wait_turn()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            results = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise NominatimError("Place search failed.") from exc
    if not isinstance(results, list):
        raise NominatimError("Place search sent an unexpected answer.")

    _remember(key, results)
    return results
