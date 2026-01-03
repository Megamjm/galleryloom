from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(Text)  # must be under /data
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    scan_mode: Mapped[str] = mapped_column(String(50), default="both")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class SettingsRow(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zip_galleries: Mapped[bool] = mapped_column(Boolean, default=True)
    update_gallery_zips: Mapped[bool] = mapped_column(Boolean, default=False)
    replicate_nesting: Mapped[bool] = mapped_column(Boolean, default=True)
    leaf_only: Mapped[bool] = mapped_column(Boolean, default=True)
    consider_images_in_subfolders: Mapped[bool] = mapped_column(Boolean, default=False)
    output_mode: Mapped[str] = mapped_column(String(20), default="zip")  # zip | foldercopy | zip+foldercopy
    copy_sidecars: Mapped[bool] = mapped_column(Boolean, default=False)
    lanraragi_flatten: Mapped[bool] = mapped_column(Boolean, default=False)
    archive_extension_for_galleries: Mapped[str] = mapped_column(String(10), default="zip")
    debug_logging: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_scan_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_scan_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    duplicates_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    min_images_to_be_gallery: Mapped[int] = mapped_column(Integer, default=3)
    archive_extensions: Mapped[str] = mapped_column(Text, default='["zip","cbz"]')
    image_extensions: Mapped[str] = mapped_column(
        Text, default='["jpg","jpeg","png","webp","gif","bmp","jfif"]'
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

class ArchiveRecord(Base):
    __tablename__ = "archive_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_path: Mapped[str] = mapped_column(Text, unique=True, index=True)
    virtual_target_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_path: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(50))  # archive | galleryzip
    signature_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Activity(Base):
    __tablename__ = "activity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    level: Mapped[str] = mapped_column(String(20), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
