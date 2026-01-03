import tempfile
from pathlib import Path
from unittest import TestCase

from fastapi import HTTPException

from app.api import routes_fs
from app.core.config import settings as env_settings


class BrowsePathTests(TestCase):
    def setUp(self):
        self._orig_roots = list(env_settings.allowed_browse_roots)

    def tearDown(self):
        env_settings.allowed_browse_roots = self._orig_roots

    def test_resolve_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            env_settings.allowed_browse_roots = [str(base)]
            safe = routes_fs._resolve_browse_path(base, "inside")
            self.assertEqual(safe, base / "inside")
            with self.assertRaises(HTTPException):
                routes_fs._resolve_browse_path(base, "../escape")
            with self.assertRaises(HTTPException):
                routes_fs._resolve_browse_path(base, "/abs/path")

    def test_normalize_root_rejects_unknown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            env_settings.allowed_browse_roots = [str(base)]
            normalized = routes_fs._normalize_root(str(base))
            self.assertEqual(normalized, base)
            with self.assertRaises(HTTPException):
                routes_fs._normalize_root(str(base / "other"))
