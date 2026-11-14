"""翻译器适配器单元测试（无网络/GPU，全部用 unittest.mock）。

覆盖：
- FallbackTranslator：主后端失败时降级到次级并返回 fallback_used 告警。
- _openai_chat：对 429/5xx/超时做指数退避重试，重试耗尽后抛 TranslationError。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from vdtmt.exceptions import TranslationError
from vdtmt.translation.translators import (
    FallbackTranslator,
    MockTranslator,
    _openai_chat,
)


class _FailingTranslator(MockTranslator):
    """测试用：主后端，translate 必抛 TranslationError。"""

    name = "failing"

    def translate(self, text: str, source_lang: str = "en", target_lang: str = "zh") -> str:
        raise TranslationError("primary backend unavailable")


def test_fallback_uses_secondary_on_primary_failure():
    primary = _FailingTranslator()
    secondary = MockTranslator()
    fb = FallbackTranslator(primary, secondary)

    out = fb.translate("hello world")
    # 返回次级译文（Mock 原样返回）
    assert out == "hello world"
    # 告警标明降级及主后端名
    assert fb.warnings == ["fallback_used:failing"]
    assert fb.last_error is not None
    assert isinstance(fb.last_error, TranslationError)


def test_fallback_no_warning_when_primary_ok():
    primary = MockTranslator()
    fb = FallbackTranslator(primary, _FailingTranslator())

    out = fb.translate("hello")
    assert out == "hello"
    assert fb.warnings == []
    assert fb.last_error is None


def test_openai_chat_retries_then_succeeds():
    class _FakeResp:
        def __init__(self, payload: str) -> None:
            self._payload = payload.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):  # noqa: ANN002
            return False

        def read(self):
            return self._payload

    payload = json.dumps({"choices": [{"message": {"content": "译"}}]})

    calls = {"n": 0}

    def _side_effect(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError("http://x", 429, "rate limited", {}, None)
        return _FakeResp(payload)

    with patch.object(urllib.request, "urlopen", side_effect=_side_effect):
        result = _openai_chat("http://x/v1", "m", [{"role": "user", "content": "hi"}], timeout=1)
    assert result == "译"
    assert calls["n"] == 3  # 前两次限流，第三次成功


def test_openai_chat_raises_after_max_retries():
    with patch.object(
        urllib.request, "urlopen",
        side_effect=urllib.error.HTTPError("http://x", 503, "down", {}, None),
    ):
        with pytest.raises(TranslationError):
            _openai_chat("http://x/v1", "m", [{"role": "user", "content": "hi"}], timeout=1)


def test_openai_chat_retries_on_timeout():
    class _FakeResp:
        def __init__(self, payload: str) -> None:
            self._payload = payload.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):  # noqa: ANN002
            return False

        def read(self):
            return self._payload

    calls = {"n": 0}

    def _side_effect(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("timed out")
        return _FakeResp(json.dumps({"choices": [{"message": {"content": "ok"}}]}))

    with patch.object(urllib.request, "urlopen", side_effect=_side_effect):
        result = _openai_chat("http://x/v1", "m", [{"role": "user", "content": "hi"}], timeout=1)
    assert result == "ok"
    assert calls["n"] == 2
