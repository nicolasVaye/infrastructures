"""Application-level settings endpoints (admin-configurable, stored in DB).

Currently hosts the custom application logo: an SVG/PNG/JPG uploaded from the
admin settings page, persisted in the ``app_settings`` table and served to the
frontend (header, login page, favicon). A multi-resolution ``.ico`` favicon is
generated automatically from raster uploads (Pillow); SVG uploads are served
as-is (modern browsers render SVG favicons directly).
"""

from __future__ import annotations

import base64
import io

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.core.db import SettingRecord
from app.core.security import AdminUser, CurrentUser, DbSession
from app.events import notify_event

router = APIRouter(tags=["settings"])

# Keys used in the app_settings table for the logo feature.
_K_MIME = "logo_mime"
_K_DATA = "logo_data"
_K_ICO = "logo_favicon_ico"
_K_VERSION = "logo_version"
# Generated PNG icons (PWA manifest, apple-touch), stored per name.
_K_ICON_PREFIX = "logo_icon_"
# Application display timezone (audit log, connected sessions…). All
# timestamps stay stored as UTC; this only drives how the frontend renders them.
_K_TZ = "app_timezone"

_ACCEPTED_MIMES = ("image/svg+xml", "image/png", "image/jpeg")
_MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB

# ICO favicon sizes rendered from raster uploads.
_ICO_SIZES = [(16, 16), (32, 32), (48, 48)]

# PNG icons generated from raster uploads, served by GET /app/logo/icons/{name}.
# The frontend used to ship static PWA icons in its assets; they went stale
# the moment the admin uploaded a new logo — now every icon is regenerated
# from the upload itself. Maskable icons get cropped to a circle by the OS,
# so the logo is pasted inside the 80% safe zone over an opaque background.
_ICON_SPECS: dict[str, tuple[int, bool]] = {
    "icon-192.png": (192, False),
    "icon-512.png": (512, False),
    "icon-maskable-512.png": (512, True),
    "apple-touch-icon.png": (180, False),
}


class LogoIn(BaseModel):
    mime: str
    # Raw file bytes, base64-encoded.
    data: str


class LogoOut(BaseModel):
    mime: str
    data: str  # base64 image bytes
    version: int


class TimezoneIn(BaseModel):
    timezone: str


def _valid_timezone(name: str) -> bool:
    """True when the name is an IANA zone the backend can resolve."""
    if name == "UTC":
        return True
    try:
        from zoneinfo import available_timezones
        return name in available_timezones()
    except ImportError:  # pragma: no cover  slim images without tzdata
        return False


async def _get_setting(session, key: str) -> str | None:
    row = (await session.scalars(
        select(SettingRecord).where(SettingRecord.key == key))).first()
    return row.value if row else None


async def _set_setting(session, key: str, value: str | None) -> None:
    row = (await session.scalars(
        select(SettingRecord).where(SettingRecord.key == key))).first()
    if value is None:
        if row:
            await session.delete(row)
    elif row:
        row.value = value
    else:
        session.add(SettingRecord(key=key, value=value))


def _generate_ico(raw: bytes, mime: str) -> str | None:
    """Build a multi-resolution .ico favicon from a PNG/JPG upload.

    Returns the ICO bytes base64-encoded, or ``None`` when the image cannot
    be processed (SVG has no raster source; Pillow missing, corrupt file…).
    """
    if mime == "image/svg+xml":
        return None  # SVG favicon is served directly by the frontend
    try:
        from PIL import Image  # noqa: PLC0415  optional runtime dependency
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(raw))
        img.thumbnail((256, 256))
        buf = io.BytesIO()
        img.save(buf, format="ICO", sizes=_ICO_SIZES)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001  a bad image must not break the upload
        return None


def _generate_png(raw: bytes, size: int, maskable: bool) -> str | None:
    """Render one square PNG icon from a raster upload (base64-encoded).

    ``maskable`` pastes the logo inside the 80% safe zone over an opaque
    background so the OS can crop it to any shape without clipping the
    logo itself.
    """
    try:
        from PIL import Image  # noqa: PLC0415  optional runtime dependency
    except ImportError:
        return None
    try:
        logo = Image.open(io.BytesIO(raw))
        if maskable:
            canvas = Image.new("RGB", (size, size), (255, 255, 255))
            fit = int(size * 0.8)
            logo.thumbnail((fit, fit))
            if logo.mode in ("RGBA", "LA", "P"):
                logo = logo.convert("RGBA")
                canvas.paste(logo, ((size - logo.width) // 2,
                                    (size - logo.height) // 2), logo)
            else:
                canvas.paste(logo, ((size - logo.width) // 2,
                                    (size - logo.height) // 2))
            out = canvas
        else:
            out = logo
            out.thumbnail((size, size))
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001  a bad image must not break the upload
        return None


@router.get("/app/logo", response_model=LogoOut)
async def get_logo(session: DbSession) -> LogoOut:
    """Public: the custom logo (the favicon/login page need it pre-auth)."""
    data = await _get_setting(session, _K_DATA)
    mime = await _get_setting(session, _K_MIME)
    if not data or not mime:
        raise HTTPException(404, "No custom logo configured")
    version = int(await _get_setting(session, _K_VERSION) or 0)
    return LogoOut(mime=mime, data=data, version=version)


@router.get("/app/logo.ico")
async def get_logo_ico(session: DbSession) -> dict:
    """Public: the pre-generated ICO favicon, as base64 (or 404)."""
    ico = await _get_setting(session, _K_ICO)
    if not ico:
        raise HTTPException(404, "No ICO favicon available")
    return {"data": ico}


@router.get("/app/logo/icons/{name}")
async def get_logo_icon(name: str, session: DbSession) -> Response:
    """Public: a PNG icon generated from the uploaded logo, raw bytes.

    404 when no custom logo is configured or the logo is an SVG (Pillow
    cannot rasterize SVG) — the frontend then falls back to the SVG itself.
    """
    if name not in _ICON_SPECS:
        raise HTTPException(404, "Unknown icon")
    data = await _get_setting(session, _K_ICON_PREFIX + name)
    if not data:
        raise HTTPException(404, "No icon available")
    return Response(
        content=base64.b64decode(data),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.put("/app/logo", response_model=LogoOut, status_code=201)
async def set_logo(body: LogoIn, admin: AdminUser, session: DbSession) -> LogoOut:
    """Upload the application logo (SVG/PNG/JPG) and regenerate every icon.

    Raster uploads regenerate the whole icon set server-side (ICO favicon,
    PWA 192/512/maskable PNGs, apple-touch) so the static icons shipped in
    the frontend assets stay in phase with whatever the admin uploads. SVG
    uploads are served as-is everywhere (no raster source for Pillow).
    """
    mime = (body.mime or "").lower()
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in _ACCEPTED_MIMES:
        raise HTTPException(400, "Unsupported format (SVG, PNG or JPG only)")
    try:
        raw = base64.b64decode(body.data)
    except Exception:
        raise HTTPException(400, "Invalid base64 payload") from None
    if len(raw) > _MAX_LOGO_BYTES:
        raise HTTPException(400, "Logo too large (max 2 MB)")

    version = int(await _get_setting(session, _K_VERSION) or 0) + 1
    await _set_setting(session, _K_MIME, mime)
    await _set_setting(session, _K_DATA, body.data)
    await _set_setting(session, _K_ICO, _generate_ico(raw, mime))
    for name, (size, maskable) in _ICON_SPECS.items():
        await _set_setting(
            session, _K_ICON_PREFIX + name,
            None if mime == "image/svg+xml" else _generate_png(raw, size, maskable))
    await _set_setting(session, _K_VERSION, str(version))
    # Push the new logo to every open browser (not just the tabs of the
    # uploading browser): the frontend bumps its logo_version and re-renders
    # header + favicon on this event.
    await notify_event(session, "app_settings_changed",
                       setting="logo", version=version)
    await session.commit()

    return LogoOut(mime=mime, data=body.data, version=version)


@router.delete("/app/logo", status_code=204)
async def reset_logo(admin: AdminUser, session: DbSession) -> None:
    """Remove the custom logo; the frontend falls back to the bundled asset."""
    await session.execute(delete(SettingRecord).where(
        SettingRecord.key.in_(
            [_K_MIME, _K_DATA, _K_ICO]
            + [_K_ICON_PREFIX + name for name in _ICON_SPECS])))
    # Bump + broadcast: open browsers must drop their cached custom logo and
    # favicon, not keep showing them until the next full page load.
    version = int(await _get_setting(session, _K_VERSION) or 0) + 1
    await _set_setting(session, _K_VERSION, str(version))
    await notify_event(session, "app_settings_changed",
                       setting="logo", version=version)


@router.get("/app/timezone")
async def get_timezone(user: CurrentUser, session: DbSession) -> dict:
    """The display timezone configured by the admin (default UTC).

    Authenticated: unlike the logo (needed on the pre-auth login page and
    favicon), nothing public renders timestamps — leaking the admin's
    configured zone to anonymous callers is pure information disclosure.
    All frontend call sites go through the caller's token (get_session).
    """
    tz = await _get_setting(session, _K_TZ)
    return {"timezone": tz or "UTC"}


@router.put("/app/timezone", status_code=201)
async def set_timezone(body: TimezoneIn, admin: AdminUser, session: DbSession) -> dict:
    """Set the application display timezone (admin only, IANA names)."""
    tz = (body.timezone or "UTC").strip()
    if not _valid_timezone(tz):
        raise HTTPException(400, f"Unknown timezone: {tz}")
    await _set_setting(session, _K_TZ, tz)
    await session.commit()
    return {"timezone": tz}
    await session.commit()
