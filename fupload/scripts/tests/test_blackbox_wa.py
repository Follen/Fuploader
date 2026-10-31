from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fupload_cli.blackbox import Blackbox
from fupload_cli.blackbox_wa import WA_CREATE, WA_UPDATE, WA_LIST, WA_DETAIL, WA_TAGS, WA_USER
from fupload_cli.errors import FuploadError
from fupload_cli.schema import get_schema
from fupload_cli.cli import build_parser

ENCODED = "!WA:2!opaque-test-content"
IMAGE = "https://imgheybox.max-c.com/fixture.png"


def configuration():
    return {"categories": ["gen0"], "strappid": "wowretail", "open": True, "name": "Private temporary WA",
            "descriptionHeybox": '<p data-fixture="preserve"><img src="' + IMAGE + '">文章</p>',
            "updateLog": "<p>Original</p>", "screens": [{"src": IMAGE, "thumb": IMAGE}],
            "encoded": ENCODED, "subscribeLevel": 0}


class Workshop:
    def __init__(self):
        self.items = {}
        self.calls = []
        self.writes = []
        self.repeat = False
        self.fail_read_after_write = False
        self.fail_write = False
        self.foreign_detail = False
        self.page_cap = None

    def put(self, slug, config):
        old = self.items.get(slug, {})
        self.items[slug] = {"Slug": slug, "HeyboxId": 123, "Name": config["name"],
                            "Categories": deepcopy(config["categories"]), "Description": config.get("descriptionHeybox", ""),
                            "UpdateLog": config.get("updateLog", ""), "Encoded": config["encoded"],
                            "ThumbList": [item["src"] for item in config["screens"]], "AuditState": 2,
                            "LatestVersion": {"Slug": slug, "Version": old.get("LatestVersion", {}).get("Version", 0) + 1},
                            "branch": config["strappid"]}

    def __call__(self, method, route, body, query):
        self.calls.append((method, route, deepcopy(body), deepcopy(query)))
        if route == WA_USER:
            result = {"heybox_id": 123}
        elif route == WA_TAGS:
            result = {"list": [{"Name": "通用", "TagList": [{"Key": "gen0", "Name": "通用"}]}]}
        elif route == WA_LIST:
            if self.fail_read_after_write and self.writes:
                raise FuploadError("read failed", kind="network_error")
            rows = [deepcopy(item) for item in self.items.values() if item["branch"] == query["strappid"]]
            offset = 0 if self.repeat else query["offset"]
            result = {"waList": rows[offset:offset + min(query["limit"], self.page_cap or query["limit"])]}
        elif route == WA_DETAIL:
            result = deepcopy(self.items[query["slug"]])
            if self.foreign_detail:
                result["HeyboxId"] = 999
        elif route in (WA_CREATE, WA_UPDATE):
            self.writes.append(route)
            if self.fail_write:
                raise FuploadError("backend echoed " + ENCODED, details={"response": {"Encoded": ENCODED}, "body": ENCODED})
            if query.get("delete"):
                self.items.pop(query["slug"])
            else:
                self.put("new-slug" if route == WA_CREATE else query["slug"], json.loads(body["configuration"]))
            result = {}
        else:
            raise AssertionError(route)
        return {"status": "ok", "result": result}


class BlackboxWATests(unittest.TestCase):
    def setUp(self):
        self.server = Workshop()
        self.provider = Blackbox({"verify_attempts": 1, "verify_interval": 0}, self.server)

    def checked(self, action, doc):
        doc = dict(doc)
        if action != "delete":
            doc.setdefault("scope", "public")
        dry_run = doc.pop("dry_run", False)
        value = get_schema("blackbox", "wa", action).validate({"schema": "fupload.v1.blackbox.wa." + action, **doc})
        if dry_run:
            value["dry_run"] = True
        return self.provider.execute_write("wa", action, value)

    def test_create_uses_native_configuration_and_redacts_opaque_content(self):
        result = self.checked("create", {"configuration": configuration()})
        self.assertTrue(result["verified"])
        self.assertEqual(result["slug"], "new-slug")
        call = next(call for call in self.server.calls if call[1] == WA_CREATE)
        self.assertEqual(call[3], {})
        self.assertEqual(json.loads(call[2]["configuration"]), configuration())
        self.assertNotIn(ENCODED, json.dumps(result))
        self.assertEqual(result["readback"]["Encoded_summary"]["bytes"], len(ENCODED))
        self.assertIn("subscribeLevel", result["unverified_fields"])
        self.assertNotIn("subscribeLevel", result["verified_fields"])

    def test_sparse_update_preserves_string_html_and_images(self):
        self.server.put("owned", configuration())
        self.checked("edit", {"slug": "owned", "configuration": {"strappid": "wowretail", "open": True, "subscribeLevel": 0, "name": "Edited WA"}})
        sent = json.loads(next(call[2]["configuration"] for call in self.server.calls if call[1] == WA_UPDATE))
        self.assertEqual(sent["encoded"], ENCODED)
        self.assertEqual(sent["descriptionHeybox"], configuration()["descriptionHeybox"])
        self.assertEqual(sent["updateLog"], configuration()["updateLog"])
        self.assertEqual(sent["screens"], configuration()["screens"])
        self.assertEqual(self.server.writes, [WA_UPDATE])

    def test_every_sparse_write_explicitly_selects_branch_visibility_and_level(self):
        for key in ("strappid", "open", "subscribeLevel"):
            doc = {"strappid": "wowretail", "open": True, "subscribeLevel": 0}
            del doc[key]
            with self.subTest(key=key), self.assertRaises(FuploadError):
                self.checked("update", {"slug": "owned", "configuration": doc})
        self.assertEqual(self.server.calls, [])

    def test_unsupported_private_scope_is_rejected_before_auth_or_write(self):
        config = configuration()
        config["open"] = False
        with self.assertRaises(FuploadError) as caught:
            self.checked("create", {"scope": "private", "configuration": config})
        self.assertEqual(caught.exception.details["path"], "$.scope")
        self.assertEqual(self.server.calls, [])

    def test_native_open_false_requires_public_intent_and_never_claims_private(self):
        config = configuration()
        config["open"] = False
        result = self.checked("create", {"scope": "public", "configuration": config})
        self.assertEqual(result["scope"], "public")
        self.assertFalse(result["requested_open"])
        self.assertFalse(result["visibility"]["verified"])
        self.assertIn("open", result["unverified_fields"])
        call = next(call for call in self.server.calls if call[1] == WA_CREATE)
        self.assertNotIn("scope", json.loads(call[2]["configuration"]))

    def test_provider_requires_public_intent_even_without_schema(self):
        for scope in (None, "private"):
            with self.subTest(scope=scope), self.assertRaises(FuploadError):
                self.provider.wa_upsert({"scope": scope, "configuration": configuration()}, create=True)
        self.assertEqual(self.server.calls, [])

    def test_schema_requires_explicit_scope_for_every_upsert(self):
        for action in ("create", "update", "edit"):
            doc = {"schema": "fupload.v1.blackbox.wa." + action, "configuration": configuration()}
            if action != "create":
                doc["slug"] = "owned"
            with self.subTest(action=action), self.assertRaises(FuploadError) as caught:
                get_schema("blackbox", "wa", action).validate(doc)
            self.assertEqual(caught.exception.details["path"], "$.scope")

    def test_arbitrary_transport_exception_cannot_echo_content_on_read(self):
        with patch.object(self.provider, "_config_request", side_effect=ValueError(ENCODED)):
            with self.assertRaises(FuploadError) as caught:
                self.provider.wa_categories()
        self.assertNotIn(ENCODED, str(caught.exception.as_dict()))
        self.assertFalse(caught.exception.verification_required)

    def test_schema_rejects_unknown_nested_fields_types_and_long_weighted_title(self):
        mutations = [lambda c: c.update(unknown=1), lambda c: c.update(open=1), lambda c: c.update(subscribeLevel=True),
                     lambda c: c.update(categories=["gen0", "gen0"]), lambda c: c.update(screens=[{"src": IMAGE}]),
                     lambda c: c.update(name="中" * 36)]
        for mutate in mutations:
            config = configuration()
            mutate(config)
            with self.assertRaises(FuploadError):
                self.checked("create", {"configuration": config})
        self.assertEqual(self.server.calls, [])

    def test_owned_list_exhausts_short_pages_and_never_returns_raw_strings(self):
        self.server.put("a", configuration())
        self.server.put("b", configuration())
        self.provider.config["wa_page_size"] = 1
        result = self.provider.wa_list("wowretail")
        self.assertEqual(result["total_count"], 2)
        self.assertEqual([call[3]["offset"] for call in self.server.calls if call[1] == WA_LIST], [0, 1, 2])
        self.assertNotIn(ENCODED, json.dumps(result))

    def test_repeated_or_capped_pagination_prevents_writes(self):
        self.server.put("owned", configuration())
        for repeat in (True, False):
            self.server.repeat = repeat
            self.provider.config["wa_max_pages"] = 2 if repeat else 1
            with self.assertRaises(FuploadError):
                self.checked("delete", {"slug": "owned", "strappid": "wowretail", "confirm_delete": True})
        self.assertEqual(self.server.writes, [])

    def test_server_short_page_advances_by_actual_row_count(self):
        self.server.put("a", configuration())
        self.server.put("b", configuration())
        self.server.page_cap = 1
        result = self.provider.wa_list("wowretail")
        self.assertEqual(result["total_count"], 2)
        self.assertEqual([call[3]["offset"] for call in self.server.calls if call[1] == WA_LIST], [0, 1, 2])

    def test_other_author_or_wrong_branch_is_rejected_before_mutation(self):
        self.server.put("owned", configuration())
        self.server.foreign_detail = True
        with self.assertRaises(FuploadError):
            self.checked("delete", {"slug": "owned", "strappid": "wowretail", "confirm_delete": True})
        self.server.foreign_detail = False
        with self.assertRaises(FuploadError):
            self.checked("delete", {"slug": "owned", "strappid": "wowforever", "confirm_delete": True})
        self.assertEqual(self.server.writes, [])

    def test_error_echo_is_suppressed_and_write_is_not_replayed(self):
        self.server.fail_write = True
        with self.assertRaises(FuploadError) as caught:
            self.checked("create", {"configuration": configuration()})
        self.assertTrue(caught.exception.verification_required)
        self.assertNotIn(ENCODED, str(caught.exception) + json.dumps(caught.exception.as_dict()))
        self.assertEqual(self.server.writes, [WA_CREATE])

    def test_readback_failure_after_create_is_uncertain_without_replay(self):
        self.server.fail_read_after_write = True
        with self.assertRaises(FuploadError) as caught:
            self.checked("create", {"configuration": configuration()})
        self.assertTrue(caught.exception.verification_required)
        self.assertEqual(self.server.writes, [WA_CREATE])

    def test_ordinary_exception_after_write_is_sanitized_and_not_replayed(self):
        for error in (ValueError(ENCODED), OSError(ENCODED)):
            original_rows = self.provider._wa_rows
            def rows(*args, **kwargs):
                if self.server.writes:
                    raise error
                return original_rows(*args, **kwargs)
            with self.subTest(error=type(error).__name__), patch.object(self.provider, "_wa_rows", side_effect=rows):
                self.server.items.clear()
                self.server.writes.clear()
                with self.assertRaises(FuploadError) as caught:
                    self.checked("create", {"configuration": configuration()})
                self.assertTrue(caught.exception.verification_required)
                self.assertNotIn(ENCODED, str(caught.exception.as_dict()))
                self.assertEqual(self.server.writes, [WA_CREATE])

    def test_delete_has_slug_delete_flag_empty_body_and_negative_readback(self):
        self.server.put("owned", configuration())
        result = self.checked("delete", {"slug": "owned", "strappid": "wowretail", "confirm_delete": True})
        self.assertTrue(result["verified"])
        call = next(call for call in self.server.calls if call[1] == WA_UPDATE)
        self.assertEqual(call[2], {})
        self.assertEqual(call[3], {"slug": "owned", "delete": 1})
        self.assertEqual(self.server.writes, [WA_UPDATE])

    def test_active_review_delete_is_rejected_like_official_client(self):
        self.server.put("owned", configuration())
        self.server.items["owned"]["AuditState"] = 1
        with self.assertRaises(FuploadError) as caught:
            self.checked("delete", {"slug": "owned", "strappid": "wowretail", "confirm_delete": True})
        self.assertEqual(caught.exception.kind, "review_in_progress")
        self.assertEqual(self.server.writes, [])

    def test_dry_run_does_not_read_authenticate_or_print_string(self):
        result = self.checked("create", {"configuration": configuration(), "dry_run": True})
        self.assertEqual(self.server.calls, [])
        self.assertNotIn(ENCODED, json.dumps(result))

    def test_cli_exposes_complete_wa_tree(self):
        parser = build_parser()
        for action in ("create", "update", "edit", "delete"):
            args = parser.parse_args(["blackbox", "wa", action, "--input", "-"])
            self.assertEqual((args.platform, args.resource, args.action), ("blackbox", "wa", action))
        args = parser.parse_args(["blackbox", "wa", "get", "--strappid", "wowretail", "--slug", "opaque"])
        self.assertEqual(args.slug, "opaque")


if __name__ == "__main__":
    unittest.main()
