import json
from pathlib import Path
from typing import Iterable
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings as env_settings
from app.core import models
from app.api.schemas import SettingsPayload, SettingsUpdate
from app.core.logging_utils import reconfigure_logging

def _normalize_ext(exts: Iterable[str]) -> list[str]:
    seen = set()
    normalized = []
    for ext in exts:
        clean = ext.lower().lstrip(".").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        normalized.append(clean)
    return normalized

def _row_to_payload(row: models.SettingsRow | None) -> SettingsPayload:
    if row is None:
        return SettingsPayload(
            zip_galleries=env_settings.zip_galleries,
            update_gallery_zips=env_settings.update_gallery_zips,
            replicate_nesting=env_settings.replicate_nesting,
            leaf_only=env_settings.leaf_only,
            consider_images_in_subfolders=env_settings.consider_images_in_subfolders,
            output_mode=env_settings.output_mode,
            copy_sidecars=env_settings.copy_sidecars,
        lanraragi_flatten=env_settings.lanraragi_flatten,
        archive_extension_for_galleries=env_settings.archive_extension_for_galleries,
        debug_logging=env_settings.debug_logging,
        auto_scan_enabled=env_settings.auto_scan_enabled,
        auto_scan_interval_minutes=env_settings.auto_scan_interval_minutes,
        duplicates_enabled=True,
        min_images_to_be_gallery=env_settings.min_images_to_be_gallery,
        archive_extensions=_normalize_ext(env_settings.archive_extensions),
        image_extensions=_normalize_ext(env_settings.image_extensions),
    )

    def _get(attr: str, default):
        return getattr(row, attr, default)

    return SettingsPayload(
        zip_galleries=row.zip_galleries,
        update_gallery_zips=row.update_gallery_zips,
        replicate_nesting=row.replicate_nesting,
        leaf_only=_get("leaf_only", env_settings.leaf_only),
        consider_images_in_subfolders=_get("consider_images_in_subfolders", env_settings.consider_images_in_subfolders),
        output_mode=_get("output_mode", env_settings.output_mode) or env_settings.output_mode,
        copy_sidecars=_get("copy_sidecars", env_settings.copy_sidecars),
        lanraragi_flatten=_get("lanraragi_flatten", env_settings.lanraragi_flatten),
        archive_extension_for_galleries=_get("archive_extension_for_galleries", env_settings.archive_extension_for_galleries)
        or env_settings.archive_extension_for_galleries,
        debug_logging=_get("debug_logging", env_settings.debug_logging),
        auto_scan_enabled=_get("auto_scan_enabled", env_settings.auto_scan_enabled),
        auto_scan_interval_minutes=_get("auto_scan_interval_minutes", env_settings.auto_scan_interval_minutes),
        duplicates_enabled=_get("duplicates_enabled", True),
        min_images_to_be_gallery=_get("min_images_to_be_gallery", env_settings.min_images_to_be_gallery),
        archive_extensions=_normalize_ext(json.loads(_get("archive_extensions", "[]") or "[]")),
        image_extensions=_normalize_ext(json.loads(_get("image_extensions", "[]") or "[]")),
    )

async def get_settings(session: AsyncSession) -> SettingsPayload:
    result = await session.execute(select(models.SettingsRow).limit(1))
    row = result.scalars().first()
    if row is None:
        payload = _row_to_payload(None)
        new_row = models.SettingsRow(
            zip_galleries=payload.zip_galleries,
            update_gallery_zips=payload.update_gallery_zips,
            replicate_nesting=payload.replicate_nesting,
            leaf_only=payload.leaf_only,
            consider_images_in_subfolders=payload.consider_images_in_subfolders,
            output_mode=payload.output_mode,
            copy_sidecars=payload.copy_sidecars,
            lanraragi_flatten=payload.lanraragi_flatten,
            archive_extension_for_galleries=payload.archive_extension_for_galleries,
            debug_logging=payload.debug_logging,
            auto_scan_enabled=payload.auto_scan_enabled,
            auto_scan_interval_minutes=payload.auto_scan_interval_minutes,
            duplicates_enabled=payload.duplicates_enabled,
            min_images_to_be_gallery=payload.min_images_to_be_gallery,
            archive_extensions=json.dumps(payload.archive_extensions),
            image_extensions=json.dumps(payload.image_extensions),
        )
        session.add(new_row)
        await session.commit()
        return payload

    return _row_to_payload(row)

async def update_settings(session: AsyncSession, update: SettingsUpdate) -> SettingsPayload:
    result = await session.execute(select(models.SettingsRow).limit(1))
    row = result.scalars().first()
    if row is None:
        row = models.SettingsRow()
        session.add(row)

    old_debug = row.debug_logging if row else env_settings.debug_logging

    if update.zip_galleries is not None:
        row.zip_galleries = update.zip_galleries
    if update.update_gallery_zips is not None:
        row.update_gallery_zips = update.update_gallery_zips
    if update.replicate_nesting is not None:
        row.replicate_nesting = update.replicate_nesting
    if update.leaf_only is not None:
        row.leaf_only = update.leaf_only
    if update.consider_images_in_subfolders is not None:
        row.consider_images_in_subfolders = update.consider_images_in_subfolders
    if update.output_mode is not None:
        row.output_mode = update.output_mode
    if update.copy_sidecars is not None:
        row.copy_sidecars = update.copy_sidecars
    if update.lanraragi_flatten is not None:
        row.lanraragi_flatten = update.lanraragi_flatten
    if update.archive_extension_for_galleries is not None:
        row.archive_extension_for_galleries = update.archive_extension_for_galleries
    if update.debug_logging is not None:
        row.debug_logging = update.debug_logging
    if update.auto_scan_enabled is not None:
        row.auto_scan_enabled = update.auto_scan_enabled
    if update.auto_scan_interval_minutes is not None:
        row.auto_scan_interval_minutes = update.auto_scan_interval_minutes
    if update.duplicates_enabled is not None:
        row.duplicates_enabled = update.duplicates_enabled
    if update.min_images_to_be_gallery is not None:
        row.min_images_to_be_gallery = update.min_images_to_be_gallery
    if update.archive_extensions is not None:
        row.archive_extensions = json.dumps(_normalize_ext(update.archive_extensions))
    if update.image_extensions is not None:
        row.image_extensions = json.dumps(_normalize_ext(update.image_extensions))

    await session.commit()
    await session.refresh(row)
    payload = _row_to_payload(row)
    if row.debug_logging != old_debug:
        reconfigure_logging(Path(env_settings.config_root), row.debug_logging)
    return payload
