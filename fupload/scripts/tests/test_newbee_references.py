"""Relationship readback uses the Creator picker's source type namespace."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fupload_cli.errors import FuploadError
from fupload_cli.newbee import NewBee


class ReferenceReadbackTests(unittest.TestCase):
    def provider(self, readback):
        provider = NewBee()
        provider.post = Mock(side_effect=[{}, readback])
        return provider

    def call(self, provider, refs=None):
        return provider.execute_write('plugin-reference', 'set', {
            'source_id': 101, 'references': refs if refs is not None else [{'type': 1, 'id': 31228}],
        })

    def test_display_type_is_normalized_using_official_picker_source_type(self):
        provider = self.provider({'references': [{'type': 2, 'id': 31228, 'title': 'Synthetic display row'}]})
        result = self.call(provider)
        self.assertEqual(result['readback']['references'][0]['type'], 2)
        self.assertEqual(provider.post.call_args_list[0].args, ('/creator/content_reference/set', {
            'source_type': 1, 'source_id': 101, 'references': [{'type': 1, 'id': 31228}],
        }))
        self.assertEqual(provider.post.call_args_list[1].args, ('/creator/content_reference/list', {'content_type': 1, 'content_id': 101}))
        self.assertEqual(provider.post.call_count, 2)

    def test_wrong_target_id_cannot_be_hidden_by_type_normalization(self):
        provider = self.provider({'references': [{'type': 2, 'id': 999}]})
        with self.assertRaises(FuploadError) as caught:
            self.call(provider)
        self.assertTrue(caught.exception.verification_required)
        self.assertEqual(provider.post.call_count, 2)

    def test_same_numeric_id_cannot_hide_missing_unknown_or_wrong_display_type(self):
        for resource, wire_type, display_type in (('plugin', 1, 2), ('wa', 2, 3), ('config', 3, 4)):
            for returned in ({}, {'type': 999}, {'type': True}, {'type': 2.5},
                             {'type': str(display_type) + '.0'}, {'type': wire_type},
                             {'type': display_type, 'content_type': 999}):
                with self.subTest(resource=resource, returned=returned):
                    provider = self.provider({'references': [{'id': 31228, **returned}]})
                    with self.assertRaises(FuploadError) as caught:
                        provider.execute_write(resource + '-reference', 'set', {
                            'source_id': 101, 'references': [{'type': wire_type, 'id': 31228}],
                        })
                    self.assertTrue(caught.exception.verification_required)
                    self.assertEqual(provider.post.call_count, 2)

    def test_all_observed_display_types_map_to_the_exact_picker_type(self):
        for resource, wire_type, display_type in (('plugin', 1, 2), ('wa', 2, 3), ('config', 3, 4)):
            for value in (display_type, str(display_type)):
                with self.subTest(resource=resource, value=value):
                    provider = self.provider({'references': [{'id': 31228, 'type': value}]})
                    provider.execute_write(resource + '-reference', 'set', {
                        'source_id': 101, 'references': [{'type': wire_type, 'id': 31228}],
                    })
                    self.assertEqual(provider.post.call_count, 2)

    def test_config_display_type_four_preserves_wire_type_three_and_exact_target(self):
        provider = self.provider({'references': [{'type': 4, 'id': 62444}]})
        result = provider.execute_write('config-reference', 'set', {
            'source_id': 62445, 'references': [{'type': 3, 'id': 62444}],
        })
        self.assertEqual(result['readback']['references'], [{'type': 4, 'id': 62444}])
        self.assertEqual(provider.post.call_args_list[0].args, ('/creator/content_reference/set', {
            'source_type': 3, 'source_id': 62445, 'references': [{'type': 3, 'id': 62444}],
        }))
        self.assertEqual(provider.post.call_args_list[1].args, (
            '/creator/content_reference/list', {'content_type': 3, 'content_id': 62445}))
        self.assertEqual(provider.post.call_count, 2)

    def test_config_display_type_four_cannot_hide_source_or_target_conflict(self):
        for readback in (
            {'source_type': 4, 'references': [{'type': 4, 'id': 62444}]},
            {'content_type': 4, 'references': [{'type': 4, 'id': 62444}]},
            {'references': [{'source_type': 4, 'type': 4, 'id': 62444}]},
            {'references': [{'source_id': 999, 'type': 4, 'id': 62444}]},
            {'references': [{'type': 4, 'id': 999}]},
        ):
            with self.subTest(readback=readback):
                provider = self.provider(readback)
                with self.assertRaises(FuploadError) as caught:
                    provider.execute_write('config-reference', 'set', {
                        'source_id': 62445, 'references': [{'type': 3, 'id': 62444}],
                    })
                self.assertTrue(caught.exception.verification_required)
                self.assertEqual(provider.post.call_count, 2)

    def test_conflicting_explicit_source_identity_is_rejected(self):
        for identity in ({'source_type': 2}, {'content_type': 2}, {'source_id': 999}, {'content_id': 999}):
            for nested in ((False, True) if next(iter(identity)).startswith('source_') else (False,)):
                with self.subTest(identity=identity, nested=nested):
                    row = {'type': 1, 'id': 31228}
                    readback = {'references': [{**row, **identity}]} if nested else {**identity, 'references': [row]}
                    provider = self.provider(readback)
                    with self.assertRaises(FuploadError) as caught:
                        self.call(provider)
                    self.assertTrue(caught.exception.verification_required)
                    self.assertEqual(provider.post.call_count, 2)

    def test_cross_type_expectation_is_not_normalized_to_request_source(self):
        provider = self.provider({'references': [{'type': 1, 'id': 31228}]})
        with self.assertRaises(FuploadError):
            self.call(provider, [{'type': 2, 'id': 31228}])

    def test_cross_type_request_cannot_use_a_raw_display_type_match(self):
        provider = self.provider({'references': [{'type': 2, 'id': 31228}]})
        with self.assertRaises(FuploadError) as caught:
            self.call(provider, [{'type': 2, 'id': 31228}])
        self.assertTrue(caught.exception.verification_required)

    def test_cross_type_readback_still_requires_the_target_namespace(self):
        provider = self.provider({'references': [{'type': 3, 'id': 31228}]})
        self.call(provider, [{'type': 2, 'id': 31228}])


if __name__ == '__main__':
    unittest.main()
