from __future__ import annotations

import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.errors import ValidationError
from fupload_cli.schema import get_schema


class DDZipPreflightTests(unittest.TestCase):
    def validate_archive(self, raw: bytes) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "addon.zip"
            package.write_bytes(raw)
            schema = get_schema("dd", "plugin", "update")
            schema.validate({
                "schema": schema.name, "sn": "test", "game_versions": ["120000"],
                "version": "1.0", "update_desc": "test", "file": str(package),
            })

    def archive(self, *, local_backslash=False, central_backslash=False) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("Addon/Addon.toc", "## Interface: 120000\n")
        raw = bytearray(output.getvalue())
        local_name = 30
        central_name = raw.index(b"PK\x01\x02") + 46
        if local_backslash:
            raw[local_name + 5] = ord("\\")
        if central_backslash:
            raw[central_name + 5] = ord("\\")
        return bytes(raw)

    def test_backslashes_in_either_zip_header_are_rejected(self) -> None:
        for local, central in ((True, True), (True, False), (False, True)):
            with self.subTest(local=local, central=central):
                with self.assertRaisesRegex(ValidationError, "backslash"):
                    self.validate_archive(self.archive(local_backslash=local, central_backslash=central))

    def test_forward_slash_archive_is_accepted(self) -> None:
        self.validate_archive(self.archive())

    def test_invalid_archive_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "valid ZIP"):
            self.validate_archive(b"not a zip")

    def test_external_url_without_local_file_is_unchanged(self) -> None:
        schema = get_schema("dd", "plugin", "update")
        schema.validate({
            "schema": schema.name, "sn": "test", "game_versions": ["120000"],
            "version": "1.0", "update_desc": "test", "detail_url": "https://example.com/addon.zip",
        })
