from typing import List, Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GLOOM_", extra="ignore")

    # container paths
    data_root: str = Field("/data")
    output_root: str = Field("/output")
    config_root: str = Field("/config")
    duplicates_root: str = Field("/duplicates")
    tmp_root: str = Field("/config/tmp")

    # permissions / ownership
    puid: Optional[int] = Field(default=None, validation_alias=AliasChoices("PUID", "GLOOM_PUID"))
    pgid: Optional[int] = Field(default=None, validation_alias=AliasChoices("PGID", "GLOOM_PGID"))

    # behavior toggles
    zip_galleries: bool = True
    update_gallery_zips: bool = False
    use_hardlinks: bool = False  # usually off for Unraid user shares

    # detection / planner defaults
    archive_extensions: List[str] = ["zip", "cbz"]
    image_extensions: List[str] = ["jpg", "jpeg", "png", "webp", "gif", "bmp", "jfif"]
    min_images_to_be_gallery: int = 3
    replicate_nesting: bool = True
    leaf_only: bool = True
    consider_images_in_subfolders: bool = False
    output_mode: str = "zip"
    copy_sidecars: bool = False
    lanraragi_flatten: bool = False
    archive_extension_for_galleries: str = "zip"
    debug_logging: bool = False
    auto_scan_enabled: bool = True
    auto_scan_interval_minutes: int = 30


APP_VERSION = "0.2.0"

settings = Settings()
