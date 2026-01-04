import errno
import hashlib
import logging
import json
import os
import shutil
import time
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DiffItem, DiffResult, PlanAction, ScanResult, ScanSummary
from app.core import models
from app.core.config import settings as env_settings
from app.services.activity_service import log_activity
from app.services.settings_service import get_settings
from app.services.status_service import set_status

SIDECAR_EXTS = {".txt", ".json", ".xml", ".nfo"}
_last_results: Dict[str, Optional[ScanResult]] = {"dryrun": None, "run": None}
_warned_missing_duplicates = False
logger = logging.getLogger("galleryloom.scan")


@dataclass
class GalleryCandidate:
    path: Path
    rel_dir: Path
    images: List[Path]
    signature: Dict[str, int]
    is_leaf: bool


def _ext_in_list(path: Path, options: Iterable[str]) -> bool:
    return path.suffix.lower().lstrip(".") in {ext.lower().lstrip(".") for ext in options}


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def _gallery_signature(images: List[Path]) -> dict:
    if not images:
        return {"image_count": 0, "total_image_bytes": 0, "newest_mtime": 0}
    stats = [p.stat() for p in images]
    return {
        "image_count": len(images),
        "total_image_bytes": sum(s.st_size for s in stats),
        "newest_mtime": max(s.st_mtime for s in stats),
    }


def _archive_signature(path: Path) -> dict:
    stat = path.stat()
    return {"size": stat.st_size, "mtime": stat.st_mtime}


async def _get_record(session: AsyncSession, target_path: Path) -> models.ArchiveRecord | None:
    stmt = select(models.ArchiveRecord).where(models.ArchiveRecord.target_path == str(target_path))
    result = await session.execute(stmt)
    return result.scalars().first()


async def _upsert_record(
    session: AsyncSession,
    target_path: Path,
    source_path: Path,
    type_: str,
    signature: dict,
    virtual_target_path: Path | None = None,
) -> None:
    now = datetime.utcnow()
    existing = await _get_record(session, target_path)
    if existing:
        existing.source_path = str(source_path)
        existing.type = type_
        existing.signature_json = json.dumps(signature)
        existing.virtual_target_path = str(virtual_target_path) if virtual_target_path else None
        existing.last_seen_at = now
        existing.updated_at = now
    else:
        session.add(
            models.ArchiveRecord(
                target_path=str(target_path),
                source_path=str(source_path),
                type=type_,
                signature_json=json.dumps(signature),
                virtual_target_path=str(virtual_target_path) if virtual_target_path else None,
                created_at=now,
                updated_at=now,
                last_seen_at=now,
            )
        )
    await session.commit()


async def _touch_record(session: AsyncSession, target_path: Path):
    existing = await _get_record(session, target_path)
    if existing:
        existing.last_seen_at = datetime.utcnow()
        await session.commit()


def _copy_file(src: Path, dest: Path):
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if env_settings.use_hardlinks:
            try:
                os.link(src, dest)
                logger.debug("Hardlinked %s -> %s", src, dest)
                return
            except OSError:
                logger.debug("Hardlink failed for %s -> %s, falling back to copy", src, dest)
        shutil.copy2(src, dest)
        logger.debug("Copied %s -> %s", src, dest)
    except Exception:
        logger.debug("Copy failed for %s -> %s", src, dest, exc_info=True)
        raise


def _safe_unlink(path: Path):
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception:
        logger.debug("Failed to remove temp file %s", path, exc_info=True)


def _fsync_path(path: Path):
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        logger.debug("fsync skipped for %s", path, exc_info=True)


def _create_temp_zip_path(target_zip: Path) -> tuple[Path, bool]:
    target_dir = target_zip.parent
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            delete=False,
            dir=target_dir,
            prefix=f"{target_zip.stem}_",
            suffix=".zip.tmp",
        )
        handle.close()
        return Path(handle.name), True
    except Exception:
        logger.debug("Unable to create temp in target dir for %s, falling back to tmp root", target_zip, exc_info=True)
    tmp_root = Path(env_settings.temp_dir or env_settings.tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        delete=False,
        dir=tmp_root,
        prefix=f"{target_zip.stem}_",
        suffix=".zip.tmp",
    )
    handle.close()
    return Path(handle.name), False


def _write_zip(source_dir: Path, image_files: List[Path], target_zip: Path):
    temp_zip: Path | None = None
    partial_path: Path | None = None
    try:
        temp_zip, _ = _create_temp_zip_path(target_zip)
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file in image_files:
                arcname = file.relative_to(source_dir) if file.is_relative_to(source_dir) else file.name
                zf.write(file, arcname=str(arcname))
        target_zip.parent.mkdir(parents=True, exist_ok=True)
        _fsync_path(temp_zip)
        try:
            os.replace(temp_zip, target_zip)
            logger.debug("Wrote zip %s from %s files (%s)", target_zip, len(image_files), source_dir)
            return
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
        partial_path = target_zip.with_suffix(f"{target_zip.suffix}.partial")
        _safe_unlink(partial_path)
        shutil.copy2(temp_zip, partial_path)
        _fsync_path(partial_path)
        os.replace(partial_path, target_zip)
        logger.debug("Wrote zip %s with cross-device fallback (%s)", target_zip, temp_zip.parent)
    except Exception:
        logger.debug("Zip write failed for %s", target_zip, exc_info=True)
        raise
    finally:
        if temp_zip:
            _safe_unlink(temp_zip)
        if partial_path:
            _safe_unlink(partial_path)


def _gather_gallery_files(path: Path, image_exts: Iterable[str], recursive: bool) -> List[Path]:
    if not path.exists():
        return []
    files: List[Path] = []
    if recursive:
        for root, dirs, filenames in os.walk(path):
            dirs.sort()
            filenames.sort()
            for name in filenames:
                candidate = Path(root) / name
                if candidate.is_file() and _ext_in_list(candidate, image_exts):
                    files.append(candidate)
    else:
        for candidate in sorted(path.iterdir()):
            if candidate.is_file() and _ext_in_list(candidate, image_exts):
                files.append(candidate)
    return files


def _gather_sidecars(path: Path, recursive: bool) -> List[Path]:
    if not path.exists():
        return []
    files: List[Path] = []
    if recursive:
        for root, dirs, filenames in os.walk(path):
            dirs.sort()
            filenames.sort()
            for name in filenames:
                candidate = Path(root) / name
                if candidate.is_file() and candidate.suffix.lower() in SIDECAR_EXTS:
                    files.append(candidate)
    else:
        for candidate in sorted(path.iterdir()):
            if candidate.is_file() and candidate.suffix.lower() in SIDECAR_EXTS:
                files.append(candidate)
    return files


def _iter_archives(base_path: Path, archive_exts: Iterable[str]) -> Iterable[Path]:
    for path in sorted(base_path.rglob("*"), key=lambda p: str(p)):
        if path.is_file() and _ext_in_list(path, archive_exts):
            yield path


def _virtual_relpath(rel_path: Path, replicate_nesting: bool) -> Path:
    if replicate_nesting:
        return rel_path
    if len(rel_path.parts) > 1:
        top = rel_path.parts[0]
        return Path(top) / rel_path.name
    return Path(rel_path.name)


def _resolve_output_file(
    rel_file: Path,
    replicate_nesting: bool,
    flatten_enabled: bool,
    flatten_map: Dict[str, str],
) -> tuple[Path, Path]:
    virtual_rel = _virtual_relpath(rel_file, replicate_nesting)
    virtual_target = Path(env_settings.output_root) / virtual_rel
    if not flatten_enabled:
        return virtual_target, virtual_target

    base_name = rel_file.name
    recorded = flatten_map.get(base_name)
    if recorded and recorded != str(rel_file):
        base_name = f"{rel_file.stem}__{_short_hash(str(rel_file))}{rel_file.suffix}"
    flatten_map.setdefault(base_name, str(rel_file))
    physical = Path(env_settings.output_root) / base_name
    return physical, virtual_target


def _append_reason(summary: ScanSummary, reason: str | None):
    if not reason:
        return
    summary.reason_counts[reason] = summary.reason_counts.get(reason, 0) + 1
    if reason in {"SKIP_EXISTING_UNCHANGED", "SKIP_DUPLICATE_SAME_SIGNATURE", "SKIP_DUPLICATE_SAME_SIZE"}:
        summary.skipped_existing += 1


def _update_scan_status(completed: int, planned: int, message: str | None = None, dry_run: bool = True):
    progress = None
    if planned > 0:
        progress = min(1.0, completed / planned)
    set_status("scanning", message=message or "Scanning", progress=progress, meta={"dry_run": dry_run, "completed": completed, "planned": planned})


def _debug_action(action: PlanAction, note: str | None = None):
    if not logger.isEnabledFor(logging.DEBUG):
        return
    logger.debug(
        "Action=%s type=%s decision=%s reason=%s source=%s target=%s virtual=%s note=%s",
        action.action,
        action.type,
        action.decision,
        action.reason_code or action.reason,
        action.source_path,
        action.target_path,
        action.virtual_target,
        note,
    )


def _register_action(action: PlanAction, summary: ScanSummary, actions: List[PlanAction]):
    _append_reason(summary, action.reason_code or action.reason)
    if action.decision == "SKIP":
        summary.skipped += 1
    else:
        summary.planned += 1

    if action.type == "archive" and action.decision not in {"SKIP", "ENSURE_DIR"}:
        summary.archives_to_copy += 1
    if action.type == "gallery" and action.action in {"zip_gallery", "overwrite_zip"} and action.decision in {"ZIP", "UPDATE"}:
        summary.galleries_to_zip += 1
    if action.decision in {"RENAME", "COPY_DUPLICATE"}:
        summary.duplicates += 1
    if action.decision == "UPDATE":
        summary.overwrites += 1

    _debug_action(action)
    actions.append(action)


def _safe_is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _discover_galleries(base_path: Path, data_root: Path, settings) -> tuple[List[GalleryCandidate], List[PlanAction], Sequence[Path]]:
    if not base_path.exists():
        return [], [], []

    dir_meta: Dict[Path, Dict[str, int | bool]] = {}
    for root, dirs, files in os.walk(base_path, topdown=False):
        dirs.sort()
        files.sort()
        current = Path(root)
        direct_images = [f for f in files if _ext_in_list(Path(f), settings.image_extensions)]
        total_images = len(direct_images)
        for d in dirs:
            child = current / d
            child_info = dir_meta.get(child)
            if child_info:
                total_images += int(child_info["total_images"])
        dir_meta[current] = {
            "direct_images": len(direct_images),
            "total_images": total_images,
            "is_leaf": len(dirs) == 0,
        }

    galleries: List[GalleryCandidate] = []
    skips: List[PlanAction] = []
    for path in sorted(dir_meta.keys(), key=lambda p: str(p)):
        info = dir_meta[path]
        rel_dir = path.relative_to(data_root)
        direct_count = int(info["direct_images"])
        total_images = int(info["total_images"])
        qualifies = False
        if direct_count >= settings.min_images_to_be_gallery:
            qualifies = True
        elif settings.leaf_only and info["is_leaf"] and direct_count > 0:
            qualifies = True
        elif (not settings.leaf_only) and settings.consider_images_in_subfolders and total_images >= settings.min_images_to_be_gallery:
            qualifies = True

        if qualifies:
            images = _gather_gallery_files(path, settings.image_extensions, settings.consider_images_in_subfolders)
            signature = _gallery_signature(images)
            galleries.append(
                GalleryCandidate(
                    path=path,
                    rel_dir=rel_dir,
                    images=images,
                    signature=signature,
                    is_leaf=bool(info["is_leaf"]),
                )
            )
        else:
            reason_code = None
            if direct_count == 0 and info["is_leaf"]:
                reason_code = "SKIP_NO_IMAGES"
            elif direct_count > 0 and direct_count < settings.min_images_to_be_gallery:
                reason_code = "SKIP_BELOW_MIN_IMAGES"
            if reason_code:
                skips.append(
                    PlanAction(
                        action="scan_gallery",
                        type="gallery",
                        source_path=str(path),
                        relative_source=str(rel_dir),
                        decision="SKIP",
                        reason=reason_code,
                        reason_code=reason_code,
                    )
                )

    container_dirs: set[Path] = set()
    gallery_paths = [g.path for g in galleries]
    for gal_path in gallery_paths:
        parent = gal_path.parent
        while _safe_is_relative_to(parent, base_path):
            info = dir_meta.get(parent)
            if info and int(info["direct_images"]) == 0:
                container_dirs.add(parent)
            if parent == base_path:
                break
            parent = parent.parent

    logger.debug(
        "Discovered galleries=%d skips=%d containers=%d under %s",
        len(galleries),
        len(skips),
        len(container_dirs),
        base_path,
    )
    return galleries, skips, sorted(container_dirs, key=lambda p: str(p))


def _copy_folder_contents(source_dir: Path, files: List[Path], sidecars: List[Path], target_dir: Path):
    for file in files + sidecars:
        rel = file.relative_to(source_dir)
        dest = target_dir / rel
        _copy_file(file, dest)
    logger.debug("Copied folder contents from %s to %s (files=%d sidecars=%d)", source_dir, target_dir, len(files), len(sidecars))


def get_last_results() -> Dict[str, Optional[ScanResult]]:
    return _last_results


async def perform_scan(session: AsyncSession, dry_run: bool = True) -> ScanResult:
    settings = await get_settings(session)
    output_modes = {mode.strip() for mode in settings.output_mode.split("+")}
    process_galleries = settings.zip_galleries or ("foldercopy" in output_modes)
    summary = ScanSummary()
    actions: List[PlanAction] = []
    completed_ops = 0
    planned_ops = 0

    def _plan_op(message: str):
        nonlocal planned_ops
        planned_ops += 1
        _update_scan_status(completed_ops, planned_ops, message=message, dry_run=dry_run)

    def _complete_op(message: str):
        nonlocal completed_ops
        completed_ops += 1
        _update_scan_status(completed_ops, planned_ops, message=message, dry_run=dry_run)

    logger.debug(
        "Starting scan dry_run=%s output_modes=%s settings=%s",
        dry_run,
        output_modes,
        settings.model_dump(),
    )
    set_status("scanning", message="Scanning sources", progress=0.0, meta={"dry_run": dry_run})

    try:
        result = await session.execute(select(models.Source).where(models.Source.enabled == True))  # noqa: E712
        sources = sorted(result.scalars().all(), key=lambda s: s.path)
        exclusions_result = await session.execute(select(models.Exclusion))
        exclusions = [Path(ex.path) for ex in exclusions_result.scalars().all()]

        data_root = Path(env_settings.data_root)
        duplicates_root = Path(env_settings.duplicates_root)
        duplicates_available = duplicates_root.exists() and duplicates_root.is_dir() and os.access(duplicates_root, os.W_OK)
        flatten_name_map: Dict[str, str] = {}

        global _warned_missing_duplicates
        if settings.duplicates_enabled and not duplicates_available and not _warned_missing_duplicates:
            await log_activity(
                session,
                "WARN",
                "Duplicates directory unavailable; falling back to rename strategy",
                {"path": str(duplicates_root)},
            )
            _warned_missing_duplicates = True
            logger.debug("Duplicates directory unavailable: %s", duplicates_root)

        for source in sources:
            base_path = data_root / source.path
            logger.debug("Scanning source id=%s name=%s path=%s mode=%s", source.id, source.name, base_path, source.scan_mode)
            if not base_path.exists():
                await log_activity(session, "WARN", f"Source path missing: {base_path}", {"source_id": source.id})
                logger.debug("Source path missing, skipping %s", base_path)
                continue

            # process archives
            if source.scan_mode != "folders_only":
                for archive_path in _iter_archives(base_path, settings.archive_extensions):
                    rel_path = archive_path.relative_to(data_root)
                    if any(rel_path.is_relative_to(exc) for exc in exclusions):
                        logger.debug("Skipping excluded archive %s", rel_path)
                        continue
                    physical_target, virtual_target = _resolve_output_file(
                        rel_path,
                        settings.replicate_nesting,
                        settings.lanraragi_flatten,
                        flatten_name_map,
                    )
                    signature = _archive_signature(archive_path)
                    existing_record = await _get_record(session, physical_target)
                    action = PlanAction(
                        action="copy_archive",
                        type="archive",
                        source_path=str(archive_path),
                        target_path=str(physical_target),
                        virtual_target=str(virtual_target),
                        relative_source=str(rel_path),
                        signature=signature,
                        similarity=1.0,
                        decision="COPY",
                        bytes=signature["size"],
                    )

                    if physical_target.exists():
                        is_same = existing_record and existing_record.signature_json and json.loads(existing_record.signature_json) == signature
                        if is_same:
                            action.decision = "SKIP"
                            action.reason = "SKIP_EXISTING_UNCHANGED"
                            action.reason_code = "SKIP_EXISTING_UNCHANGED"
                            if not dry_run:
                                await log_activity(session, "INFO", "Archive unchanged, skipping", action.model_dump())
                                await _touch_record(session, physical_target)
                            _register_action(action, summary, actions)
                            continue

                        if physical_target.stat().st_size == signature["size"]:
                            action.decision = "SKIP"
                            action.reason = "SKIP_DUPLICATE_SAME_SIZE"
                            action.reason_code = "SKIP_DUPLICATE_SAME_SIZE"
                            if not dry_run:
                                await log_activity(session, "INFO", "Archive duplicate size, skipping", action.model_dump())
                                await _touch_record(session, physical_target)
                            _register_action(action, summary, actions)
                            continue

                        alt_target: Path
                        if settings.duplicates_enabled and duplicates_available:
                            alt_target = duplicates_root / rel_path
                            action.decision = "COPY_DUPLICATE"
                            action.target_path = str(alt_target)
                            action.reason = "SKIP_OUTPUT_CONFLICT"
                            action.reason_code = "SKIP_OUTPUT_CONFLICT"
                        else:
                            alt_target = physical_target.with_name(f"{physical_target.stem}_DUP_{int(time.time())}{physical_target.suffix}")
                            action.decision = "RENAME"
                            action.target_path = str(alt_target)
                            action.reason = "SKIP_OUTPUT_CONFLICT"
                            action.reason_code = "SKIP_OUTPUT_CONFLICT"
                        if not dry_run:
                            _plan_op("Copying archive duplicate")
                            _copy_file(archive_path, alt_target)
                            _complete_op("Copying archive duplicate")
                            await _upsert_record(session, alt_target, archive_path, "archive", signature, virtual_target_path=virtual_target)
                            await log_activity(session, "INFO", "Archive duplicated", action.model_dump())
                        _register_action(action, summary, actions)
                        continue

                    if not dry_run:
                        _plan_op("Copying archive")
                        _copy_file(archive_path, physical_target)
                        _complete_op("Copying archive")
                        await _upsert_record(session, physical_target, archive_path, "archive", signature, virtual_target_path=virtual_target)
                        await log_activity(session, "INFO", "Archive copied", action.model_dump())
                    _register_action(action, summary, actions)

            if not process_galleries or source.scan_mode == "archives_only":
                continue

            galleries, skip_actions, container_dirs = _discover_galleries(base_path, data_root, settings)
            for skip_action in skip_actions:
                _register_action(skip_action, summary, actions)

            # ensure container directories exist for nested outputs
            if (settings.replicate_nesting and not settings.lanraragi_flatten) or ("foldercopy" in output_modes):
                for container in container_dirs:
                    rel_dir = container.relative_to(data_root)
                    target_dir = Path(env_settings.output_root) / _virtual_relpath(rel_dir, settings.replicate_nesting)
                    ensure_action = PlanAction(
                        action="ensure_output_dir",
                        type="container",
                        source_path=str(container),
                        target_path=str(target_dir),
                        relative_source=str(rel_dir),
                        decision="ENSURE_DIR",
                    )
                    if not dry_run:
                        target_dir.mkdir(parents=True, exist_ok=True)
                    _register_action(ensure_action, summary, actions)

            for gallery in sorted(galleries, key=lambda g: str(g.rel_dir)):
                rel_dir = gallery.rel_dir
                if any(rel_dir.is_relative_to(exc) for exc in exclusions):
                    logger.debug("Skipping excluded gallery %s", rel_dir)
                    continue
                sidecars: List[Path] = []
                if settings.copy_sidecars:
                    sidecars = _gather_sidecars(gallery.path, settings.consider_images_in_subfolders)

                modes_to_apply = []
                if "zip" in output_modes:
                    modes_to_apply.append("zip")
                if "foldercopy" in output_modes:
                    modes_to_apply.append("foldercopy")

                # skip galleries with no images
                if not gallery.images:
                    skip_action = PlanAction(
                        action="scan_gallery",
                        type="gallery",
                        source_path=str(gallery.path),
                        relative_source=str(rel_dir),
                        decision="SKIP",
                        reason="SKIP_NO_IMAGES",
                        reason_code="SKIP_NO_IMAGES",
                    )
                    _register_action(skip_action, summary, actions)
                    continue

                for mode in modes_to_apply:
                    if mode == "zip":
                        extension = settings.archive_extension_for_galleries.lstrip(".")
                        rel_file = rel_dir.parent / f"{rel_dir.name}.{extension}"
                        target_path, virtual_target = _resolve_output_file(
                            rel_file,
                            settings.replicate_nesting,
                            settings.lanraragi_flatten,
                            flatten_name_map,
                        )
                        existing_record = await _get_record(session, target_path)
                        action = PlanAction(
                            action="zip_gallery",
                            type="gallery",
                            source_path=str(gallery.path),
                            target_path=str(target_path),
                            virtual_target=str(virtual_target),
                            relative_source=str(rel_dir),
                            signature=gallery.signature,
                            similarity=float(fuzz.ratio(gallery.path.name, rel_dir.name)) / 100.0,
                            decision="ZIP",
                            bytes=gallery.signature.get("total_image_bytes"),
                        )

                        if target_path.exists():
                            same_signature = existing_record and existing_record.signature_json and json.loads(existing_record.signature_json) == gallery.signature
                            if same_signature:
                                action.decision = "SKIP"
                                action.reason = "SKIP_DUPLICATE_SAME_SIGNATURE"
                                action.reason_code = "SKIP_DUPLICATE_SAME_SIGNATURE"
                                if not dry_run:
                                    await log_activity(session, "INFO", "Gallery unchanged, skip", action.model_dump())
                                    await _touch_record(session, target_path)
                                _register_action(action, summary, actions)
                                continue

                            if not settings.update_gallery_zips:
                                alt_target: Path
                                if settings.duplicates_enabled and duplicates_available:
                                    alt_target = duplicates_root / rel_dir / f"{rel_dir.name}.{extension}"
                                    action.decision = "COPY_DUPLICATE"
                                else:
                                    alt_target = target_path.with_name(f"{target_path.stem}_DUP_{int(time.time())}{target_path.suffix}")
                                    action.decision = "RENAME"
                                action.target_path = str(alt_target)
                                action.reason = "SKIP_OUTPUT_CONFLICT"
                                action.reason_code = "SKIP_OUTPUT_CONFLICT"
                                if not dry_run:
                                    _plan_op("Writing duplicate gallery zip")
                                    _write_zip(gallery.path, gallery.images, alt_target)
                                    _complete_op("Writing duplicate gallery zip")
                                    await _upsert_record(
                                        session,
                                        alt_target,
                                        gallery.path,
                                        "galleryzip",
                                        gallery.signature,
                                        virtual_target_path=virtual_target,
                                    )
                                    await log_activity(session, "INFO", "Gallery duplicate written", action.model_dump())
                                _register_action(action, summary, actions)
                                continue

                            action.action = "overwrite_zip"
                            action.decision = "UPDATE"
                            if not dry_run:
                                _plan_op("Updating gallery zip")
                                _write_zip(gallery.path, gallery.images, target_path)
                                _complete_op("Updating gallery zip")
                                await _upsert_record(
                                    session,
                                    target_path,
                                    gallery.path,
                                    "galleryzip",
                                    gallery.signature,
                                    virtual_target_path=virtual_target,
                                )
                                await log_activity(session, "INFO", "Gallery zip updated", action.model_dump())
                            _register_action(action, summary, actions)
                            continue

                        if not dry_run:
                            _plan_op("Writing gallery zip")
                            _write_zip(gallery.path, gallery.images, target_path)
                            _complete_op("Writing gallery zip")
                            await _upsert_record(
                                session,
                                target_path,
                                gallery.path,
                                "galleryzip",
                                gallery.signature,
                                virtual_target_path=virtual_target,
                            )
                            await log_activity(session, "INFO", "Gallery zipped", action.model_dump())
                        _register_action(action, summary, actions)

                    if mode == "foldercopy":
                        target_dir = Path(env_settings.output_root) / _virtual_relpath(rel_dir, settings.replicate_nesting)
                        existing_record = await _get_record(session, target_dir)
                        action = PlanAction(
                            action="foldercopy_gallery",
                            type="gallery",
                            source_path=str(gallery.path),
                            target_path=str(target_dir),
                            relative_source=str(rel_dir),
                            signature=gallery.signature,
                            decision="FOLDERCOPY",
                            bytes=gallery.signature.get("total_image_bytes"),
                        )

                        same_signature = existing_record and existing_record.signature_json and json.loads(existing_record.signature_json) == gallery.signature
                        if target_dir.exists() and same_signature:
                            action.decision = "SKIP"
                            action.reason = "SKIP_DUPLICATE_SAME_SIGNATURE"
                            action.reason_code = "SKIP_DUPLICATE_SAME_SIGNATURE"
                            if not dry_run:
                                await log_activity(session, "INFO", "Folder copy unchanged, skip", action.model_dump())
                                await _touch_record(session, target_dir)
                            _register_action(action, summary, actions)
                            continue

                        if target_dir.exists() and not settings.update_gallery_zips:
                            action.decision = "SKIP"
                            action.reason = "SKIP_OUTPUT_CONFLICT"
                            action.reason_code = "SKIP_OUTPUT_CONFLICT"
                            _register_action(action, summary, actions)
                            continue

                        if not dry_run:
                            target_dir.mkdir(parents=True, exist_ok=True)
                            _plan_op("Copying folder")
                            _copy_folder_contents(gallery.path, gallery.images, sidecars, target_dir)
                            _complete_op("Copying folder")
                            await _upsert_record(
                                session,
                                target_dir,
                                gallery.path,
                                "foldercopy",
                                gallery.signature,
                                virtual_target_path=target_dir,
                            )
                            await log_activity(session, "INFO", "Folder copied", action.model_dump())
                        _register_action(action, summary, actions)
    except Exception:
        set_status("error", message="Scan failed", progress=None, meta={"dry_run": dry_run})
        logger.debug("Scan failed", exc_info=True)
        raise

    result_payload = ScanResult(summary=summary, actions=actions)
    logger.debug(
        "Completed scan dry_run=%s planned=%d skipped=%d actions=%d",
        dry_run,
        summary.planned,
        summary.skipped,
        len(actions),
    )
    _last_results["dryrun" if dry_run else "run"] = result_payload
    set_status("standby", message="Idle", progress=None, meta={"last_run": "dryrun" if dry_run else "run"})
    return result_payload


async def compute_diff(session: AsyncSession) -> DiffResult:
    settings = await get_settings(session)
    output_modes = {mode.strip() for mode in settings.output_mode.split("+")}
    process_galleries = settings.zip_galleries or ("foldercopy" in output_modes)
    data_root = Path(env_settings.data_root)
    flatten_name_map: Dict[str, str] = {}

    current_items: Dict[str, Dict[str, object]] = {}

    result = await session.execute(select(models.Source).where(models.Source.enabled == True))  # noqa: E712
    sources = sorted(result.scalars().all(), key=lambda s: s.path)

    logger.debug("Computing diff output_modes=%s settings=%s", output_modes, settings.model_dump())

    for source in sources:
        base_path = data_root / source.path
        if not base_path.exists():
            logger.debug("Diff skip missing source path %s", base_path)
            continue

        if source.scan_mode != "folders_only":
            for archive_path in _iter_archives(base_path, settings.archive_extensions):
                rel_path = archive_path.relative_to(data_root)
                physical_target, virtual_target = _resolve_output_file(
                    rel_path,
                    settings.replicate_nesting,
                    settings.lanraragi_flatten,
                    flatten_name_map,
                )
                current_items[str(physical_target)] = {
                    "virtual_target": str(virtual_target),
                    "source_path": str(archive_path),
                    "type": "archive",
                    "signature": _archive_signature(archive_path),
                }

        if not process_galleries or source.scan_mode == "archives_only":
            continue

        galleries, _, _ = _discover_galleries(base_path, data_root, settings)
        for gallery in galleries:
            rel_dir = gallery.rel_dir
            if "zip" in output_modes:
                extension = settings.archive_extension_for_galleries.lstrip(".")
                rel_file = rel_dir.parent / f"{rel_dir.name}.{extension}"
                physical_target, virtual_target = _resolve_output_file(
                    rel_file,
                    settings.replicate_nesting,
                    settings.lanraragi_flatten,
                    flatten_name_map,
                )
                current_items[str(physical_target)] = {
                    "virtual_target": str(virtual_target),
                    "source_path": str(gallery.path),
                    "type": "galleryzip",
                    "signature": gallery.signature,
                }

            if "foldercopy" in output_modes:
                target_dir = Path(env_settings.output_root) / _virtual_relpath(rel_dir, settings.replicate_nesting)
                current_items[str(target_dir)] = {
                    "virtual_target": str(target_dir),
                    "source_path": str(gallery.path),
                    "type": "foldercopy",
                    "signature": gallery.signature,
                }

    existing_records = (await session.execute(select(models.ArchiveRecord))).scalars().all()
    record_map = {rec.target_path: rec for rec in existing_records}
    new_items: List[DiffItem] = []
    changed_items: List[DiffItem] = []
    unchanged_items: List[DiffItem] = []
    missing_items: List[DiffItem] = []

    for target, item in current_items.items():
        record = record_map.get(target)
        if not record:
            new_items.append(
                DiffItem(
                    status="new",
                    target_path=target,
                    virtual_target_path=item.get("virtual_target"),
                    source_path=item.get("source_path"),
                    type=str(item.get("type", "unknown")),
                    signature=item.get("signature"),
                )
            )
            continue

        record_sig = json.loads(record.signature_json or "{}")
        if record_sig == item.get("signature"):
            unchanged_items.append(
                DiffItem(
                    status="unchanged",
                    target_path=target,
                    virtual_target_path=record.virtual_target_path or item.get("virtual_target"),
                    source_path=record.source_path,
                    type=record.type,
                    signature=item.get("signature"),
                )
            )
        else:
            changed_items.append(
                DiffItem(
                    status="changed",
                    target_path=target,
                    virtual_target_path=record.virtual_target_path or item.get("virtual_target"),
                    source_path=record.source_path,
                    type=record.type,
                    signature=item.get("signature"),
                )
            )

    for record in existing_records:
        source_path = Path(record.source_path)
        if not source_path.exists():
            missing_items.append(
                DiffItem(
                    status="missing",
                    target_path=record.target_path,
                    virtual_target_path=record.virtual_target_path,
                    source_path=record.source_path,
                    type=record.type,
                    signature=json.loads(record.signature_json or "{}"),
                )
            )

    logger.debug(
        "Diff result new=%d changed=%d missing=%d unchanged=%d",
        len(new_items),
        len(changed_items),
        len(missing_items),
        len(unchanged_items),
    )

    return DiffResult(new=new_items, changed=changed_items, missing=missing_items, unchanged=unchanged_items)
