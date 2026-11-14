"""可插拔翻译器适配器（模块 M4）。

- ``MockTranslator``：离线默认，确定性返回输入（配合术语占位注入，术语部分由服务强制还原），
  保证本地与测试可跑、结果可复现。
- ``VLLMTranslator`` / ``APITranslator``：对接真实后端（vLLM OpenAI 兼容接口 / 通用 API）。
  受依赖守护，失败时抛 ``TranslationError``，绝不静默返回空。
切换仅改配置 ``translator_backend``，业务代码零改动。
"""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request

from ..config import get_settings
from ..exceptions import TranslationError
from ..logging_setup import get_logger

logger = get_logger("vdtmt.translation.translators")


def _openai_chat(
    base_url: str, model: str, messages: list[dict], timeout: float,
    api_key: str = "", max_retries: int = 3,
):
    """调用 OpenAI 兼容接口，对 429/5xx/超时做最多 3 次指数退避重试。

    重试仅在可恢复错误（限流、服务端错误、超时）上触发；其它错误直接抛出。
    绝不静默返回空结果——失败最终抛出 ``TranslationError``。
    """
    url = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": model, "messages": messages, "temperature": 0.0, "max_tokens": 2048,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=payload, headers=headers)

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            last_exc = exc
            # 429 限流 / 5xx 服务端错误：可重试
            if exc.code == 429 or 500 <= exc.code < 600:
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (2 ** attempt))
                    continue
                raise TranslationError(f"backend call failed after retries: {exc}")
            raise TranslationError(f"backend call failed: {exc}")
        except (socket.timeout, TimeoutError, urllib.error.URLError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(0.1 * (2 ** attempt))
                continue
            raise TranslationError(f"backend call failed: {exc}")
    raise TranslationError(f"backend call failed: {last_exc}")


class MockTranslator:
    name = "mock"

    def translate(self, text: str, source_lang: str = "en", target_lang: str = "zh") -> str:
        # 离线确定性：原样返回，术语还原由服务层完成
        return text


class VLLMTranslator:
    name = "vllm"

    def __init__(self, base_url: str, model_name: str, timeout: float = 60.0) -> None:
        self.base_url = base_url
        self.model_name = model_name
        self.timeout = timeout

    def translate(self, text: str, source_lang: str = "en", target_lang: str = "zh") -> str:
        messages = [{
            "role": "system",
            "content": (
                f"You are a professional translator from {source_lang} to {target_lang}. "
                "Translate the user text. IMPORTANT: preserve all tokens of the form "
                "@TERM<digits>@ exactly as-is; do not translate or alter them."
            ),
        }, {"role": "user", "content": text}]
        return _openai_chat(self.base_url, self.model_name, messages, self.timeout)


class APITranslator:
    name = "api"

    def __init__(self, base_url: str, model_name: str, api_key: str, timeout: float = 60.0) -> None:
        self.base_url = base_url
        self.model_name = model_name
        self.api_key = api_key
        self.timeout = timeout

    def translate(self, text: str, source_lang: str = "en", target_lang: str = "zh") -> str:
        messages = [{
            "role": "system",
            "content": (
                f"You are a professional translator from {source_lang} to {target_lang}. "
                "Translate the user text. IMPORTANT: preserve all tokens of the form "
                "@TERM<digits>@ exactly as-is; do not translate or alter them."
            ),
        }, {"role": "user", "content": text}]
        return _openai_chat(self.base_url, self.model_name, messages, self.timeout, self.api_key)


def get_translator(settings=None):
    """按配置返回翻译器实例。"""
    settings = settings or get_settings()
    backend = settings.translator_backend
    if backend == "vllm":
        return VLLMTranslator(settings.vllm_base_url, settings.vllm_model_name, settings.api_timeout_seconds)
    if backend == "api":
        if not settings.api_base_url or not settings.api_key:
            raise TranslationError(
                "api translator requires api_base_url and api_key (via env API_KEY)"
            )
        return APITranslator(
            settings.api_base_url, settings.api_model_name, settings.api_key,
            settings.api_timeout_seconds,
        )
    return MockTranslator()


class FallbackTranslator:
    """韧性包装：主翻译器抛 ``TranslationError`` 时降级到次级翻译器。

    - 成功返回译文；主后端失败时改用 secondary 并返回其译文。
    - 每次 ``translate`` 会在 ``warnings`` 中追加 ``"fallback_used:<backend>"``（仅当真发生降级）。
    - ``last_error`` 记录主后端最近一次失败（供上层计数/观测）。
    """

    name = "fallback"

    def __init__(self, primary, secondary) -> None:
        self.primary = primary
        self.secondary = secondary
        self.warnings: list[str] = []
        self.last_error: TranslationError | None = None

    def translate(self, text: str, source_lang: str = "en", target_lang: str = "zh") -> str:
        self.warnings = []
        self.last_error = None
        try:
            return self.primary.translate(text, source_lang, target_lang)
        except TranslationError as exc:
            self.last_error = exc
            self.warnings.append(f"fallback_used:{self.primary.name}")
            logger.warning(
                "primary translator %s failed; falling back to %s: %s",
                self.primary.name, self.secondary.name, exc,
            )
            return self.secondary.translate(text, source_lang, target_lang)
