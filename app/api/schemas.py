from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

class SourceCreate(BaseModel):
    name: str
    path: str
    enabled: bool = True
    scan_mode: Literal["both", "archives_only", "folders_only"] = "both"

class SourceUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    enabled: Optional[bool] = None
    scan_mode: Optional[Literal["both", "archives_only", "folders_only"]] = None

class SourceOut(BaseModel):
    id: int
    name: str
    path: str
    enabled: bool
    scan_mode: str
    created_at: datetime

    class Config:
        from_attributes = True

class SettingsPayload(BaseModel):
    zip_galleries: bool
    update_gallery_zips: bool
    replicate_nesting: bool
    leaf_only: bool
    consider_images_in_subfolders: bool
    output_mode: Literal["zip", "foldercopy", "zip+foldercopy"]
    copy_sidecars: bool
    lanraragi_flatten: bool
    archive_extension_for_galleries: Literal["zip", "cbz"]
    debug_logging: bool
    auto_scan_enabled: bool
    auto_scan_interval_minutes: int = Field(ge=1)
    duplicates_enabled: bool
    min_images_to_be_gallery: int = Field(ge=1)
    archive_extensions: List[str]
    image_extensions: List[str]

class SettingsUpdate(BaseModel):
    zip_galleries: Optional[bool] = None
    update_gallery_zips: Optional[bool] = None
    replicate_nesting: Optional[bool] = None
    leaf_only: Optional[bool] = None
    consider_images_in_subfolders: Optional[bool] = None
    output_mode: Optional[Literal["zip", "foldercopy", "zip+foldercopy"]] = None
    copy_sidecars: Optional[bool] = None
    lanraragi_flatten: Optional[bool] = None
    archive_extension_for_galleries: Optional[Literal["zip", "cbz"]] = None
    debug_logging: Optional[bool] = None
    auto_scan_enabled: Optional[bool] = None
    auto_scan_interval_minutes: Optional[int] = Field(default=None, ge=1)
    duplicates_enabled: Optional[bool] = None
    min_images_to_be_gallery: Optional[int] = Field(default=None, ge=1)
    archive_extensions: Optional[List[str]] = None
    image_extensions: Optional[List[str]] = None

class SettingsOut(SettingsPayload):
    updated_at: Optional[datetime] = None

class PlanAction(BaseModel):
    action: str
    type: Optional[str] = None
    source_path: str
    target_path: Optional[str] = None
    virtual_target: Optional[str] = None
    relative_source: Optional[str] = None
    reason: Optional[str] = None
    reason_code: Optional[str] = None
    decision: Optional[str] = None
    signature: Optional[Dict[str, Any]] = None
    similarity: Optional[float] = None
    bytes: Optional[int] = None

class ScanSummary(BaseModel):
    archives_to_copy: int = 0
    galleries_to_zip: int = 0
    skipped_existing: int = 0
    duplicates: int = 0
    overwrites: int = 0
    planned: int = 0
    skipped: int = 0
    reason_counts: Dict[str, int] = Field(default_factory=dict)

class ScanResult(BaseModel):
    summary: ScanSummary
    actions: List[PlanAction]

class ActivityOut(BaseModel):
    ts: datetime
    level: str
    message: str
    payload_json: str

    class Config:
        from_attributes = True


class DiskInfo(BaseModel):
    path: str
    total_bytes: int
    free_bytes: int
    available_bytes: int


class SystemInfo(BaseModel):
    data_root: str
    output_root: str
    config_root: str
    duplicates_root: str
    tmp_root: str
    temp_dir: Optional[str] = None
    browse_roots: List[str]
    puid: Optional[int] = None
    pgid: Optional[int] = None
    duplicates_enabled: bool
    settings: SettingsOut
    disk_output: DiskInfo
    disk_config: DiskInfo
    version: str
    commit: Optional[str] = None


class DiffItem(BaseModel):
    status: Literal["new", "changed", "missing", "unchanged"]
    target_path: str
    virtual_target_path: Optional[str] = None
    source_path: Optional[str] = None
    type: str
    signature: Optional[Dict[str, Any]] = None


class DiffResult(BaseModel):
    new: List[DiffItem]
    changed: List[DiffItem]
    missing: List[DiffItem]
    unchanged: List[DiffItem]


class LastScans(BaseModel):
    dryrun: Optional[ScanResult] = None
    run: Optional[ScanResult] = None


class FsRoot(BaseModel):
    path: str
    available: bool


class FsDir(BaseModel):
    name: str
    path: str


class FsList(BaseModel):
    root: str
    path: str
    abs: str
    dirs: List[FsDir]
    truncated: bool = False
