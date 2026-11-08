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
import urllib.request

from ..config import get_settings
from ..exceptions import TranslationError
from ..logging_setup import get_logger

logger = get_logger("vdtmt.translation.translators")


def _openai_chat(base_url: str, model: str, messages: list[dict], timeout: float, api_key: str = ""):
    url = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": model, "messages": messages, "temperature": 0.0, "max_tokens": 2048,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # 网络/解析失败必须显式抛出
        raise TranslationError(f"backend call failed: {exc}")


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
