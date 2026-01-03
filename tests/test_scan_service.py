import errno
import os
import tempfile
import zipfile
from pathlib import Path
from unittest import TestCase, mock

from app.core.config import settings as env_settings
from app.services import scan_service


class WriteZipTests(TestCase):
    def setUp(self):
        self._orig_tmp_root = env_settings.tmp_root
        self._orig_temp_dir = getattr(env_settings, "temp_dir", None)

    def tearDown(self):
        env_settings.tmp_root = self._orig_tmp_root
        env_settings.temp_dir = self._orig_temp_dir

    def test_write_zip_handles_exdev_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir) / "out"
            gallery_dir = Path(tmpdir) / "gallery"
            gallery_dir.mkdir(parents=True, exist_ok=True)
            img = gallery_dir / "image.txt"
            img.write_text("demo")

            env_settings.tmp_root = str(Path(tmpdir) / "tmp")
            Path(env_settings.tmp_root).mkdir(parents=True, exist_ok=True)
            target_zip = target_dir / "archive.zip"

            replace_calls = {"count": 0}
            real_replace = os.replace

            def fake_replace(src, dst):
                replace_calls["count"] += 1
                if replace_calls["count"] == 1:
                    raise OSError(errno.EXDEV, "Invalid cross-device link")
                return real_replace(src, dst)

            with mock.patch("os.replace", side_effect=fake_replace):
                scan_service._write_zip(gallery_dir, [img], target_zip)

            self.assertTrue(target_zip.exists())
            self.assertEqual(replace_calls["count"], 2)
            self.assertEqual(list(target_dir.glob("*.partial")), [])
            with zipfile.ZipFile(target_zip, "r") as zf:
                self.assertIn("image.txt", zf.namelist())

    def test_write_zip_prefers_target_directory_temp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir) / "dest"
            gallery_dir = Path(tmpdir) / "gallery2"
            gallery_dir.mkdir(parents=True, exist_ok=True)
            img = gallery_dir / "image2.txt"
            img.write_text("demo")

            env_settings.tmp_root = str(Path(tmpdir) / "tmp")
            env_settings.temp_dir = None
            target_zip = target_dir / "gallery.zip"

            real_ntf = scan_service.tempfile.NamedTemporaryFile
            created_dirs: list[Path] = []

            def recording_ntf(*args, **kwargs):
                created_dirs.append(Path(kwargs.get("dir")).resolve())
                return real_ntf(*args, **kwargs)

            with mock.patch("app.services.scan_service.tempfile.NamedTemporaryFile", side_effect=recording_ntf):
                scan_service._write_zip(gallery_dir, [img], target_zip)

            self.assertTrue(created_dirs)
            self.assertEqual(created_dirs[0], target_zip.parent.resolve())
            self.assertTrue(target_zip.exists())
