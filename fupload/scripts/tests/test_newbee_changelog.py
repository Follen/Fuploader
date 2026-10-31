"""Version-log visibility checks use only mock Creator requests."""
import sys
import http.client
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fupload_cli.errors import FuploadError
from fupload_cli.newbee import NewBee


class PluginChangelogTests(unittest.TestCase):
    def edit(self, provider, text="New complete log"):
        with patch("time.sleep"):
            return provider.execute_write("plugin-changelog", "edit", {"file_id": 73, "changelog": text})

    def test_old_then_correct_body_polls_same_file_without_repeating_write(self):
        provider = NewBee()
        provider.post = Mock(side_effect=[{}, {"file_id": 73, "changelog": "Old log"}, {"file_id": 73, "changelog": "New complete log"}])
        result = self.edit(provider)
        self.assertEqual(result["readback"], {"file_id": 73, "changelog": "New complete log"})
        self.assertEqual(provider.post.call_args_list[0].args, ("/creator/wow/mod_file/edit_changelog", {"file_id": 73, "changelog": "New complete log"}))
        self.assertEqual([c.args for c in provider.post.call_args_list[1:]], [("/creator/wow/mod_file/get_changelog", {"file_id": 73})] * 2)

    def test_persistent_old_body_has_bounded_reads_and_one_write(self):
        provider = NewBee()
        provider.post = Mock(side_effect=lambda route, body: {} if route.endswith("/edit_changelog") else {"file_id": 73, "changelog": "Old log"})
        with self.assertRaises(FuploadError) as failed:
            self.edit(provider)
        self.assertTrue(failed.exception.verification_required)
        self.assertEqual(failed.exception.kind, "verification_required")
        self.assertFalse(failed.exception.details["automatic_retry"])
        writes = [c for c in provider.post.call_args_list if c.args[0].endswith("/edit_changelog")]
        reads = [c for c in provider.post.call_args_list if c.args[0].endswith("/get_changelog")]
        self.assertEqual(len(writes), 1)
        self.assertTrue(1 < len(reads) <= 5)

    def test_matching_text_from_another_file_is_never_accepted(self):
        provider = NewBee()
        provider.post = Mock(side_effect=lambda route, body: {} if route.endswith("/edit_changelog") else {"file_id": 999, "changelog": "New complete log"})
        with self.assertRaises(FuploadError) as failed:
            self.edit(provider)
        self.assertTrue(failed.exception.verification_required)
        self.assertEqual(sum(c.args[0].endswith("/edit_changelog") for c in provider.post.call_args_list), 1)
        self.assertTrue(all(c.args[1]["file_id"] == 73 for c in provider.post.call_args_list))

    def test_incomplete_read_after_write_requires_verification_without_replay(self):
        provider = NewBee()
        provider.post = Mock(side_effect=[{}, http.client.IncompleteRead(b'partial')])
        with self.assertRaises(FuploadError) as failed:
            self.edit(provider)
        self.assertTrue(failed.exception.verification_required)
        self.assertEqual(failed.exception.stage, 'readback')
        self.assertEqual(provider.post.call_count, 2)
        self.assertEqual(provider.post.call_args_list[0].args[0], '/creator/wow/mod_file/edit_changelog')
        self.assertEqual(provider.post.call_args_list[1].args[0], '/creator/wow/mod_file/get_changelog')

    def test_unparseable_digit_id_after_write_requires_verification(self):
        provider = NewBee()
        provider.post = Mock(side_effect=[{}, {'file_id': '²', 'changelog': 'New complete log'}])
        with self.assertRaises(FuploadError) as failed:
            self.edit(provider)
        self.assertTrue(failed.exception.verification_required)
        self.assertEqual(failed.exception.kind, 'verification_required')
        self.assertEqual(provider.post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
