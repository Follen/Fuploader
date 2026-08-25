from __future__ import annotations

import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.errors import ValidationError
from fupload_cli.modus_zip import parse_modus_zip


def make_zip(*toc_entries: tuple[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, text in toc_entries:
            archive.writestr(name, text)
        archive.writestr("Addon/init.lua", "return {}\n")
    return output.getvalue()


class ModusZipParserTests(unittest.TestCase):
    def test_derives_retail_metadata_from_creator_interface(self) -> None:
        result = parse_modus_zip(make_zip(("Addon/Addon.toc", "## Interface: 110000\n")))
        self.assertEqual(result["toc_version"], "110000")
        self.assertEqual(result["supported_game_versions"], [{"gameVersion": "11.0.0", "server": "wow_retail"}])
        self.assertEqual(result["interface_values"], ["110000"])

    def test_supports_multiple_interface_values_for_one_game_release(self) -> None:
        result = parse_modus_zip(make_zip(("Addon/Addon.toc", "## Interface: 110000, 110002\n")))
        self.assertEqual(result["toc_version"], "110000,110002")
        self.assertEqual(
            result["supported_game_versions"],
            [{"gameVersion": "11.0.0", "server": "wow_retail"}, {"gameVersion": "11.0.2", "server": "wow_retail"}],
        )

    def test_same_interface_in_multiple_tocs_is_deterministic(self) -> None:
        result = parse_modus_zip(
            make_zip(
                ("B/B.toc", "## Interface: 11507\n"),
                ("A/A.toc", "## Interface: 11507\n"),
            )
        )
        self.assertEqual(result["toc_files"], ["A/A.toc", "B/B.toc"])
        self.assertEqual(result["supported_game_versions"][0]["gameVersion"], "Classic Era")

    def test_rejects_missing_toc(self) -> None:
        with self.assertRaisesRegex(ValidationError, r"no addon \.toc"):
            parse_modus_zip(make_zip())

    def test_rejects_missing_interface(self) -> None:
        with self.assertRaisesRegex(ValidationError, "no Interface"):
            parse_modus_zip(make_zip(("Addon/Addon.toc", "## Title: Missing\n")))

    def test_rejects_conflicting_tocs(self) -> None:
        with self.assertRaisesRegex(ValidationError, "ambiguous across files"):
            parse_modus_zip(
                make_zip(
                    ("A/A.toc", "## Interface: 110000\n"),
                    ("B/B.toc", "## Interface: 111000\n"),
                )
            )

    def test_rejects_unknown_interface(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unsupported addon TOC Interface"):
            parse_modus_zip(make_zip(("Addon/Addon.toc", "## Interface: 999999\n")))

    def test_rejects_malformed_interface(self) -> None:
        with self.assertRaisesRegex(ValidationError, "decimal codes"):
            parse_modus_zip(make_zip(("Addon/Addon.toc", "## Interface: retail\n")))

    def test_accepts_path_and_bytes_and_rejects_bad_zip(self) -> None:
        raw = make_zip(("Addon/Addon.toc", "\ufeff## Interface: 120100\n"))
        self.assertEqual(parse_modus_zip(raw)["toc_version"], "120100")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "addon.zip"
            path.write_bytes(raw)
            self.assertEqual(parse_modus_zip(path)["toc_version"], "120100")
        with self.assertRaisesRegex(ValidationError, "valid ZIP"):
            parse_modus_zip(b"not a zip")


if __name__ == "__main__":
    unittest.main()
