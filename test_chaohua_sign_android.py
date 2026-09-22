import io
import unittest
from contextlib import redirect_stdout
from urllib.parse import quote
from unittest.mock import patch

import chaohua_sign_android as script


RAW = (
    "https://api.weibo.cn/2/statuses/container_timeline_topicsub"
    "?aid=TEST_AID_VALUE&c=android&from=test_build&gsid=TEST_GSID_VALUE&s=TEST_S_VALUE"
)


class FakeResponse:
    def __init__(self, data=None, status_code=200, json_error=None):
        self.data = data
        self.status_code = status_code
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


def topic(title, key, done=False, action=None):
    button = {
        "type": "sign_in",
        "name": "已签到" if done else "签到",
        "params": {"action": action or ""},
    }
    return {
        "title_sub": title,
        "scheme": "sinaweibo://pageinfo?containerid=" + key,
        "buttons": [button],
    }


def sign_action():
    target = "https://i.chaohua.weibo.com/mobile/shproxy/active_fcheckin?topic=TEST_TOPIC"
    return "/2/page/button?request_url=" + quote(target, safe="")


class ScriptTests(unittest.TestCase):
    def run_main(self, responses, raw=RAW, notifier=None, pause=None):
        session = FakeSession(responses)
        calls = []
        sender = notifier if notifier is not None else lambda title, body: calls.append((title, body))
        output = io.StringIO()
        with redirect_stdout(output):
            code = script.main(
                raw=raw,
                session_factory=lambda: session,
                pause=pause or (lambda seconds: None),
                notifier=sender,
            )
        return code, calls, output.getvalue(), session

    def test_success_sends_one_notification_with_results_and_summary(self):
        pauses = []
        responses = [
            FakeResponse({"items": [
                topic("已完成超话", "done", done=True),
                topic("待签到超话", "pending", action=sign_action()),
            ]}),
            FakeResponse({"result": 1, "msg": "已签到"}),
        ]
        code, calls, output, session = self.run_main(
            responses, pause=lambda seconds: pauses.append(seconds))

        self.assertEqual(0, code)
        self.assertEqual(1, len(calls))
        self.assertEqual("微博超话签到", calls[0][0])
        self.assertIn("[已签] 已完成超话", calls[0][1])
        self.assertIn("[成功] 待签到超话", calls[0][1])
        self.assertIn("汇总：成功 1，已签 1，失败 0，跳过 0", calls[0][1])
        self.assertIn("状态：执行完成。", calls[0][1])
        self.assertIn("[汇总]", output)
        self.assertEqual(1, len(pauses))
        self.assertEqual(["POST", "GET"], [request[0] for request in session.requests])

    def test_missing_and_invalid_environment_notify_once(self):
        for raw, expected in (("", "status_taobudiao"), ("not-a-url", "完整 HTTPS 请求链接")):
            with self.subTest(raw=raw):
                code, calls, output, session = self.run_main([], raw=raw)
                self.assertEqual(1, code)
                self.assertEqual(1, len(calls))
                self.assertIn(expected, calls[0][1])
                self.assertIn("汇总：成功 0，已签 0，失败 0，跳过 0", calls[0][1])
                self.assertIn("[错误]", output)
                self.assertEqual([], session.requests)

    def test_http_json_and_pagination_failures_notify_once(self):
        cases = [
            ([FakeResponse(status_code=503)], "HTTP 状态：503"),
            ([FakeResponse(json_error=ValueError("secret response"))], "接口未返回 JSON"),
            ([
                FakeResponse({
                    "items": [topic("分页超话", "same", done=True)],
                    "moreInfo": {"params": {"page": 2}},
                }),
                FakeResponse({"items": [topic("分页超话", "same", done=True)]}),
            ], "分页返回重复内容"),
        ]
        for responses, expected in cases:
            with self.subTest(expected=expected):
                code, calls, output, unused = self.run_main(responses)
                self.assertEqual(1, code)
                self.assertEqual(1, len(calls))
                self.assertIn(expected, calls[0][1])
                self.assertIn("状态：错误：", calls[0][1])
                self.assertIn("[错误]", output)

    def test_unexpected_failure_sends_sanitized_notification(self):
        calls = []

        def fail_factory():
            raise RuntimeError("unexpected " + RAW)

        output = io.StringIO()
        with redirect_stdout(output):
            code = script.main(
                raw=RAW,
                session_factory=fail_factory,
                notifier=lambda title, body: calls.append((title, body)),
            )

        self.assertEqual(1, code)
        self.assertEqual(1, len(calls))
        self.assertIn("未预期", calls[0][1])
        self.assertIn("RuntimeError", calls[0][1])
        self.assertNotIn(RAW, calls[0][1])
        self.assertNotIn("TEST_GSID_VALUE", calls[0][1])
        self.assertNotIn("Traceback", output)

    def test_notifier_unavailable_does_not_change_success_status(self):
        response = FakeResponse({"items": [topic("已签超话", "done", done=True)]})
        output = io.StringIO()
        with patch.object(script, "load_notifier", return_value=None), redirect_stdout(output):
            code = script.main(
                raw=RAW,
                session_factory=lambda: FakeSession([response]),
                pause=lambda seconds: None,
            )

        self.assertEqual(0, code)
        self.assertIn("[通知警告]", output.getvalue())
        self.assertNotIn(RAW, output.getvalue())

    def test_notifier_send_failure_does_not_change_success_status(self):
        def broken_sender(title, body):
            raise RuntimeError("notification secret " + RAW)

        response = FakeResponse({"items": [topic("已签超话", "done", done=True)]})
        code, calls, output, unused = self.run_main([response], notifier=broken_sender)

        self.assertEqual(0, code)
        self.assertEqual([], calls)
        self.assertIn("[通知警告] 通知发送失败", output)
        self.assertNotIn(RAW, output)

    def test_notification_and_console_do_not_leak_secrets(self):
        title = (
            "敏感测试 " + RAW
            + " aid=TEST_AID_VALUE gsid=TEST_GSID_VALUE s=TEST_S_VALUE token=TEST_TOKEN_VALUE"
        )
        response = FakeResponse({"items": [topic(title, "secret-topic", done=True)]})
        code, calls, output, unused = self.run_main([response])

        self.assertEqual(0, code)
        self.assertEqual(1, len(calls))
        combined = calls[0][1] + output
        for secret in (RAW, "TEST_AID_VALUE", "TEST_GSID_VALUE", "TEST_S_VALUE", "TEST_TOKEN_VALUE"):
            self.assertNotIn(secret, combined)
        self.assertNotIn("?aid=", combined)
        self.assertNotIn("api.weibo.cn/2/statuses", combined)
        self.assertIn("[已隐藏", combined)


if __name__ == "__main__":
    unittest.main()
