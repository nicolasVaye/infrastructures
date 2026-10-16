"""Backend asset proxying with a short-lived process cache.

The public backend routes /app/logo, /app/logo.ico and /app/logo/icons/{name}
serve the admin-uploaded logo set. The frontend proxies them at /logo,
/favicon.ico and the icon routes — needed before authentication (favicon,
login page, PWA manifest).

Without a cache, every browser page render re-requests the backend; when no
custom logo is configured each call is a 404 in the backend logs — one line
of noise per page load per tab. The TTL below keeps a "no logo" miss for at
most a minute, and :func:`invalidate` lets the settings page refresh the
cache the moment an upload lands instead of waiting for the TTL.
"""

from __future__ import annotations

import base64
import time

import httpx

from core.database import BACKEND_URL

# How long a fetched asset (or a "no logo configured" miss) is reused.
_TTL_SECONDS = 60.0

_cache: dict[str, tuple[float, tuple[bytes, str] | None]] = {}


def backend_asset(path: str) -> tuple[bytes, str] | None:
    """Fetch a public backend asset, or None when absent/unreachable.

    Handles both payload shapes: JSON ``{"data": <base64>, "mime": ...}``
    (logo + ICO) and raw bytes (generated PNG icons).
    """
    now = time.monotonic()
    hit = _cache.get(path)
    if hit is not None and now - hit[0] < _TTL_SECONDS:
        return hit[1]
    try:
        r = httpx.get(f'{BACKEND_URL}{path}', timeout=5.0)
    except Exception:  # noqa: BLE001 — backend down: caller uses the fallback
        value = None
    else:
        value = _decode(r)
    _cache[path] = (now, value)
    return value


def invalidate() -> None:
    """Drop every cached asset (called right after a logo upload/reset)."""
    _cache.clear()


def _decode(r: httpx.Response) -> tuple[bytes, str] | None:
    if r.status_code != 200:
        return None
    if (r.headers.get('content-type') or '').startswith('application/json'):
        try:
            body = r.json()
            return base64.b64decode(body['data']), body.get('mime') or 'image/png'
        except Exception:  # noqa: BLE001 — malformed payload
            return None
    return r.content, r.headers.get('content-type') or 'image/png'
