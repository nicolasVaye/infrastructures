"""Application display timezone: read the admin setting and render timestamps.

Every timestamp is STORED as UTC (backend ``utcnow()``); the admin-configured
timezone (``PUT /app/timezone`` → ``app_settings`` table) only drives how the
frontend DISPLAYS them (audit log, connected sessions). The configured zone
is fetched from ``GET /app/timezone`` and cached briefly so a table refresh
does not trigger one API call per render — but a change made by an admin
shows up within the TTL, without any restart.
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from core.database import get_session

# Curated list of common IANA zones for the settings dropdown. The stored
# value is always accepted even when absent from this list (the select then
# shows it as its own extra option).
COMMON_TIMEZONES: tuple[str, ...] = (
    'UTC',
    'Europe/Paris', 'Europe/London', 'Europe/Berlin', 'Europe/Madrid',
    'Europe/Rome', 'Europe/Amsterdam', 'Europe/Brussels', 'Europe/Zurich',
    'Europe/Lisbon', 'Europe/Stockholm', 'Europe/Warsaw', 'Europe/Athens',
    'Europe/Helsinki', 'Europe/Prague', 'Europe/Vienna', 'Europe/Dublin',
    'Europe/Copenhagen', 'Europe/Oslo', 'Europe/Budapest', 'Europe/Bucharest',
    'Atlantic/Reykjavik',
    'America/New_York', 'America/Chicago', 'America/Denver',
    'America/Los_Angeles', 'America/Anchorage', 'America/Sao_Paulo',
    'America/Argentina/Buenos_Aires', 'America/Toronto', 'America/Vancouver',
    'America/Mexico_City', 'America/Bogota',
    'Asia/Tokyo', 'Asia/Seoul', 'Asia/Shanghai', 'Asia/Hong_Kong',
    'Asia/Singapore', 'Asia/Taipei', 'Asia/Kolkata', 'Asia/Dubai',
    'Asia/Bangkok', 'Asia/Jakarta', 'Asia/Vladivostok',
    'Australia/Sydney', 'Australia/Melbourne', 'Australia/Perth',
    'Australia/Brisbane', 'Pacific/Auckland', 'Pacific/Honolulu',
    'Africa/Casablanca', 'Africa/Lagos', 'Africa/Johannesburg', 'Africa/Cairo',
)

# How long the fetched timezone stays cached (seconds).
_CACHE_TTL = 10.0
_cache: dict = {'ts': 0.0, 'tz': 'UTC'}


def get_app_timezone() -> str:
    """Current display timezone (IANA name), defaulting to UTC.

    Cached for a few seconds so repeated table refreshes share one fetch.
    """
    now = time.monotonic()
    if now - _cache['ts'] < _CACHE_TTL:
        return _cache['tz']
    try:
        with get_session() as session:
            data = session.get('/app/timezone') or {}
        tz = str(data.get('timezone') or 'UTC')
    except Exception:  # noqa: BLE001  backend unreachable → keep last known
        tz = _cache['tz']
    # Never trust a zone the runtime cannot resolve.
    try:
        ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        tz = 'UTC'
    _cache.update({'ts': now, 'tz': tz})
    return tz


def invalidate_cache() -> None:
    """Drop the cached timezone (called right after an admin saves a new one)."""
    _cache['ts'] = 0.0


def format_local(value, tz: str | None = None) -> str:
    """Render a UTC timestamp (datetime or ISO string) in the app timezone.

    Naive values are assumed UTC (that is what the backend stores). Only
    date and time are shown — the offset adds noise without information,
    the configured zone already says where the time is local.
    """
    if not value:
        return '—'
    if isinstance(value, str):
        text = value.strip().replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return value  # not a parseable timestamp: show it as-is
    elif isinstance(value, datetime):
        dt = value
    else:
        return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo('UTC'))
    try:
        local = dt.astimezone(ZoneInfo(tz or get_app_timezone()))
    except Exception:  # noqa: BLE001  bad stored zone → fall back to UTC
        local = dt.astimezone(ZoneInfo('UTC'))
    return local.strftime('%Y-%m-%d %H:%M:%S')
