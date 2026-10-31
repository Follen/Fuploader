"""A request must use one server timestamp for both NEP signing and headers."""
import importlib.util
import itertools
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class CrossingSecondClient:
    def __init__(self):
        self.clock = itertools.count(100)
        self.observed = []
        self.fail_transport = False
        self._fupload_last_response_error = None

    def _get_current_server_ts(self):
        return next(self.clock)

    def get(self, path, params=None):
        return self._request(path)

    def post(self, path, params=None):
        return self._request(path)

    def _request(self, path):
        # These are the two reads made by the official client's signing and
        # header builders, with the clock crossing a second between them.
        signed = self._get_current_server_ts()
        header = self._get_current_server_ts()
        self.observed.append((signed, header))
        if self.fail_transport:
            raise OSError('synthetic transport failure')
        payload = {'code': 0} if signed == header else {'code': 409, 'msg': '签名无效'}
        self._fupload_last_response_error = {'body': json.dumps(payload)}
        return payload

    def login(self):
        return self.get('/user/dflogin')['code'] == 0

    def close(self):
        pass


class DDRequestClockTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'fupload_cli' / 'dd_sidecar.py'
        spec = importlib.util.spec_from_file_location('dd_request_clock_fixture', source)
        self.native = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, {'NETEASE_DD_DIR': 'fixture', 'FUPLOAD_DD_DEVICE_STATE': 'fixture'}):
            spec.loader.exec_module(self.native)

    def connect(self, client):
        return self.native.author_session_or_cleanup(mock.Mock(), None, None, None, client)

    def test_login_get_and_post_share_one_timestamp_per_request(self):
        client = CrossingSecondClient()
        self.connect(client)
        self.assertEqual(client.get('/options')['code'], 0)
        self.assertEqual(client.post('/wa/create', {})['code'], 0)
        self.assertEqual(client.observed, [(100, 100), (101, 101), (102, 102)])
        self.assertNotIn('_get_current_server_ts', vars(client))

    def test_clock_restored_after_transport_failure_without_replaying_post(self):
        client = CrossingSecondClient()
        self.connect(client)
        client.fail_transport = True
        with self.assertRaisesRegex(OSError, 'synthetic transport failure'):
            client.post('/wa/create', {})
        self.assertEqual(client.observed, [(100, 100), (101, 101)])
        self.assertNotIn('_get_current_server_ts', vars(client))
        client.fail_transport = False
        self.assertEqual(client.get('/options')['code'], 0)
        self.assertEqual(client.observed[-1], (102, 102))

    def test_existing_instance_clock_provider_is_restored(self):
        client = CrossingSecondClient()
        provider = client._get_current_server_ts
        client._get_current_server_ts = provider
        self.connect(client)
        self.assertIs(client._get_current_server_ts, provider)
        self.assertEqual(client.observed, [(100, 100)])

    def test_direct_login_samples_after_server_clock_synchronization(self):
        class DirectLoginClient(CrossingSecondClient):
            def login(self):
                # Official login updates server time before calling its signing
                # and header builders directly, without invoking self.get.
                self.clock = itertools.count(1000)
                return self._request('/user/dflogin')['code'] == 0

        client = DirectLoginClient()
        self.connect(client)
        self.assertEqual(client.observed, [(1000, 1000)])

    def test_installing_twice_does_not_layer_request_wrappers(self):
        client = CrossingSecondClient()
        self.native.stabilize_author_request_clock(client)
        original = client.post
        self.native.stabilize_author_request_clock(client)
        self.assertIs(client.post, original)


if __name__ == '__main__':
    unittest.main()
