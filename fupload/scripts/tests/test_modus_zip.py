from __future__ import annotations

import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.errors import ValidationError
from fupload_cli.modus_zip import parse_modus_zip, select_game_versions


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

    def test_ignores_library_tocs_under_libs(self) -> None:
        result = parse_modus_zip(
            make_zip(
                ("Addon/Addon.toc", "## Interface: 120100\n"),
                ("Addon/Libs/Ace3.toc", "## Interface: 11508, 120000\n"),
                ("Addon/libs/LibDeflate/LibDeflate.toc", "## Interface: 80300\n"),
            )
        )
        self.assertEqual(result["toc_version"], "120100")
        self.assertEqual(result["toc_files"], ["Addon/Addon.toc"])
        self.assertEqual(
            result["supported_game_versions"],
            [{"gameVersion": "12.1.0", "server": "wow_retail"}],
        )

    def test_rejects_zip_with_only_library_tocs(self) -> None:
        with self.assertRaisesRegex(ValidationError, "outside a Libs directory"):
            parse_modus_zip(make_zip(("Addon/Libs/Ace3.toc", "## Interface: 120100\n")))

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

    def test_universal_flavors_use_live_choices_and_explicit_product_scope(self) -> None:
        result = parse_modus_zip(make_zip(
            ("Addon/Addon.toc", "## Interface: 11509,16001,20506,30405,38002,40402,50504,120100\n"),
            ("Addon/Addon_Mainline.toc", "## Interface: 16001,120100\n"),
            ("Addon/Addon_Vanilla.toc", "## Interface: 11509\n"),
            ("Addon/Addon_TBC.toc", "## Interface: 20506\n"),
            ("Addon/Addon_Wrath.toc", "## Interface: 30405,38002\n"),
            ("Addon/Addon_Cata.toc", "## Interface: 40402\n"),
            ("Addon/Addon_Mists.toc", "## Interface: 50504\n"),
        ))
        import json
        config = [{"key": "wow_builds", "value": json.dumps({
            "wow_retail": {"versions": ["12.1.0"]}, "wow_classic": {"versions": ["5.5.4"]},
            "wow_classic_era": {"versions": ["1.15.9"]}, "wow_classic_titan": {"versions": ["3.80.2"]},
            "wow_anniversary": {"versions": ["2.5.6"]},
        })}]
        available = select_game_versions(result["supported_game_versions"], config)
        self.assertEqual(len(available), 5)
        self.assertEqual(result["unmapped_interface_values"], ["30405"])
        retail = [{"gameVersion": "12.1.0", "server": "wow_retail"}]
        self.assertEqual(select_game_versions(result["supported_game_versions"], config, retail), retail)
        for supplied in ([], [available[0], available[0]], [{"gameVersion": "1.60.1", "server": "wow_forever"}],
                         [{"gameVersion": "12.0.7", "server": "wow_retail"}]):
            with self.assertRaises(ValidationError):
                select_game_versions(result["supported_game_versions"], config, supplied)
        for invalid in ([], [{"key": "wow_builds", "value": "invalid"}]):
            with self.assertRaises(ValidationError):
                select_game_versions(result["supported_game_versions"], invalid)

    def test_rejects_malformed_interface(self) -> None:
        with self.assertRaisesRegex(ValidationError, "decimal codes"):
            parse_modus_zip(make_zip(("Addon/Addon.toc", "## Interface: retail\n")))

    def test_forever_live_build_and_explicit_newer_retail_build(self) -> None:
        import json
        result = parse_modus_zip(make_zip(("Addon/Addon.toc", "## Interface: 16001,120100\n")))
        retail = {"server": "wow_retail", "gameVersion": "12.1.0"}
        newer = {"server": "wow_retail", "gameVersion": "12.1.5"}
        forever = {"server": "wow_forever", "gameVersion": "1.60.1"}
        config = [{"key": "wow_builds", "value": json.dumps({
            "wow_retail": {"versions": ["12.1.5", "12.1.0"]},
            "wow_forever": {"versions": ["1.60.1"]},
            "wow_classic": {"versions": ["5.5.4"]},
        })}]
        self.assertEqual(result["toc_version"], "16001,120100")
        self.assertEqual(result["unmapped_interface_values"], [])
        self.assertEqual(select_game_versions(result["supported_game_versions"], config), [forever, retail])
        self.assertEqual(select_game_versions(result["supported_game_versions"], config, [newer, forever]), [newer, forever])
        for supplied in ([{"server": "wow_classic", "gameVersion": "5.5.4"}],
                         [{"server": "wow_retail", "gameVersion": "12.2.0"}],
                         [newer, newer], [], [None]):
            with self.assertRaises(ValidationError):
                select_game_versions(result["supported_game_versions"], config, supplied)

    def test_forever_only_requires_live_support_and_does_not_add_retail(self) -> None:
        import json
        result = parse_modus_zip(make_zip(("Addon/Addon.toc", "## Interface: 16001\n")))
        forever = {"server": "wow_forever", "gameVersion": "1.60.1"}
        config = [{"key": "wow_builds", "value": json.dumps({"wow_forever": {"versions": ["1.60.1"]}})}]
        self.assertEqual(select_game_versions(result["supported_game_versions"], config), [forever])
        config[0]["value"] = json.dumps({"wow_retail": {"versions": ["12.1.0"]}})
        with self.assertRaises(ValidationError):
            select_game_versions(result["supported_game_versions"], config)
        with self.assertRaises(ValidationError):
            select_game_versions(result["supported_game_versions"], config, [{"server": "wow_retail", "gameVersion": "12.1.0"}])

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
