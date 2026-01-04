import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    DiscoveredGallery,
    DuplicateGroup,
    GalleryOutput,
    GalleryPreview,
    ImportResult,
)
from app.core import models
from app.core.config import settings as env_settings
from app.core.db import get_session
from app.services.scan_service import (
    _discover_galleries,
    _gallery_signature,
    _gather_gallery_files,
    _resolve_output_file,
    _upsert_record,
    _write_zip,
)
from app.services.settings_service import get_settings
from app.services.duplicates_service import load_acknowledged, mark_acknowledged
from app.services.status_service import set_status

router = APIRouter(prefix="/galleries", tags=["galleries"])


def _stat_file(path: Path) -> tuple[bool, int | None, datetime | None]:
    try:
        st = path.stat()
        return True, st.st_size, datetime.fromtimestamp(st.st_mtime)
    except FileNotFoundError:
        return False, None, None
    except Exception:
        return False, None, None


@router.get("/output", response_model=List[GalleryOutput])
async def list_output_galleries(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(models.ArchiveRecord).where(models.ArchiveRecord.type.in_(["galleryzip", "foldercopy"]))
    )
    records = result.scalars().all()
    items: list[GalleryOutput] = []
    for rec in records:
        path = Path(rec.target_path)
        exists, size, mtime = _stat_file(path)
        items.append(
            GalleryOutput(
                path=str(path),
                virtual_path=rec.virtual_target_path,
                record_type=rec.type,  # type: ignore[arg-type]
                exists=exists,
                size=size,
                mtime=mtime,
                last_seen_at=rec.last_seen_at,
            )
        )
    return sorted(items, key=lambda i: i.path.lower())


@router.get("/discovered", response_model=List[DiscoveredGallery])
async def list_discovered_galleries(session: AsyncSession = Depends(get_session)):
    settings = await get_settings(session)
    result = await session.execute(select(models.Source).where(models.Source.enabled == True))  # noqa: E712
    sources = result.scalars().all()
    data_root = Path(env_settings.data_root)
    discovered: list[DiscoveredGallery] = []
    for source in sources:
        base_path = data_root / source.path
        galleries, _, _ = _discover_galleries(base_path, data_root, settings)
        for gal in galleries:
            sig = gal.signature
            discovered.append(
                DiscoveredGallery(
                    source_name=source.name,
                    source_path=str(base_path),
                    gallery_path=str(gal.path),
                    relative_path=str(gal.rel_dir),
                    image_count=int(sig.get("image_count", 0)),
                    total_image_bytes=int(sig.get("total_image_bytes", 0)),
                    newest_mtime=float(sig.get("newest_mtime", 0)),
                    is_leaf=gal.is_leaf,
                )
            )
    return sorted(discovered, key=lambda g: g.gallery_path.lower())


def _safe_under_output(path: Path) -> Path:
    root = Path(env_settings.output_root).resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path must be under output root")
    return resolved


@router.get("/preview", response_model=GalleryPreview)
async def preview_gallery(path: str):
    target = _safe_under_output(Path(path))
    if not target.exists():
        return GalleryPreview(path=str(target), kind="missing", exists=False)
    kind = "file"
    entries: list[str] = []
    truncated = False
    size = None
    mtime = None
    try:
        st = target.stat()
        size = st.st_size
        mtime = datetime.fromtimestamp(st.st_mtime)
    except Exception:
        pass
    if target.is_dir():
        kind = "folder"
        for entry in sorted(target.iterdir()):
            entries.append(entry.name + ("/" if entry.is_dir() else ""))
            if len(entries) >= 50:
                truncated = True
                break
    elif target.suffix.lower() in {".zip", ".cbz"}:
        kind = "zip"
        try:
            with zipfile.ZipFile(target, "r") as zf:
                for name in zf.namelist()[:50]:
                    entries.append(name)
                if len(zf.namelist()) > len(entries):
                    truncated = True
        except Exception:
            entries.append("[unable to read archive]")
    return GalleryPreview(path=str(target), kind=kind, exists=True, size=size, mtime=mtime, entries=entries, truncated=truncated)


def _signature_key(rec: models.ArchiveRecord) -> str:
    try:
        sig = json.loads(rec.signature_json or "{}")
        return json.dumps(sig, sort_keys=True)
    except Exception:
        return ""


@router.get("/duplicates", response_model=List[DuplicateGroup])
async def list_duplicates(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(models.ArchiveRecord).where(models.ArchiveRecord.type.in_(["galleryzip", "foldercopy"])))
    records = result.scalars().all()
    groups: dict[str, list[models.ArchiveRecord]] = {}
    for rec in records:
        key = _signature_key(rec)
        if not key:
            continue
        groups.setdefault(key, []).append(rec)
    acked = load_acknowledged()
    payload: list[DuplicateGroup] = []
    for key, recs in groups.items():
        if len(recs) < 2:
            continue
        entries = []
        for rec in recs:
            exists = Path(rec.target_path).exists()
            try:
                signature = json.loads(rec.signature_json or "{}")
            except Exception:
                signature = None
            entries.append(
                {
                    "path": rec.target_path,
                    "virtual_path": rec.virtual_target_path,
                    "record_type": rec.type,
                    "signature": signature,
                    "last_seen_at": rec.last_seen_at,
                    "exists": exists,
                }
            )
        payload.append(
            DuplicateGroup(
                signature_key=key,
                count=len(entries),
                entries=entries,  # type: ignore[arg-type]
                acknowledged=key in acked,
            )
        )
    payload.sort(key=lambda g: g.count, reverse=True)
    return payload


@router.post("/duplicates/ack")
async def ack_duplicates(keys: List[str] = Body(...)):
    mark_acknowledged(keys)
    return {"status": "ok", "acknowledged": keys}


def _sanitize_rel(path: str) -> Path:
    cleaned = path.strip().lstrip("/")
    candidate = Path(cleaned)
    if ".." in candidate.parts:
        raise HTTPException(status_code=400, detail="Path must not contain ..")
    return candidate


@router.post("/import/upload", response_model=ImportResult)
async def import_upload(
    file: UploadFile = File(...),
    target_subdir: str = Form(default=""),
    extract: bool = Form(default=False),
):
    output_root = Path(env_settings.output_root)
    subdir = _sanitize_rel(target_subdir)
    dest_dir = (output_root / subdir).resolve()
    _safe_under_output(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(file.filename or "upload").name
    dest_path = dest_dir / filename
    if dest_path.exists():
        return ImportResult(saved_path=str(dest_path), skipped=True, reason="File already exists")
    with dest_path.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    if extract and dest_path.suffix.lower() in {".zip", ".cbz"}:
        extract_dir = dest_dir / dest_path.stem
        if extract_dir.exists():
            return ImportResult(saved_path=str(dest_path), skipped=True, reason="Extract target exists")
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest_path, "r") as zf:
            zf.extractall(extract_dir)
        return ImportResult(saved_path=str(dest_path), extracted=True, extract_path=str(extract_dir))
    return ImportResult(saved_path=str(dest_path))


@router.post("/update")
async def update_gallery(relative_path: str, session: AsyncSession = Depends(get_session)):
    rel = _sanitize_rel(relative_path)
    source_dir = Path(env_settings.data_root) / rel
    if not source_dir.exists() or not source_dir.is_dir():
        raise HTTPException(status_code=404, detail="Source directory not found")
    settings = await get_settings(session)
    images = _gather_gallery_files(source_dir, settings.image_extensions, settings.consider_images_in_subfolders)
    if not images:
        raise HTTPException(status_code=400, detail="No images to zip in this folder")
    signature = _gallery_signature(images)
    extension = settings.archive_extension_for_galleries.lstrip(".")
    rel_file = rel.parent / f"{rel.name}.{extension}"
    flatten_name_map: dict[str, str] = {}
    target_path, virtual_target = _resolve_output_file(rel_file, settings.replicate_nesting, settings.lanraragi_flatten, flatten_name_map)
    set_status("scanning", message=f"Updating {rel}", progress=None, meta={"manual_update": True})
    _write_zip(source_dir, images, target_path)
    await _upsert_record(session, target_path, source_dir, "galleryzip", signature, virtual_target_path=virtual_target)
    set_status("standby", message="Idle", progress=None, meta={"last_update": str(rel)})
    return {"status": "updated", "target_path": str(target_path), "virtual_target": str(virtual_target), "signature": signature}
