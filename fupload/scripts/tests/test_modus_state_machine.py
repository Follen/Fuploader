from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.errors import ValidationError
from fupload_cli.state_machine import (
    BASIC_INFO,
    CHOOSE_GAME,
    COMPLETE,
    LICENSE,
    ProjectStateMachine,
)


class ModusProjectStateMachineTests(unittest.TestCase):
    def basic(self, **overrides):
        value = {
            "name": "Fixture project",
            "summary": "State machine fixture",
            "alt_name": "Fixture",
            "categories": [1800],
            "synchronization_type": 1,
            "publish_platforms": ["modus"],
        }
        value.update(overrides)
        return value

    def test_steps_are_sequenced_and_overjump_does_not_mutate_state(self):
        machine = ProjectStateMachine()
        self.assertEqual(machine.state, CHOOSE_GAME)
        with self.assertRaises(ValidationError):
            machine.submit_basic_info(self.basic())
        self.assertEqual(machine.state, CHOOSE_GAME)
        with self.assertRaises(ValidationError):
            machine.submit_license({"type": "MIT"})
        machine.select_game({"id": "wow_retail", "name": "WoW Retail"})
        self.assertEqual(machine.state, BASIC_INFO)
        with self.assertRaises(ValidationError):
            machine.submit_license({"type": "MIT"})
        self.assertEqual(machine.state, BASIC_INFO)
        machine.submit_basic_info(self.basic())
        self.assertEqual(machine.state, LICENSE)
        machine.submit_license({"type": "MIT", "holder": "ROLE", "year": "2026", "content": "text"})
        self.assertEqual(machine.state, COMPLETE)

    def test_platforms_require_at_least_one_and_allow_both(self):
        machine = ProjectStateMachine()
        machine.select_game({"gameVersion": "12.1.0", "server": "wow_retail"})
        for platforms in ([], ["other"], ["modus", "modus"]):
            with self.subTest(platforms=platforms):
                with self.assertRaises(ValidationError):
                    machine.submit_basic_info(self.basic(publish_platforms=platforms))
                self.assertEqual(machine.state, BASIC_INFO)
        machine.submit_basic_info(self.basic(publish_platforms=["modus", "bigfoot"]))
        self.assertEqual(machine.basic_info["publish_platforms"], ["modus", "bigfoot"])

    def test_required_tier_none_positive_and_invalid_branches(self):
        for tier in (None, 7):
            with self.subTest(tier=tier):
                machine = ProjectStateMachine()
                machine.select_game({"id": "wow_retail"})
                machine.submit_basic_info(self.basic(required_tier_id=tier))
                self.assertEqual(machine.basic_info["required_tier_id"], tier)
        for tier in (0, -1, True, False, "7", 1.5):
            with self.subTest(tier=tier):
                machine = ProjectStateMachine()
                machine.select_game({"id": "wow_retail"})
                with self.assertRaises(ValidationError):
                    machine.submit_basic_info(self.basic(required_tier_id=tier))
                self.assertEqual(machine.state, BASIC_INFO)

    def test_snapshot_round_trip_and_file_persistence(self):
        machine = ProjectStateMachine()
        game = {"id": "wow_retail", "name": "Retail"}
        machine.select_game(game)
        machine.submit_basic_info(self.basic(publish_platforms=["modus", "bigfoot"], required_tier_id=None))
        snapshot = machine.snapshot()
        resumed = ProjectStateMachine.from_snapshot(json.loads(json.dumps(snapshot)))
        self.assertEqual(resumed.state, LICENSE)
        self.assertEqual(resumed.game, game)
        resumed.submit_license({"template": "MIT", "copyrightHolder": "ROLE", "copyrightYear": "2026", "licenseContent": "text"})
        self.assertEqual(resumed.license, {"type": "MIT", "holder": "ROLE", "year": "2026", "content": "text"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project-state.json"
            resumed.save(path)
            loaded = ProjectStateMachine.load(path)
            self.assertEqual(loaded.snapshot(), resumed.snapshot())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["state"], COMPLETE)

    def test_custom_license_requires_content_and_unknown_fields_rejected(self):
        machine = ProjectStateMachine()
        machine.select_game({"id": "wow_retail"})
        machine.submit_basic_info(self.basic())
        with self.assertRaises(ValidationError):
            machine.submit_license({"type": "custom"})
        self.assertEqual(machine.state, LICENSE)
        with self.assertRaisesRegex(ValidationError, "unknown license field"):
            machine.submit_license({"type": "MIT", "unexpected": "x"})
        self.assertEqual(machine.state, LICENSE)


if __name__ == "__main__":
    unittest.main()
