from __future__ import annotations

from copy import deepcopy
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.blackbox import Blackbox
from fupload_cli.blackbox_config import (
    BACKUP_LIST, BACKUP_REMOVE, BACKUP_RENAME, SHARE_LIST, SHARE_DETAIL,
    SHARE_CREATE, SHARE_UPDATE,
)
from fupload_cli.blackbox_web import BlackboxWebSession
from fupload_cli.blackbox_backup import BACKUP_CREATE, BACKUP_CREDENTIAL, BACKUP_SAVE
from fupload_cli.errors import FuploadError


def backup(backup_id="backup-a"):
    return {
        "ID": backup_id, "Name": "Original backup", "IsClassic": False, "Strappid": "wowretail",
        "KnownAddons": [{"ID": 7, "Name": "Addon", "Version": "1"}],
        "UnknownAddons": {"Files": [{"Name": "Unknown", "Size": 2}], "Url": "https://cdn.example/unknown.zip"},
        "WTFList": [{"Name": "ACCOUNT", "Characters": ["Realm - Player"],
                     "RealmCharacters": [{"Realm": "Realm", "Player": "Player"}]}],
        "Materials": {"Files": [{"Name": "Textures", "Size": 3}]},
        "Fonts": {"Files": [{"Name": "FRIZQT__.TTF", "Size": 4}]},
        "OpaqueBackupMetadata": {"preserve": [1, 2, 3]},
    }


def selection():
    return {
        "Title": "My setup", "Article": '<p><img src="https://cdn.example/pic.png">文章</p>',
        "UpdateLog": "<p>Update</p>", "Open": True,
        "KnownAddons": [{"ID": 7, "Name": "Addon", "Version": "1"}],
        "UnknownAddons": {"Files": []}, "WTFList": [], "Materials": {"Files": []},
        "Fonts": {"Files": []}, "ThumbList": ["https://cdn.example/cover.png"], "SubscribeLevel": 0,
        "ClearKnownAddons": False, "ClearUnknownAddons": False,
        "ClearMaterials": False, "ClearFonts": False,
    }


def share(share_id="share-a", backup_id="backup-a"):
    value = {**backup(backup_id), **selection(), "ShareID": share_id, "BackupID": backup_id}
    value["SubscribeLevel"] = {"level": 0, "name": "Free"}
    return value


class MemoryWorkshop:
    def __init__(self):
        self.backups = [backup()]
        self.shares = []
        self.calls = []
        self.writes = []
        self.error_path = None
        self.uncertain_path = None
        self.repeat_page = False
        self.missing_reference = False
        self.fail_read_after_remove = False

    def __call__(self, method, path, body, query):
        self.calls.append((method, path, deepcopy(body), deepcopy(query)))
        if path == self.error_path:
            return {"status": "failed", "result": {}}
        if path == self.uncertain_path:
            self.writes.append(path)
            raise FuploadError("network interrupted", business_code="network_error", verification_required=True)
        if path == BACKUP_LIST:
            if self.fail_read_after_remove and BACKUP_REMOVE in self.writes:
                return {"status": "failed"}
            result = {"backupList": deepcopy(self.backups)}
        elif path == SHARE_LIST:
            assert query["my_publish"] == 1
            assert query["sort_by"] == "weekDownloadNum"
            rows = [row for row in self.shares if row["Strappid"] == query["strappid"]]
            offset = 0 if self.repeat_page else query["offset"]
            chunk = deepcopy(rows[offset:offset + query["limit"]])
            if self.missing_reference:
                for row in chunk:
                    row.pop("BackupID", None)
            result = {"shares": chunk}
        elif path == SHARE_DETAIL:
            row = next((row for row in self.shares if row["ShareID"] == query["share_id"]), None)
            result = deepcopy(row or {})
        elif path == SHARE_CREATE:
            self.writes.append(path)
            configuration = json.loads(body["configuration"])
            assert configuration["ID"] == query["backup_id"]
            new = {**configuration, "ShareID": "created", "BackupID": query["backup_id"]}
            new["SubscribeLevel"] = {"level": new["SubscribeLevel"]}
            self.shares.append(new)
            result = {"go_to_review": True}
        elif path == SHARE_UPDATE:
            self.writes.append(path)
            current = next(row for row in self.shares if row["ShareID"] == query["share_id"])
            if query.get("delete"):
                assert not body
                self.shares.remove(current)
            else:
                configuration = json.loads(body["configuration"])
                current.clear()
                current.update(configuration, ShareID=query["share_id"], BackupID=query["backup_id"])
                current["SubscribeLevel"] = {"level": current["SubscribeLevel"]}
            result = {}
        elif path == BACKUP_REMOVE:
            self.writes.append(path)
            self.backups = [row for row in self.backups if row["ID"] != query["backup_id"]]
            result = {}
        elif path == BACKUP_RENAME:
            self.writes.append(path)
            row = next(row for row in self.backups if row["ID"] == query["backup_id"])
            row["Name"] = query["new_name"]
            result = {}
        else:
            raise AssertionError(path)
        return {"status": "ok", "result": result}


class BlackboxConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.server = MemoryWorkshop()
        self.provider = Blackbox({"verify_attempts": 1, "verify_interval": 0}, self.server)

    def test_allowlist_uses_observed_post_routes(self):
        for path in (BACKUP_LIST, BACKUP_REMOVE, BACKUP_RENAME, SHARE_LIST, SHARE_DETAIL, SHARE_CREATE, SHARE_UPDATE):
            self.assertEqual(BlackboxWebSession._validate_request("POST", path), ("POST", path))
            with self.assertRaises(FuploadError):
                BlackboxWebSession._validate_request("GET", path)

    def test_list_get_use_full_backup_objects_and_exact_opaque_id(self):
        self.server.backups.append(backup("backup-aa"))
        self.assertEqual(self.provider.backup_list()["total_count"], 2)
        got = self.provider.backup_get("backup-a")["backup"]
        self.assertEqual(got["ID"], "backup-a")
        self.assertEqual(got["OpaqueBackupMetadata"], {"preserve": [1, 2, 3]})
        with self.assertRaises(FuploadError):
            self.provider.backup_get("backup-")

    def test_short_share_page_is_followed_until_empty(self):
        self.server.shares = [share()]
        result = self.provider.config_list("wowretail")
        self.assertTrue(result["complete"])
        self.assertEqual(result["total_count"], 1)
        offsets = [call[3]["offset"] for call in self.server.calls if call[1] == SHARE_LIST]
        self.assertEqual(offsets, [0, 20])

    def test_create_verification_fetches_details_when_list_omits_backup_reference(self):
        self.server.missing_reference = True
        result = self.provider.execute_write("config", "create", {"backup_id": "backup-a", "configuration": selection()})
        self.assertTrue(result["verified"])
        self.assertEqual(result["share_id"], "created")
        self.assertEqual(self.server.writes.count(SHARE_CREATE), 1)

    def test_config_create_binds_backup_and_preserves_unknown_metadata(self):
        result = self.provider.execute_write("config", "create", {"backup_id": "backup-a", "configuration": selection()})
        self.assertTrue(result["verified"])
        self.assertEqual(result["share_id"], "created")
        write = next(call for call in self.server.calls if call[1] == SHARE_CREATE)
        config = json.loads(write[2]["configuration"])
        self.assertEqual(config["OpaqueBackupMetadata"], backup()["OpaqueBackupMetadata"])
        self.assertEqual(config["ID"], "backup-a")
        self.assertNotIn("UnknownAddons", config)
        self.assertNotIn("Materials", config)
        self.assertNotIn("Fonts", config)

    def test_config_create_requires_explicit_all_content_selections(self):
        value = selection()
        del value["Fonts"]
        with self.assertRaises(FuploadError) as error:
            self.provider.config_upsert({"backup_id": "backup-a", "configuration": value}, create=True)
        self.assertEqual(error.exception.kind, "validation_error")
        self.assertEqual(self.server.writes, [])

    def test_config_title_matches_official_javascript_weighted_limit(self):
        # The shipped editor treats Latin-1 as one UTF-16 unit, CJK as two,
        # and an astral character's surrogate pair as four weighted units.
        for title in ("a" * 70, "é" * 70, "中" * 35, "😀" * 17 + "aa"):
            with self.subTest(valid=title):
                self.provider._validate_configuration({**selection(), "Title": title})
        for title in ("a" * 71, "é" * 71, "中" * 36, "😀" * 18):
            with self.subTest(invalid=title), self.assertRaises(FuploadError):
                self.provider.config_upsert({"backup_id": "backup-a", "configuration": {**selection(), "Title": title}}, create=True)
        self.assertEqual(self.server.writes, [])

    def test_public_share_requires_preview_but_private_share_does_not(self):
        value = {**selection(), "ThumbList": []}
        with self.assertRaises(FuploadError):
            self.provider.config_upsert({"backup_id": "backup-a", "configuration": value}, create=True)
        self.assertEqual(self.server.writes, [])
        value["Open"] = False
        self.provider._validate_configuration(value)

    def test_empty_content_is_rejected_before_remote_write(self):
        value = {**selection(), "KnownAddons": [], "WTFList": [], "Open": False}
        with self.assertRaises(FuploadError):
            self.provider.config_upsert({"backup_id": "backup-a", "configuration": value}, create=True)
        self.server.shares = [share()]
        with self.assertRaises(FuploadError):
            self.provider.config_upsert({"share_id": "share-a", "configuration": {"KnownAddons": []}})
        self.assertEqual(self.server.writes, [])

    def test_file_selection_preserves_complete_backup_container_metadata(self):
        value = selection()
        value["UnknownAddons"] = {"Files": [{"Name": "Unknown", "Size": 2}]}
        self.provider.config_upsert({"backup_id": "backup-a", "configuration": value}, create=True)
        write = next(call for call in self.server.calls if call[1] == SHARE_CREATE)
        sent = json.loads(write[2]["configuration"])
        self.assertEqual(sent["UnknownAddons"]["Url"], backup()["UnknownAddons"]["Url"])

    def test_config_identity_cannot_be_overridden(self):
        for key in ("ID", "IsClassic", "Strappid"):
            value = selection()
            value[key] = "wrong"
            with self.assertRaises(FuploadError):
                self.provider.config_upsert({"backup_id": "backup-a", "configuration": value}, create=True)
        self.assertEqual(self.server.writes, [])

    def test_sparse_update_preserves_exact_rich_text_images_and_selections(self):
        current = share()
        current["Article"] = '<p data-x="a"><img src="https://cdn.example/img?q=original"></p>'
        current["UpdateLog"] = "<p><strong>Unchanged &amp; exact</strong></p>"
        current["ThumbList"] = ["https://cdn.example/image?format=webp"]
        self.server.shares = [deepcopy(current)]
        result = self.provider.execute_write("config", "edit", {"share_id": "share-a", "configuration": {"Title": "new title"}})
        self.assertTrue(result["verified"])
        self.assertEqual(result["readback"]["ThumbList"], current["ThumbList"])
        self.assertEqual(result["readback"]["Article"], current["Article"])
        write = next(call for call in self.server.calls if call[1] == SHARE_UPDATE)
        value = json.loads(write[2]["configuration"])
        for key in ("Article", "UpdateLog", "ThumbList", "KnownAddons", "WTFList"):
            self.assertEqual(value[key], current[key])
        self.assertEqual(value["SubscribeLevel"], 0)
        self.assertNotIn("ShareID", value)

    def test_changing_backup_requires_all_selections_again(self):
        self.server.shares = [share()]
        self.server.backups.append(backup("backup-b"))
        with self.assertRaises(FuploadError):
            self.provider.config_upsert({"share_id": "share-a", "backup_id": "backup-b", "configuration": {"Title": "new"}})
        self.assertEqual(self.server.writes, [])
        result = self.provider.config_upsert({"share_id": "share-a", "backup_id": "backup-b", "configuration": selection()})
        self.assertEqual(result["backup_id"], "backup-b")

    def test_changing_backup_does_not_carry_old_archive_metadata(self):
        old = share()
        old["UnknownAddons"] = deepcopy(backup()["UnknownAddons"])
        old["UnknownAddons"]["Url"] = "https://cdn.example/old.zip"
        self.server.shares = [old]
        new = backup("backup-b")
        new["UnknownAddons"]["Url"] = "https://cdn.example/new.zip"
        self.server.backups.append(new)
        value = selection()
        value["UnknownAddons"] = {"Files": [{"Name": "Unknown", "Size": 2}]}
        self.provider.config_upsert({"share_id": "share-a", "backup_id": "backup-b", "configuration": value})
        write = next(call for call in self.server.calls if call[1] == SHARE_UPDATE)
        sent = json.loads(write[2]["configuration"])
        self.assertEqual(sent["UnknownAddons"]["Url"], "https://cdn.example/new.zip")

    def test_selection_must_belong_to_bound_backup(self):
        for patch in ({"KnownAddons": [{"ID": 999}]}, {"Fonts": {"Files": [{"Name": "other.ttf"}]}},
                      {"WTFList": [{"Name": "OTHER", "RealmCharacters": [{"Realm": "Realm", "Player": "Player"}]}]},
                      {"WTFList": [{"Name": "ACCOUNT", "RealmCharacters": [{"Realm": "Realm", "Player": "Other"}]}]}):
            with self.assertRaises(FuploadError):
                self.provider.config_upsert({"backup_id": "backup-a", "configuration": {**selection(), **patch}}, create=True)
        self.assertEqual(self.server.writes, [])

    def test_config_delete_query_has_both_ids_and_no_body(self):
        self.server.shares = [share()]
        result = self.provider.config_delete({"share_id": "share-a", "confirm_delete": True})
        self.assertTrue(result["verified"])
        call = next(call for call in self.server.calls if call[1] == SHARE_UPDATE)
        self.assertEqual(call[3], {"share_id": "share-a", "backup_id": "backup-a", "delete": 1})
        self.assertEqual(call[2], {})

    def test_backup_rename_reads_back(self):
        result = self.provider.backup_rename({"backup_id": "backup-a", "name": "New name"})
        self.assertTrue(result["verified"])
        self.assertEqual(self.server.backups[0]["Name"], "New name")

    def test_referenced_backup_blocks_entire_batch(self):
        self.server.backups.append(backup("backup-b"))
        self.server.shares = [share()]
        plan = self.provider.backup_delete_preview({"backup_ids": ["backup-b", "backup-a"]})
        self.assertFalse(plan["allowed"])
        self.assertEqual(plan["items"][1]["referenced_by"], ["share-a"])
        with self.assertRaises(FuploadError) as error:
            self.provider.backup_delete({"backup_ids": ["backup-b", "backup-a"], "confirm_delete": True})
        self.assertEqual(error.exception.kind, "backup_in_use")
        self.assertEqual(self.server.writes, [])

    def test_unknown_or_duplicate_backup_rejects_entire_batch(self):
        for ids in (["backup-a", "missing"], ["backup-a", "backup-a"]):
            with self.assertRaises(FuploadError):
                self.provider.backup_delete({"backup_ids": ids, "confirm_delete": True})
        self.assertEqual(self.server.writes, [])

    def test_name_and_timestamp_filters_are_explicit_and_protected(self):
        self.server.backups[0]["SaveTime"] = 100
        other = backup("backup-b")
        other.update(Name="Other name", SaveTime=200)
        self.server.backups.append(other)
        plan = self.provider.backup_delete_preview({"name_contains": "Original", "created_before": 150})
        self.assertEqual([row["backup_id"] for row in plan["items"]], ["backup-a"])
        self.server.shares = [share()]
        with self.assertRaises(FuploadError) as error:
            self.provider.backup_delete({"name_equals": "Original backup", "confirm_delete": True})
        self.assertEqual(error.exception.kind, "backup_in_use")
        self.assertEqual(self.server.writes, [])
        for doc in ({}, {"backup_ids": ["backup-a"], "name_contains": "Original"}, {"created_before": "2020-01-01"}):
            with self.assertRaises(FuploadError):
                self.provider.backup_delete_preview(doc)

    def test_backup_delete_requires_confirmation_and_dry_run_is_read_only(self):
        with self.assertRaises(FuploadError):
            self.provider.backup_delete({"backup_id": "backup-a"})
        preview = self.provider.backup_delete({"backup_id": "backup-a", "dry_run": True})
        self.assertTrue(preview["allowed"])
        self.assertTrue(preview["dry_run"])
        self.assertEqual(self.server.writes, [])

    def test_batch_delete_rechecks_references_and_verifies_each_removal(self):
        self.server.backups.append(backup("backup-b"))
        result = self.provider.backup_delete({"backup_ids": ["backup-a", "backup-b"], "confirm_delete": True})
        self.assertTrue(result["verified"])
        self.assertEqual(result["deleted_backup_ids"], ["backup-a", "backup-b"])
        self.assertEqual(self.server.writes, [BACKUP_REMOVE, BACKUP_REMOVE])
        self.assertEqual(self.server.backups, [])

    def test_new_reference_between_batch_items_stops_remaining_deletions(self):
        self.server.backups.append(backup("backup-b"))
        def transport(method, path, body, query):
            result = self.server(method, path, body, query)
            if path == BACKUP_REMOVE and query["backup_id"] == "backup-a":
                self.server.shares.append(share("new-share", "backup-b"))
            return result
        provider = Blackbox({"verify_attempts": 1}, transport)
        with self.assertRaises(FuploadError) as error:
            provider.backup_delete({"backup_ids": ["backup-a", "backup-b"], "confirm_delete": True})
        self.assertEqual(error.exception.kind, "backup_in_use")
        self.assertEqual(error.exception.details["deleted_backup_ids"], ["backup-a"])
        self.assertEqual(error.exception.details["failed_backup_id"], "backup-b")
        self.assertEqual(self.server.writes, [BACKUP_REMOVE])
        self.assertEqual([row["ID"] for row in self.server.backups], ["backup-b"])

    def test_ambiguous_create_readback_does_not_retry_write(self):
        def transport(method, path, body, query):
            result = self.server(method, path, body, query)
            if path == SHARE_CREATE:
                duplicate = deepcopy(self.server.shares[-1])
                duplicate["ShareID"] = "another-created"
                self.server.shares.append(duplicate)
            return result
        provider = Blackbox({"verify_attempts": 1}, transport)
        with self.assertRaises(FuploadError) as error:
            provider.config_upsert({"backup_id": "backup-a", "configuration": selection()}, create=True)
        self.assertTrue(error.exception.verification_required)
        self.assertEqual(self.server.writes, [SHARE_CREATE])

    def test_missing_summary_reference_is_resolved_by_detail_and_blocks(self):
        self.server.shares = [share()]
        self.server.missing_reference = True
        plan = self.provider.backup_delete_preview({"backup_id": "backup-a"})
        self.assertFalse(plan["allowed"])
        self.assertIn(SHARE_DETAIL, [call[1] for call in self.server.calls])

    def test_unknown_reference_fails_closed(self):
        current = share()
        del current["BackupID"]
        self.server.shares = [current]
        with self.assertRaises(FuploadError) as error:
            self.provider.backup_delete({"backup_id": "backup-a", "confirm_delete": True})
        self.assertTrue(error.exception.verification_required)
        self.assertEqual(self.server.writes, [])

    def test_malformed_reference_is_unknown_and_never_authorizes_deletion(self):
        self.server.shares = [{**share(), "BackupID": {"ID": "backup-a"}}]
        with self.assertRaises(FuploadError) as error:
            self.provider.backup_delete({"backup_id": "backup-a", "confirm_delete": True})
        self.assertTrue(error.exception.verification_required)
        self.assertEqual(self.server.writes, [])

    def test_repeated_share_page_or_pagination_cap_never_authorizes_delete(self):
        self.server.shares = [share()]
        self.server.repeat_page = True
        for provider in (self.provider, Blackbox({"config_max_pages": 1}, self.server)):
            with self.assertRaises(FuploadError) as error:
                provider.backup_delete({"backup_id": "backup-a", "confirm_delete": True})
            self.assertTrue(error.exception.verification_required)
        self.assertEqual(self.server.writes, [])

    def test_business_failure_and_uncertain_mutation_are_not_retried(self):
        for path in (BACKUP_RENAME,):
            self.server.error_path = path
            with self.assertRaises(FuploadError) as error:
                self.provider.backup_rename({"backup_id": "backup-a", "name": "New"})
            self.assertTrue(error.exception.verification_required)
            self.assertEqual(sum(call[1] == path for call in self.server.calls), 1)
        self.server.calls.clear()
        self.server.error_path = None
        self.server.uncertain_path = BACKUP_REMOVE
        with self.assertRaises(FuploadError) as error:
            self.provider.backup_delete({"backup_id": "backup-a", "confirm_delete": True})
        self.assertTrue(error.exception.verification_required)
        self.assertEqual(self.server.writes, [BACKUP_REMOVE])

    def test_delayed_delete_visibility_only_repeats_reads(self):
        stale_reads = []
        def transport(method, path, body, query):
            if path == BACKUP_LIST and BACKUP_REMOVE in self.server.writes and not stale_reads:
                stale_reads.append(path)
                return {"status": "ok", "result": {"backupList": [backup()]}}
            return self.server(method, path, body, query)
        provider = Blackbox({"verify_attempts": 3, "verify_interval": 0}, transport)
        result = provider.backup_delete({"backup_ids": ["backup-a"], "confirm_delete": True})
        self.assertTrue(result["verified"])
        self.assertEqual(stale_reads, [BACKUP_LIST])
        self.assertEqual(self.server.writes.count(BACKUP_REMOVE), 1)

    def test_delete_visibility_timeout_is_bounded_without_mutation_replay(self):
        readbacks = []
        def transport(method, path, body, query):
            if path == BACKUP_LIST and BACKUP_REMOVE in self.server.writes:
                readbacks.append(path)
                return {"status": "ok", "result": {"backupList": [backup()]}}
            return self.server(method, path, body, query)
        provider = Blackbox({"verify_attempts": 3, "verify_interval": 0}, transport)
        with self.assertRaises(FuploadError) as error:
            provider.backup_delete({"backup_ids": ["backup-a"], "confirm_delete": True})
        self.assertTrue(error.exception.verification_required)
        self.assertEqual(len(readbacks), 3)
        self.assertEqual(self.server.writes.count(BACKUP_REMOVE), 1)

    def test_readback_failure_after_delete_requires_verification(self):
        self.server.fail_read_after_remove = True
        with self.assertRaises(FuploadError) as error:
            self.provider.backup_delete({"backup_id": "backup-a", "confirm_delete": True})
        self.assertTrue(error.exception.verification_required)
        self.assertEqual(self.server.writes, [BACKUP_REMOVE])


class BlackboxBackupPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.game = self.directory / "_retail_"
        for name, content in {
            "Interface/AddOns/Custom/Custom.toc": "## Title: Custom",
            "Interface/AddOns/Custom/Custom.lua": "print('addon')",
            "Interface/Textures/texture.blp": "texture",
            "Fonts/FRIZQT__.TTF": "font",
            "WTF/Account/ACCOUNT/Realm/Player/config-cache.wtf": "SET test 1",
            "WTF/Account/ACCOUNT/Realm/OtherPlayer/config-cache.wtf": "SET private 1",
            "WTF/Account/ACCOUNT/OtherRealm/Unselected/config-cache.wtf": "SET private 2",
            "WTF/Account/ACCOUNT/SavedVariables/Addon.lua": "Saved = {}",
            "WTF/Account/ACCOUNT/SavedVariables/HeyboxPlayerInfo.lua": "skip",
            "WTF/Account/ACCOUNT/SavedVariables/HeyboxPlayerInfo.lua.bak": "skip",
        }.items():
            path = self.game / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.request_doc = {"game_dir": str(self.game), "output_dir": str(self.directory / "package"),
                            "strappid": "wowretail", "unknown_addons": ["Custom"], "wtf_accounts": [{"name": "ACCOUNT", "characters": [{"realm": "Realm", "player": "Player"}]}],
                            "materials": ["Textures"], "fonts": ["FRIZQT__.TTF"], "known_addons": []}
        self.calls = []
        self.saved = None
        self.failure_path = None
        self.limit = 1024 * 1024
        def transport(method, path, body, query):
            self.calls.append((method, path, deepcopy(body), deepcopy(query)))
            if path == self.failure_path:
                raise FuploadError("request interrupted", business_code="network_error")
            if path == BACKUP_CREATE:
                result = {"ID": 42, "MaxSize": self.limit}
            elif path == BACKUP_CREDENTIAL:
                result = {"host": "https://cdn.example/", "path": query["file_type"] + "/archive.zip"}
            elif path == BACKUP_SAVE:
                self.saved = json.loads(base64.b64decode(body["configuration"]).decode("utf-8"))
                result = {}
            elif path == BACKUP_LIST:
                result = {"backupList": [self.saved] if self.saved else []}
            else:
                raise AssertionError(path)
            return {"status": "ok", "result": result}
        self.provider = Blackbox({"verify_attempts": 1, "verify_interval": 0}, transport)

    def package(self):
        return self.provider.execute_write("backup", "generate", self.request_doc)["file"]

    def test_create_is_local_and_zip_layout_matches_official_categories(self):
        file = self.package()
        self.assertEqual(self.calls, [])
        manifest = json.loads(Path(file).read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["archives"]), 4)
        self.assertEqual(manifest["configuration"]["WTFList"][0]["RealmCharacters"], [{"Realm": "Realm", "Player": "Player"}])
        for row in manifest["archives"]:
            with zipfile.ZipFile(Path(file).parent / row["file"]) as archive:
                names = archive.namelist()
                self.assertTrue(all(not name.startswith(("/", "unknown/", "materials/", "fonts/")) for name in names))
                self.assertFalse(any("HeyboxPlayerInfo" in name for name in names))
                if row["file_type"] == "unknownModules":
                    self.assertIn("Custom/Custom.toc", names)
                if row["file_type"] == "wtf":
                    self.assertIn("ACCOUNT/Realm/Player/config-cache.wtf", names)
                    self.assertFalse(any("OtherPlayer" in name or "OtherRealm" in name for name in names))
                    self.assertIn("ACCOUNT/SavedVariables/Addon.lua", names)

    def test_scan_lists_account_characters_without_network_or_writes(self):
        result = self.provider.execute_read("backup", "scan", {"game_dir": str(self.game), "strappid": "wowretail"})
        self.assertEqual(result["unknown_addons"], ["Custom"])
        characters = result["wtf_accounts"][0]["characters"]
        self.assertIn({"realm": "Realm", "player": "Player"}, characters)
        self.assertIn({"realm": "Realm", "player": "OtherPlayer"}, characters)
        self.assertEqual(self.calls, [])

    def test_whole_account_implicit_or_unknown_character_selection_is_rejected(self):
        for accounts in (["ACCOUNT"], [{"name": "ACCOUNT", "characters": []}],
                         [{"name": "ACCOUNT", "characters": [{"realm": "Realm", "player": "Missing"}]}]):
            with self.assertRaises(FuploadError):
                self.provider.backup_generate({**self.request_doc, "wtf_accounts": accounts})
        self.assertFalse(Path(self.request_doc["output_dir"]).exists())

    def test_create_combines_generate_and_upload(self):
        with patch.object(self.provider, "_upload_backup_archive", return_value=("https://cdn.example/", "archive.zip")):
            result = self.provider.execute_write("backup", "create", self.request_doc)
        self.assertTrue(result["verified"])
        self.assertTrue(Path(result["file"]).is_file())
        self.assertEqual(sum(call[1] == BACKUP_CREATE for call in self.calls), 1)

    def test_create_dry_run_does_not_create_output_or_session(self):
        result = self.provider.backup_generate({**self.request_doc, "dry_run": True})
        self.assertTrue(result["dry_run"])
        self.assertFalse(Path(self.request_doc["output_dir"]).exists())
        self.assertEqual(self.calls, [])

    def test_all_file_categories_need_explicit_selections(self):
        doc = dict(self.request_doc)
        del doc["wtf_accounts"]
        with self.assertRaises(FuploadError):
            self.provider.backup_generate(doc)
        self.assertEqual(self.calls, [])

    def test_path_traversal_and_output_in_game_are_rejected(self):
        for field, value in (("unknown_addons", ["../Custom"]), ("materials", ["AddOns"]), ("output_dir", str(self.game / "out"))):
            with self.assertRaises(FuploadError):
                self.provider.backup_generate({**self.request_doc, field: value})
        self.assertFalse((self.game / "out").exists())

    def test_tampered_archive_is_rejected_before_allocating_backup(self):
        file = self.package()
        archive = Path(file).parent / "unknown.zip"
        with archive.open("ab") as stream:
            stream.write(b"tamper")
        with self.assertRaises(FuploadError):
            self.provider.backup_upload({"file": file})
        self.assertEqual(self.calls, [])

    def test_upload_uses_backup_routes_base64_save_and_exact_readback(self):
        file = self.package()
        def upload(path, context, md5):
            self.assertTrue(path.is_file())
            return context["host"], context["path"]
        with patch.object(self.provider, "_upload_backup_archive", side_effect=upload) as upload_mock:
            result = self.provider.execute_write("backup", "upload", {"file": file})
        self.assertTrue(result["verified"])
        self.assertEqual(result["backup_id"], "42")
        self.assertEqual(upload_mock.call_count, 4)
        paths = [call[1] for call in self.calls]
        self.assertEqual(paths.count(BACKUP_CREATE), 1)
        self.assertEqual(paths.count(BACKUP_SAVE), 1)
        self.assertNotIn("/wow/cos/upload/token/", paths)
        types = [call[3]["file_type"] for call in self.calls if call[1] == BACKUP_CREDENTIAL]
        self.assertEqual(types, ["unknownModules", "materials", "fonts", "wtf"])
        self.assertEqual(self.saved["UnknownAddons"]["Path"], "unknownModules/archive.zip")

    def test_upload_dry_run_does_not_allocate_or_upload(self):
        file = self.package()
        result = self.provider.backup_upload({"file": file, "dry_run": True})
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.calls, [])

    def test_server_size_limit_blocks_all_archive_uploads(self):
        file = self.package()
        self.limit = 1
        with patch.object(self.provider, "_upload_backup_archive") as uploader:
            with self.assertRaises(FuploadError) as error:
                self.provider.backup_upload({"file": file})
        self.assertTrue(error.exception.verification_required)
        self.assertEqual(error.exception.details["backup_id"], "42")
        uploader.assert_not_called()
        self.assertEqual([call[1] for call in self.calls], [BACKUP_CREATE])

    def test_uncertain_save_is_not_replayed_and_keeps_allocated_id(self):
        file = self.package()
        self.failure_path = BACKUP_SAVE
        with patch.object(self.provider, "_upload_backup_archive", return_value=("https://cdn.example/", "archive.zip")):
            with self.assertRaises(FuploadError) as error:
                self.provider.backup_upload({"file": file})
        self.assertTrue(error.exception.verification_required)
        self.assertEqual(error.exception.details["backup_id"], "42")
        self.assertEqual(sum(call[1] == BACKUP_SAVE for call in self.calls), 1)
        self.assertEqual(sum(call[1] == BACKUP_CREATE for call in self.calls), 1)

    def test_real_cos_adapter_uses_zero_retry_and_verifies_etag(self):
        file = self.package()
        manifest = json.loads(Path(file).read_text(encoding="utf-8"))
        item = manifest["archives"][0]
        context = {"cos": "https://bucket-123.cos.ap-shanghai.myqcloud.com", "host": "https://cdn.example/", "path": "key.zip",
                   "Credentials": {"Credentials": {"TmpSecretID": "test-id", "TmpSecretKey": "test-key", "Token": "test-session"}}}
        with patch("qcloud_cos.CosS3Client") as client:
            def prepare_upload(**kwargs):
                import requests
                from qcloud_cos.cos_comm import mapped
                headers = mapped({key: value for key, value in kwargs.items() if key in {"ContentLength", "StorageClass"}})
                requests.Request("PUT", "https://example.com/key.zip", headers=headers, data=kwargs["Body"]).prepare()
                return {"ETag": '"' + item["md5"] + '"'}
            client.return_value.put_object.side_effect = prepare_upload
            value = self.provider._upload_backup_archive(Path(file).parent / item["file"], context, item["md5"])
            self.assertEqual(value, ("https://cdn.example/", "key.zip"))
            self.assertEqual(client.call_args.kwargs["retry"], 0)
            self.assertEqual(client.return_value.put_object.call_args.kwargs["Bucket"], "bucket-123")
        with self.assertRaises(FuploadError):
            self.provider._upload_backup_archive(Path(file), {**context, "cos": "https://evil.example"}, item["md5"])

    def test_cos_failure_or_wrong_checksum_is_not_retried(self):
        file = self.package()
        manifest = json.loads(Path(file).read_text(encoding="utf-8"))
        item = manifest["archives"][0]
        context = {"cos": "https://bucket-123.cos.ap-beijing.myqcloud.com", "host": "https://cdn.example/", "path": "key.zip",
                   "Credentials": {"Credentials": {"TmpSecretID": "test-id", "TmpSecretKey": "test-key", "Token": "test-session"}}}
        for interrupt in (True, False):
            with patch("qcloud_cos.CosS3Client") as client:
                if interrupt:
                    client.return_value.put_object.side_effect = RuntimeError("interrupted")
                else:
                    client.return_value.put_object.return_value = {"ETag": '"wrong"'}
                with self.assertRaises(FuploadError) as error:
                    self.provider._upload_backup_archive(Path(file).parent / item["file"], context, item["md5"])
                self.assertTrue(error.exception.verification_required)
                self.assertEqual(client.return_value.put_object.call_count, 1)

    def test_manifest_character_metadata_cannot_hide_an_archived_character(self):
        file = self.package()
        path = Path(file)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        account = manifest["configuration"]["WTFList"][0]
        account["RealmCharacters"] = [{"Realm": "Realm", "Player": "OtherPlayer"}]
        account["Characters"] = ["Realm - OtherPlayer"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(FuploadError):
            self.provider.backup_upload({"file": file})
        self.assertEqual(self.calls, [])

    def test_known_addon_only_package_has_no_upload_archives(self):
        doc = {**self.request_doc, "unknown_addons": [], "wtf_accounts": [], "materials": [], "fonts": [],
               "known_addons": [{"ID": 7, "Name": "Addon", "Strategy": 1, "VersionID": 8, "VersionName": "1"}]}
        generated = self.provider.backup_generate(doc)
        with patch.object(self.provider, "_upload_backup_archive") as uploader:
            result = self.provider.backup_upload({"file": generated["file"]})
        self.assertTrue(result["verified"])
        uploader.assert_not_called()
        self.assertEqual(result["archive_count"], 0)


if __name__ == "__main__":
    unittest.main()
