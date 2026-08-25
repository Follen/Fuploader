from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.errors import ValidationError
from fupload_cli.modus import _project_document, _project_wire
from fupload_cli.state_machine import ProjectStateMachine
from fupload_cli.schema import get_schema


class ModusProjectSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = get_schema("modus", "project", "create")

    def _document(self, **overrides):
        basic_info = {
            "schema": self.schema.name,
            "name": "Fixture project",
            "alt_name": "Fixture",
            "summary": "A project used for schema regression",
            "categories": [1800],
            "synchronization_type": "3",
            "images": 0,
            "screenshot_base64s": [],
            "repo_url": "https://example.invalid/repo",
            "required_tier_id": None,
            "publish_platforms": ["modus", "bigfoot"],
        }
        machine = ProjectStateMachine()
        machine.select_game({"id": "wow_retail"})
        machine.submit_basic_info(basic_info)
        machine.submit_license({
            "type": "All Rights Reserved",
            "holder": "ROLE",
            "year": "2026",
            "content": "Copyright (c) 2026 ROLE.",
        })
        value = {"schema": self.schema.name, "project_state": machine.snapshot()}
        value.update(overrides)
        return value

    def test_full_project_fields_and_both_targets_are_valid(self) -> None:
        validated = self.schema.validate(self._document())
        document = _project_document(validated)
        self.assertEqual(document["publish_platforms"], ["modus", "bigfoot"])
        self.assertEqual(document["license"]["holder"], "ROLE")

    def test_publish_platforms_are_a_nonempty_multi_select(self) -> None:
        for platforms, message in (([], "must not be empty|at least one"), (["other"], "modus or bigfoot"), (["modus", "modus"], "duplicates")):
            with self.subTest(platforms=platforms):
                with self.assertRaisesRegex(ValidationError, message):
                    self._document_with_basic_info(publish_platforms=platforms)

    def test_license_object_rejects_unknown_or_empty_fields(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unknown license field"):
            self._document_with_license({"type": "MIT", "unknown": "x"})
        with self.assertRaisesRegex(ValidationError, "non-empty string"):
            self._document_with_license({"type": ""})

    def test_required_tier_is_positive_or_null(self) -> None:
        self.schema.validate(self._document_with_basic_info(required_tier_id=None))
        for tier in (0, -1, True, "1"):
            with self.subTest(tier=tier):
                with self.assertRaises(ValidationError):
                    self._document_with_basic_info(required_tier_id=tier)

    def test_bigfoot_forces_no_required_tier(self) -> None:
        with self.assertRaisesRegex(ValidationError, "must be null"):
            self._document_with_basic_info(required_tier_id=1)

    def test_platforms_derive_synchronization_type(self) -> None:
        document = _project_document(self.schema.validate(self._document_with_basic_info(
            publish_platforms=["modus"], synchronization_type=1,
        )))
        self.assertEqual(document["synchronization_type"], 1)

    def test_bigfoot_exclusive_category_forces_bigfoot_only(self) -> None:
        with self.assertRaisesRegex(ValidationError, "category 998"):
            self._document_with_basic_info(categories=[998], publish_platforms=["modus", "bigfoot"])
        document = _project_document(self.schema.validate(self._document_with_basic_info(
            categories=[998], publish_platforms=["bigfoot"], synchronization_type=2,
        )))
        self.assertEqual(document["publish_platforms"], ["bigfoot"])

    def test_categories_have_creator_limit(self) -> None:
        with self.assertRaisesRegex(ValidationError, "at most five"):
            self._document_with_basic_info(categories=[1, 2, 3, 4, 5, 6])

    def test_legacy_license_display_name_remains_valid(self) -> None:
        self.schema.validate(self._document_with_license("All Rights Reserved"))

    def test_unknown_project_field_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unknown field"):
            self.schema.validate(self._document(unexpected_field=True))

    def test_project_wire_preserves_platform_and_detail_fields(self) -> None:
        document = _project_document(self.schema.validate(self._document_with_basic_info(
            required_dependencies="100,101",
            cf_url="https://www.curseforge.com/wow/addons/fixture",
            logo="https://cdn.invalid/logo.webp",
        )))
        wire = _project_wire(document)
        self.assertNotIn("publishPlatforms", wire)
        self.assertEqual(wire["requiredDependencies"], "100,101")
        self.assertNotIn("cfUrl", wire)
        self.assertNotIn("logo", wire)

    def test_project_update_wire_is_presence_aware(self) -> None:
        wire = _project_wire({"project_id": 9, "name": "Renamed", "required_tier_id": None})
        self.assertEqual(wire, {"name": "Renamed", "projectId": 9, "requiredTierId": "<null>"})

    def test_project_update_wire_uses_description_and_dependency_clear_markers(self) -> None:
        wire = _project_wire({"project_id": 9, "description": "", "required_dependencies": None})
        self.assertEqual(wire["description"], "<null>")
        self.assertEqual(wire["requiredDependencies"], "<null>")

    def test_project_update_wire_uses_creator_image_operations(self) -> None:
        wire = _project_wire({
            "project_id": 9,
            "images": 1,
            "image_ops": [{"op": "upload", "name": "1.webp", "base64": "AA=="}],
        })
        self.assertEqual(wire["images"], 1)
        self.assertEqual(wire["imagesOps"][0]["op"], "upload")
        self.assertNotIn("screenshotBase64sReqs", wire)

    def test_completed_project_state_snapshot_can_be_mapped(self) -> None:
        snapshot = self._document()["project_state"]
        self.assertEqual(snapshot["state"], "complete")
        document = _project_document({"project_state": snapshot})
        self.assertEqual(document["name"], "Fixture project")
        self.assertEqual(document["publish_platforms"], ["modus", "bigfoot"])
        self.assertEqual(document["license"]["type"], "All Rights Reserved")

    def test_project_create_requires_completed_state_snapshot(self) -> None:
        with self.assertRaisesRegex(ValidationError, "field is required"):
            self.schema.validate({"schema": self.schema.name, "name": "Legacy bypass"})

    def test_project_edit_requires_completed_state_snapshot(self) -> None:
        schema = get_schema("modus", "project", "edit")
        with self.assertRaisesRegex(ValidationError, "field is required"):
            schema.validate({"schema": schema.name, "project_id": 9, "name": "Legacy bypass"})

    def test_incomplete_snapshot_is_rejected_at_schema_boundary(self) -> None:
        machine = ProjectStateMachine()
        machine.select_game({"id": "wow_retail"})
        with self.assertRaisesRegex(ValidationError, "complete"):
            self.schema.validate({"schema": self.schema.name, "project_state": machine.snapshot()})

    def test_incomplete_project_state_is_rejected_by_snapshot_contract(self) -> None:
        machine = ProjectStateMachine()
        machine.select_game({"id": "wow_retail"})
        with self.assertRaises(ValidationError):
            machine.submit_license({"type": "MIT"})

    def _document_with_basic_info(self, **overrides):
        basic_info = _project_document(self._document())
        license_value = basic_info.pop("license")
        basic_info.update(overrides)
        machine = ProjectStateMachine()
        machine.select_game({"id": "wow_retail"})
        machine.submit_basic_info(basic_info)
        machine.submit_license(license_value)
        return {"schema": self.schema.name, "project_state": machine.snapshot()}

    def _document_with_license(self, license_value):
        basic_info = _project_document(self._document())
        basic_info.pop("license")
        machine = ProjectStateMachine()
        machine.select_game({"id": "wow_retail"})
        machine.submit_basic_info(basic_info)
        machine.submit_license(license_value)
        return {"schema": self.schema.name, "project_state": machine.snapshot()}


if __name__ == "__main__":
    unittest.main()
