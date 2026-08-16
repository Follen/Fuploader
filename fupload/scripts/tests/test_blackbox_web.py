from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.blackbox_web import (  # noqa: E402
    API_ORIGIN,
    API_PATHS,
    API_ROUTES,
    WEB_QUERY_KEYS,
    WORKSHOP_URL,
    BlackboxWebSession,
    WebSessionState,
    managed_profile_path,
    redact_recursive,
    web_hkey,
)
from fupload_cli.errors import FuploadError  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.ok = 200 <= status < 400

    def json(self):
        return self.payload


class FakeRequest:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("fake response queue exhausted")
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        return self._next("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._next("POST", url, **kwargs)


class FakePage:
    def __init__(self):
        self.visits = []
        self.url = ""

    def goto(self, url, **kwargs):
        self.visits.append((url, kwargs))
        self.url = url


class FakeContext:
    def __init__(self, responses, cookies=None):
        self.request = FakeRequest(responses)
        self.pages = [FakePage()]
        self.closed = False
        self._cookies = cookies or [
            {"name": "user_heybox_id", "value": "fixture-account"},
            {"name": "x_xhh_tokenid", "value": "fixture-risk"},
        ]

    def cookies(self, _urls=None):
        return list(self._cookies)

    def close(self):
        self.closed = True


class FakeLauncher:
    def __init__(self, contexts):
        self.contexts = list(contexts)
        self.calls = []

    def __call__(self, headless, profile):
        self.calls.append((headless, profile))
        if not self.contexts:
            raise AssertionError("fake context queue exhausted")
        return self.contexts.pop(0)


def response(status="ok", **result):
    return FakeResponse({"status": status, "result": result})


class BlackboxWebSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "state.json"
        self.state_patch = patch("fupload_cli.blackbox_web.managed_state_path", return_value=self.state_path)
        self.state_patch.start()

    def tearDown(self):
        self.state_patch.stop()
        self.tmp.cleanup()

    def test_headless_probe_uses_web_contract_and_becomes_ready(self):
        context = FakeContext([response(moduleList=[]), response(module={"id": 12})])
        launcher = FakeLauncher([context])
        session = BlackboxWebSession(browser_launcher=launcher)

        with patch("fupload_cli.blackbox_web.time.time", return_value=100), \
                patch("fupload_cli.blackbox_web.time.time_ns", return_value=200), \
                patch("fupload_cli.blackbox_web.secrets.token_hex", return_value="N"):
            payload = session.request("GET", "/wow/open_platform/module/detail/", query={"moduleId": 12})

        self.assertEqual(session.state, WebSessionState.READY)
        self.assertEqual(payload["result"]["module"]["id"], 12)
        self.assertEqual([item[0] for item in launcher.calls], [True])
        self.assertEqual(launcher.calls[0][1], managed_profile_path())
        self.assertEqual(context.pages[0].visits[0][0], WORKSHOP_URL)
        method, url, kwargs = context.request.calls[-1]
        self.assertEqual((method, url), ("GET", API_ORIGIN + "/wow/open_platform/module/detail/"))
        self.assertEqual(set(kwargs["params"]), WEB_QUERY_KEYS | {"moduleId"})
        self.assertEqual(kwargs["params"]["hkey"], web_hkey("/wow/open_platform/module/detail/", 101, kwargs["params"]["nonce"]))
        self.assertEqual(kwargs["headers"]["Referer"], WORKSHOP_URL)
        self.assertEqual(json.loads(self.state_path.read_text())["state"], "ready")

    def test_missing_session_opens_headed_then_returns_to_headless(self):
        first_headless = FakeContext([response("relogin")])
        headed = FakeContext([response("login"), response(moduleList=[])])
        second_headless = FakeContext([response(moduleList=[]), response(moduleList=[{"id": 1}])])
        launcher = FakeLauncher([first_headless, headed, second_headless])
        clock = iter([0.0, 0.0, 1.0])
        session = BlackboxWebSession(
            browser_launcher=launcher,
            poll_interval=0,
            monotonic=lambda: next(clock),
            sleep=lambda _: None,
        )

        payload = session.request("GET", "/wow/open_platform/module/list/")

        self.assertEqual(payload["result"]["moduleList"], [{"id": 1}])
        self.assertEqual(session.state, WebSessionState.READY)
        self.assertEqual([item[0] for item in launcher.calls], [True, False, True])
        self.assertTrue(first_headless.closed)
        self.assertTrue(headed.closed)
        self.assertFalse(second_headless.closed)

    def test_expired_get_reauthenticates_and_retries_read_only_request(self):
        initial = FakeContext([response(moduleList=[]), response("relogin")])
        headed = FakeContext([response(moduleList=[])])
        replacement = FakeContext([response(moduleList=[]), response(module={"id": 7})])
        launcher = FakeLauncher([initial, headed, replacement])
        session = BlackboxWebSession(browser_launcher=launcher)

        payload = session.request("GET", "/wow/open_platform/module/detail/", query={"moduleId": 7})

        self.assertEqual(payload["result"]["module"]["id"], 7)
        self.assertEqual([item[0] for item in launcher.calls], [True, False, True])

    def test_expired_post_is_uncertain_and_never_replayed(self):
        context = FakeContext([response(moduleList=[]), response("relogin")])
        launcher = FakeLauncher([context])
        session = BlackboxWebSession(browser_launcher=launcher)

        with self.assertRaises(FuploadError) as raised:
            session.request("POST", "/wow/open_platform/module/update/", body={"id": 7})

        self.assertTrue(raised.exception.verification_required)
        self.assertEqual([item[0] for item in launcher.calls], [True])
        self.assertEqual(len(context.request.calls), 2)

    def test_post_body_matches_website_repeat_array_encoding(self):
        context = FakeContext([response(moduleList=[]), response(updated=True)])
        session = BlackboxWebSession(browser_launcher=FakeLauncher([context]))

        session.request(
            "POST",
            "/wow/open_platform/module/update/",
            body={"id": 7, "categoryIds": [1014, 1015], "coreFolders": "TapTool"},
        )

        _method, _url, kwargs = context.request.calls[-1]
        self.assertEqual(
            kwargs["data"],
            "id=7&categoryIds=1014&categoryIds=1015&coreFolders=TapTool",
        )
        self.assertNotIn("form", kwargs)

    def test_protocol_allowlist_includes_upload_token_and_rejects_overrides(self):
        self.assertEqual(len(API_ROUTES), 7)
        self.assertEqual(len(API_PATHS), 7)
        launcher = FakeLauncher([])
        session = BlackboxWebSession(browser_launcher=launcher)
        invalid = (
            ("DELETE", "/wow/open_platform/module/list/"),
            ("GET", API_ORIGIN + "/wow/open_platform/module/list/"),
            ("GET", "/wow/open_platform/module/list/?offset=0"),
            ("GET", "/account/restore_login"),
        )
        for method, path in invalid:
            with self.subTest(method=method, path=path), self.assertRaises(FuploadError) as raised:
                session.request(method, path)
            self.assertEqual(raised.exception.kind, "validation_error")
        self.assertEqual(launcher.calls, [])

    def test_business_failure_does_not_open_login_and_redacts_details(self):
        context = FakeContext([
            response(moduleList=[]),
            FakeResponse({"status": "failed", "result": {"access_token": "private-token", "reason": "invalid field"}}),
        ])
        launcher = FakeLauncher([context])
        session = BlackboxWebSession(browser_launcher=launcher)

        with self.assertRaises(FuploadError) as raised:
            session.request("POST", "/wow/open_platform/module/update/", body={"id": 7})

        self.assertEqual(raised.exception.kind, "operation_failed")
        self.assertEqual([item[0] for item in launcher.calls], [True])
        self.assertNotIn("private-token", str(raised.exception.as_dict()))

    def test_state_and_profile_are_internal(self):
        session = BlackboxWebSession(browser_launcher=FakeLauncher([]))
        self.assertEqual(session.profile_path.name, "blackbox-chromium")
        self.assertIn("fupload", str(session.profile_path).lower())
        with self.assertRaises(TypeError):
            BlackboxWebSession(profile_path=Path("external"))
        with self.assertRaises(TypeError):
            BlackboxWebSession(cookies={"session": "external"})

    def test_recursive_redaction_and_signer_vector(self):
        sanitized = redact_recursive({
            "nested": [{
                "user_pkey": "private-pkey",
                "Credentials": {"Token": "private-token"},
                "url": "https://cos.example/file.zip?q-signature=private-signature",
            }],
        })
        self.assertEqual(sanitized["nested"][0]["user_pkey"], "<redacted>")
        self.assertEqual(sanitized["nested"][0]["Credentials"], "<redacted>")
        self.assertNotIn("private", str(sanitized))
        self.assertEqual(
            web_hkey("/wow/open_platform/module/list/", 1800000001, "0123456789ABCDEF"),
            "30SXU83",
        )


if __name__ == "__main__":
    unittest.main()
