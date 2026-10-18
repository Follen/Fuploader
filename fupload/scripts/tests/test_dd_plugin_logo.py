from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.dd import DD
from fupload_cli.errors import FuploadError, ValidationError
from fupload_cli.schema import get_schema
from test_dd_wire_matrix import WireFixtures, WireSession


class DDPluginLogoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixtures = WireFixtures(Path(self.temp.name))

    def edit(self, session, **fields):
        schema = get_schema("dd", "plugin", "edit")
        doc = schema.validate({"schema": schema.name, "sn": "plugin-sn", **fields})
        return DD().execute_write_on(session, "plugin", "edit", doc)

    def test_logo_url_edit_preserves_entire_existing_form(self) -> None:
        baseline = WireSession(self.fixtures)
        self.edit(baseline)
        session = WireSession(self.fixtures)
        logo = "https://example.test/new-logo.png"
        result = self.edit(session, logo=logo)
        expected = {**baseline.mutations[0][1], "logo": logo}
        self.assertEqual(session.mutations, [("/addon/modify", expected)])
        self.assertEqual(session.uploads, [])
        self.assertEqual(result["logo_readback"], {"logo": logo, "source": "detail_v2"})

    def test_local_logo_reuses_media_upload_and_author_readback(self) -> None:
        session = WireSession(self.fixtures)
        before = copy.deepcopy(session.current["plugin"])
        with mock.patch("fupload_cli.dd.detail", return_value=before):
            result = self.edit(session, logo="https://example.test/ignored.png", logo_file=str(self.fixtures.image))
        upload = session.uploads[0]
        self.assertEqual(upload["business"], "addon")
        self.assertEqual(upload["file_name"], "")
        self.assertTrue(upload["media"])
        self.assertEqual(upload["max_bytes"], 10 * 1024 * 1024)
        posted = session.mutations[0][1]
        self.assertEqual(result["logo_readback"], {"logo": posted["logo"], "source": "author_list"})
        self.assertNotEqual(posted["logo"], before["logo"])
        self.assertEqual(len(session.mutations), 1)

    def test_backend_acceptance_without_changed_logo_is_not_success(self) -> None:
        session = WireSession(self.fixtures)
        original_post = session.post

        def ignore_logo(endpoint, body):
            old_logo = session.current["plugin"]["logo"]
            response = original_post(endpoint, body)
            session.current["plugin"]["logo"] = old_logo
            return response

        with mock.patch.object(session, "post", side_effect=ignore_logo), mock.patch("fupload_cli.dd.time.sleep"):
            with self.assertRaises(FuploadError) as caught:
                self.edit(session, logo="https://example.test/new-logo.png")
        self.assertTrue(caught.exception.verification_required)
        self.assertIn("logo", caught.exception.details["fields"])
        self.assertEqual(len(session.mutations), 1)

    def test_missing_local_logo_is_rejected_by_schema(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            self.edit(WireSession(self.fixtures), logo_file=str(Path(self.temp.name) / "missing.png"))
        self.assertEqual(caught.exception.details["path"], "$.logo_file")

    def test_version_update_does_not_accept_logo_fields(self) -> None:
        schema = get_schema("dd", "plugin", "update")
        for field in ("logo", "logo_file"):
            with self.subTest(field=field), self.assertRaisesRegex(ValidationError, "unknown field"):
                schema.validate({"schema": schema.name, "sn": "plugin-sn", field: "image"})
