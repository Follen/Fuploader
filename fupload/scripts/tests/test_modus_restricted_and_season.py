from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.cli import build_parser
from fupload_cli.errors import FuploadError, ValidationError
from fupload_cli.modus import ModUs
from fupload_cli.schema import get_schema
from fupload_cli.state_machine import ProjectStateMachine


class RestrictedAndSeasonTests(unittest.TestCase):
    @staticmethod
    def project(**basic):
        machine = ProjectStateMachine()
        machine.select_game("wow_retail")
        values = {"name": "Fixture", "summary": "Original summary", "categories": [1800], "publish_platforms": ["modus"]}
        values.update(basic)
        machine.submit_basic_info(values)
        machine.submit_license({"type": "MIT"})
        return {"project_id": 9, "project_state": machine.snapshot()}

    @staticmethod
    def detail(**changes):
        value = {"projectId": 9, "name": "Fixture", "summary": "Original summary", "altName": "", "description": "",
                 "repoUrl": None, "categories": [{"id": 1800}], "license": '{"type":"MIT"}', "requiredTierId": None,
                 "synchronizationType": 1, "requiredDependencies": "", "images": 0}
        value.update(changes)
        return value

    def test_restricted_edit_only_sends_officially_editable_fields(self):
        provider = ModUs("fixture")
        document = {**self.project(), "summary": "Updated summary", "description": "<p>Full</p>", "alt_name": "Alias"}
        with mock.patch.object(provider, "project_detail", return_value=self.detail()) as detail, mock.patch.object(provider, "_request", return_value={"code": 200}) as request:
            provider.project_update(document)
        detail.assert_called_once_with(9)
        self.assertEqual(request.call_args.args[2], {"projectId": 9, "summary": "Updated summary", "description": "<p>Full</p>", "altName": "Alias"})

    def test_restricted_changes_and_unverifiable_detail_are_rejected(self):
        provider = ModUs("fixture")
        documents = [self.project(name="Changed"), self.project(categories=[1801]), self.project(required_tier_id=5),
                     self.project(publish_platforms=["bigfoot"]), {**self.project(), "repo_url": "https://example.invalid"},
                     {**self.project(), "required_dependencies": "22"}, {**self.project(), "images": 0, "image_ops": [{"op": "delete", "name": "1.webp"}]}]
        licensed = self.project()
        licensed["project_state"]["license"] = {"type": "BSD"}
        documents.append(licensed)
        for document in documents:
            with self.subTest(document=document), mock.patch.object(provider, "project_detail", return_value=self.detail()), mock.patch.object(provider, "_request") as request:
                with self.assertRaisesRegex(ValidationError, "restricted"):
                    provider.project_update(document)
                request.assert_not_called()
        for detail in ({"projectId": 10}, {"projectId": 9, "name": "Fixture"}, None):
            with self.subTest(detail=detail), mock.patch.object(provider, "project_detail", return_value=detail), mock.patch.object(provider, "_request") as request:
                with self.assertRaises(FuploadError):
                    provider.project_update(self.project())
                request.assert_not_called()

    def test_unrestricted_boundary_does_not_use_restricted_projection(self):
        provider = ModUs("fixture")
        with mock.patch.object(provider, "project_detail") as detail, mock.patch.object(provider, "_request", return_value={"code": 200}) as request:
            provider.project_update({**self.project(), "project_id": 200000000, "name": "Updated"})
        detail.assert_not_called()
        self.assertEqual(request.call_args.args[2]["name"], "Updated")

    def test_restricted_destructive_and_release_operations_fail_before_requests(self):
        provider = ModUs("fixture")
        for invoke in (lambda: provider.project_delete(9), lambda: provider.release_delete(9, 3),
                       lambda: provider.publish({"project_id": 9, "file_id": 3}, update=True),
                       lambda: provider.publish({"project_id": 9, "file": "unused.zip"})):
            with self.subTest(invoke=invoke), mock.patch.object(provider, "_request") as request:
                with self.assertRaisesRegex(ValidationError, "restricted"):
                    invoke()
                request.assert_not_called()

    def test_restricted_write_schema_rejects_small_ids_before_dry_run(self):
        for resource, action, extra in (("project", "delete", {"confirm": "DELETE"}),
                                        ("plugin", "edit", {"file_id": 3}),
                                        ("plugin", "delete", {"file_id": 3, "confirm": "DELETE"})):
            with self.subTest(resource=resource, action=action):
                schema = get_schema("modus", resource, action)
                with self.assertRaisesRegex(ValidationError, "restricted"):
                    schema.validate({"schema": schema.name, "project_id": 9, **extra})

    def test_create_schemas_and_direct_provider_reject_edit_ids(self):
        for resource, identity in (("config", "share_id"), ("wa", "import_id")):
            schema = get_schema("modus", resource, "create")
            self.assertNotIn(identity, schema.fields)
            with self.assertRaises(ValidationError) as failure:
                schema.validate({"schema": schema.name, identity: "existing"})
            self.assertEqual(failure.exception.details["path"], "$." + identity)
            provider = ModUs("fixture", main_session=True)
            method = provider.share_create if resource == "config" else provider.import_create
            with mock.patch.object(provider, "_request") as request:
                with self.assertRaises(ValidationError):
                    method({identity: "existing"})
                request.assert_not_called()

    def test_season_read_cli_and_wire_use_exact_author_game_query(self):
        parser = build_parser()
        args = parser.parse_args(["modus", "options", "season-subscription", "--author-id", "7", "--game-type", "wow_retail"])
        provider = ModUs("fixture", main_session=True)
        with mock.patch.object(provider, "_request", return_value={"data": {"id": 55, "isEnabled": 1}}) as request:
            result = provider.execute_read(args.resource, args.action, args)
        self.assertEqual(result["id"], 55)
        self.assertEqual(request.call_args.args, ("GET", "user/author/season-sub/detail?authorId=7&gameType=wow_retail"))
        self.assertFalse(request.call_args.kwargs.get("headers"))
        args = parser.parse_args(["modus", "options", "subscription-game-types"])
        with mock.patch.object(provider, "_request", return_value={"data": []}) as request:
            provider.execute_read(args.resource, args.action, args)
        request.assert_called_once_with("GET", "user/game-type/list")

    def test_season_read_handles_unconfigured_author_and_build_game_code(self):
        provider = ModUs("fixture", main_session=True)
        with mock.patch.object(provider, "user_info", return_value={"user": {"userId": 7}}), mock.patch.object(provider, "options", return_value=[{"gameCode": "wow_retail"}]), mock.patch.object(provider, "_request", return_value={"code": 200, "msg": "success"}) as request:
            self.assertIsNone(provider.author_season_subscription(server_type=0))
        request.assert_called_once_with("GET", "user/author/season-sub/detail?authorId=7&gameType=wow_retail")

    def test_season_selection_uses_separate_options_and_enabled_unfinished_season(self):
        provider = ModUs("fixture", main_session=True)
        for row, accepted in (({"id": 55, "isEnabled": 1, "platformSeasonStatus": 1}, True),
                              ({"id": 55, "isEnabled": 0, "platformSeasonStatus": 1}, False),
                              ({"id": 55, "isEnabled": 1, "platformSeasonStatus": 2}, False),
                              ({"id": 56, "isEnabled": 1, "platformSeasonStatus": 1}, False), (None, False)):
            with self.subTest(row=row), mock.patch.object(provider, "options", return_value=row) as options:
                document = {"sub_type": 1, "required_tier_id": 55, "server_type": 0}
                if accepted:
                    provider._validate_main_write("wa", "create", document)
                else:
                    with self.assertRaisesRegex(ValidationError, "season"):
                        provider._validate_main_write("wa", "create", document)
                options.assert_called_once_with("season-subscription", server_type=0)

    def test_sparse_season_tier_edit_uses_retained_subscription_type(self):
        provider = ModUs("fixture", main_session=True)
        with mock.patch.object(provider, "import_detail", return_value=[{"id": "opaque", "subType": 1, "requiredTierId": 55}]), mock.patch.object(provider, "options", return_value={"id": 55, "isEnabled": 1}) as options:
            provider._validate_main_write("wa", "edit", {"import_id": "opaque", "required_tier_id": 55, "server_type": 0})
        options.assert_called_once_with("season-subscription", server_type=0)

    def test_blackbox_game_types_cli_leaf_is_read_only(self):
        args = build_parser().parse_args(["blackbox", "options", "game-types"])
        self.assertEqual((args.handler, args.resource, args.action), ("read", "options", "game-types"))


if __name__ == "__main__":
    unittest.main()
