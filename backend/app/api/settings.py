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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.core.db import SettingRecord
from app.core.security import AdminUser, DbSession

router = APIRouter(tags=["settings"])

# Keys used in the app_settings table for the logo feature.
_K_MIME = "logo_mime"
_K_DATA = "logo_data"
_K_ICO = "logo_favicon_ico"
_K_VERSION = "logo_version"

_ACCEPTED_MIMES = ("image/svg+xml", "image/png", "image/jpeg")
_MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB

# ICO favicon sizes rendered from raster uploads.
_ICO_SIZES = [(16, 16), (32, 32), (48, 48)]


class LogoIn(BaseModel):
    mime: str
    # Raw file bytes, base64-encoded.
    data: str


class LogoOut(BaseModel):
    mime: str
    data: str  # base64-encoded image bytes
    version: int


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


@router.put("/app/logo", response_model=LogoOut, status_code=201)
async def set_logo(body: LogoIn, admin: AdminUser, session: DbSession) -> LogoOut:
    """Upload the application logo (SVG/PNG/JPG) and regenerate the favicon."""
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
    await _set_setting(session, _K_VERSION, str(version))
    await session.commit()

    return LogoOut(mime=mime, data=body.data, version=version)


@router.delete("/app/logo", status_code=204)
async def reset_logo(admin: AdminUser, session: DbSession) -> None:
    """Remove the custom logo; the frontend falls back to the bundled asset."""
    await session.execute(delete(SettingRecord).where(
        SettingRecord.key.in_([_K_MIME, _K_DATA, _K_ICO])))
    await session.commit()
