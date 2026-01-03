import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _write_dummy_images(folder: Path, count: int, prefix: str = "img"):
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        (folder / f"{prefix}{i}.jpg").write_bytes(b"test")


def _setup_env(base_dir: Path):
    data_root = base_dir / "data"
    output_root = base_dir / "output"
    config_root = base_dir / "config"
    duplicates_root = base_dir / "duplicates"
    tmp_root = config_root / "tmp"
    for p in [data_root, output_root, config_root, duplicates_root, tmp_root]:
        p.mkdir(parents=True, exist_ok=True)

    os.environ["GLOOM_DATA_ROOT"] = str(data_root)
    os.environ["GLOOM_OUTPUT_ROOT"] = str(output_root)
    os.environ["GLOOM_CONFIG_ROOT"] = str(config_root)
    os.environ["GLOOM_DUPLICATES_ROOT"] = str(duplicates_root)
    os.environ["GLOOM_TMP_ROOT"] = str(tmp_root)

    return data_root, output_root


async def _prepare_sources(session):
    from sqlalchemy import select
    from app.core import models

    existing = (await session.execute(select(models.Source).where(models.Source.name == "Test Library"))).scalars().first()
    if not existing:
        session.add(models.Source(name="Test Library", path="Library", enabled=True))
        await session.commit()


async def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        data_root, output_root = _setup_env(base_dir)

        # Build nested gallery tree
        _write_dummy_images(data_root / "Library/SeriesA/Arc1/Chapter1", 3)
        _write_dummy_images(data_root / "Library/SeriesA/Arc1/Chapter1/SubLeaf", 2)
        _write_dummy_images(data_root / "Library/SeriesB/LeafSolo", 1)

        from app.core.db import init_db, SessionLocal
        from app.api.schemas import SettingsUpdate
        from app.services.settings_service import update_settings
        from app.services.scan_service import perform_scan

        await init_db()
        async with SessionLocal() as session:
            await _prepare_sources(session)
            await update_settings(
                session,
                SettingsUpdate(
                    zip_galleries=True,
                    update_gallery_zips=True,
                    replicate_nesting=True,
                    leaf_only=True,
                    consider_images_in_subfolders=False,
                    output_mode="zip",
                    copy_sidecars=False,
                ),
            )
            dry_plan = await perform_scan(session, dry_run=True)
            assert any(act.decision == "ZIP" and act.type == "gallery" for act in dry_plan.actions), "Expected gallery zip action in dry-run"

            await perform_scan(session, dry_run=False)

        expected_zip = output_root / "Library/SeriesA/Arc1/Chapter1.zip"
        assert expected_zip.exists(), f"Expected zip at {expected_zip}"

        # Mutate gallery to force UPDATE
        (data_root / "Library/SeriesA/Arc1/Chapter1/new4.jpg").write_bytes(b"new")

        async with SessionLocal() as session:
            update_plan = await perform_scan(session, dry_run=True)
            assert any(
                act.decision == "UPDATE" and "Chapter1" in (act.target_path or "")
                for act in update_plan.actions
            ), "Expected UPDATE decision after mutation"

        print("Self-test passed ✓")


if __name__ == "__main__":
    asyncio.run(main())
