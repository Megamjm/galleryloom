import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import FsDir, FsList, FsRoot
from app.core.config import settings as env_settings

router = APIRouter(prefix="/fs", tags=["filesystem"])

MAX_ENTRIES = 500


def _normalize_root(root: str) -> Path:
    normalized = Path(root).resolve()
    for allowed in env_settings.allowed_browse_roots:
        if normalized == Path(allowed).resolve():
            return normalized
    raise HTTPException(status_code=403, detail="Root not allowed")


def _resolve_browse_path(root: Path, subpath: str | None) -> Path:
    rel = Path(subpath) if subpath else Path(".")
    if rel.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be relative to the selected root")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path must remain within the selected root")
    return candidate


def _list_dirs(root: Path, target: Path) -> tuple[list[FsDir], bool]:
    dirs: list[FsDir] = []
    truncated = False
    try:
        with os.scandir(target) as entries:
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                child = Path(entry.path).resolve()
                if not child.is_relative_to(root):
                    continue
                rel = child.relative_to(root).as_posix()
                dirs.append(FsDir(name=entry.name, path=rel))
                if len(dirs) >= MAX_ENTRIES:
                    truncated = True
                    break
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
    dirs.sort(key=lambda d: d.name.lower())
    return dirs, truncated


@router.get("/roots", response_model=list[FsRoot])
async def list_roots():
    roots: list[FsRoot] = []
    for raw in env_settings.allowed_browse_roots:
        resolved = Path(raw).resolve()
        roots.append(FsRoot(path=str(resolved), available=resolved.exists() and resolved.is_dir()))
    return roots


@router.get("/list", response_model=FsList)
async def list_directory(root: str = Query(...), path: str = Query(default="")):
    resolved_root = _normalize_root(root)
    if not resolved_root.exists():
        raise HTTPException(status_code=404, detail="Root unavailable")
    if not resolved_root.is_dir():
        raise HTTPException(status_code=400, detail="Root must be a directory")
    target = _resolve_browse_path(resolved_root, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Directory not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")
    dirs, truncated = _list_dirs(resolved_root, target)
    rel = target.relative_to(resolved_root)
    rel_str = rel.as_posix() if str(rel) != "." else ""
    return FsList(root=str(resolved_root), path=rel_str, abs=str(target), dirs=dirs, truncated=truncated)
