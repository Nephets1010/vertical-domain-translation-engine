"""告警通知器单元测试（无网络，用 unittest.mock 模拟外发）。

覆盖：
- LogNotifier：写入结构化日志，不应抛错。
- WebhookNotifier：目标来自环境变量；urlopen 成功/失败都应吞掉异常不抛错；
  未配置 url 时直接返回。
"""

from __future__ import annotations

import urllib.request
from unittest.mock import patch

from vdtmt.monitoring.alerting import Alert, EmailNotifier, LogNotifier, WebhookNotifier


def _make_alert() -> Alert:
    return Alert(rule="term_miss", severity="warning", message="term miss rate high",
                 context={"domain": "legal"})


def test_log_notifier_does_not_raise():
    alert = _make_alert()
    # 仅验证不抛异常
    LogNotifier().send(alert)


def test_webhook_notifier_skips_without_url():
    notifier = WebhookNotifier.__new__(WebhookNotifier)
    notifier.url = ""
    notifier.token = ""
    # 无 url 时直接返回，不调用网络
    notifier.send(_make_alert())


def test_webhook_notifier_sends_via_urlopen(monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://hook.example/alert")
    monkeypatch.setenv("ALERT_WEBHOOK_TOKEN", "secret")
    notifier = WebhookNotifier()

    captured = {}

    def _fake_urlopen(req, timeout=5):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["data"] = req.data

        class _R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _R()

    with patch.object(urllib.request, "urlopen", side_effect=_fake_urlopen):
        notifier.send(_make_alert())

    assert captured["url"] == "http://hook.example/alert"
    assert captured["headers"].get("Authorization") == "Bearer secret"
    assert b"term miss rate high" in captured["data"]


def test_webhook_notifier_swallows_urlopen_error():
    notifier = WebhookNotifier.__new__(WebhookNotifier)
    notifier.url = "http://hook.example/alert"
    notifier.token = ""

    def _boom(*args, **kwargs):
        raise OSError("network down")

    with patch.object(urllib.request, "urlopen", side_effect=_boom):
        # 不应抛出
        notifier.send(_make_alert())


def test_email_notifier_skips_without_host():
    notifier = EmailNotifier()
    # 未配置 SMTP host 时直接返回，不抛异常
    notifier.send(_make_alert())
