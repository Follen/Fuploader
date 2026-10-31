"""The official UI parseWa bridge returns a promise, not a parsed result."""
import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock


class SynchronousWAParserTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'fupload_cli' / 'dd_sidecar.py'
        spec = importlib.util.spec_from_file_location('dd_wa_parser_fixture', source)
        self.native = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, {'NETEASE_DD_DIR': 'fixture', 'FUPLOAD_DD_DEVICE_STATE': 'fixture'}):
            spec.loader.exec_module(self.native)
        self.modules = {name: ModuleType(name) for name in (
            'components', 'components.wow_ui', 'components.wow_ui.wa',
            'components.wow_ui.wa.wa_parser')}

    def test_pending_ui_promise_is_not_mistaken_for_invalid_wa(self):
        parser = mock.Mock()
        parser.parseWa.return_value = {'code': 200, 'result': {'uid': 'fixture-uid', 'id': 'fixture-id'}}
        factory = mock.Mock(return_value=parser)
        self.modules['components.wow_ui.wa.wa_parser'].WaParser = factory
        container = mock.Mock()
        container.get_instance.return_value.parseWa.return_value = SimpleNamespace(state='pending')
        with mock.patch.dict(sys.modules, self.modules):
            value = self.native.parse_native_wa((None, container, None, None, None), '!WA:2!synthetic')
        self.assertEqual(value, {'parse_wa_uid': 'fixture-uid', 'parse_wa_id': 'fixture-id'})
        container.get_instance.assert_not_called()
        factory.assert_called_once_with(None)
        parser.parseWa.assert_called_once_with('!WA:2!synthetic')

    def test_decoder_rejection_does_not_use_async_bridge_as_fallback(self):
        parser = mock.Mock()
        parser.parseWa.return_value = {'code': 40001, 'msg': 'Invalid synthetic export', 'result': {}}
        self.modules['components.wow_ui.wa.wa_parser'].WaParser = mock.Mock(return_value=parser)
        container = mock.Mock()
        with mock.patch.dict(sys.modules, self.modules):
            with self.assertRaisesRegex(RuntimeError, 'Invalid synthetic export'):
                self.native.parse_native_wa((None, container, None, None, None), '!WA:2!synthetic')
        container.get_instance.assert_not_called()


if __name__ == '__main__':
    unittest.main()
