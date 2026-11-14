"""术语约束注入（模块 M4）。

方法：将源文中命中的术语字面替换为唯一占位符 ``@TERM<n>@``，交由翻译器翻译
（真实后端被要求保留占位符），翻译后再将占位符还原为权威译文。
这样即使基座模型可能误译术语，也能保证术语 100% 准确（强制约束）。
确定性、可复现。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# 纯 ASCII 字母/数字字面走 \b 单词边界，避免 "cat" 误命中 "category"
_ALNUM_RE = re.compile(r"^[A-Za-z0-9]+$")


def literal_present(src: str, literal: str) -> bool:
    """判断字面是否出现在源文中（带词边界意识）。

    - 纯 ASCII 字母/数字字面：用 ``\\b`` 单词边界判定。
    - 含非单词字符（如 "U.S."、"C++"）的字面：退化为原始 ``in`` 子串判定，
      保证这类术语仍能命中。
    """
    if _ALNUM_RE.match(literal):
        return re.search(rf"\b{re.escape(literal)}\b", src, flags=re.I) is not None
    return literal in src


def _literal_pattern(literal: str) -> str:
    """生成替换用的正则：纯字母数字用词边界，否则退化为转义子串。"""
    if _ALNUM_RE.match(literal):
        return rf"\b{re.escape(literal)}\b"
    return re.escape(literal)


@dataclass
class InjectionResult:
    injected: str
    placeholders: dict[str, str]  # @TERM<n>@ -> 目标译文


def inject_terms(src: str, terms: list[tuple[str, str]]) -> InjectionResult:
    """将术语字面替换为占位符。terms: [(literal, target)]。"""
    placeholders: dict[str, str] = {}
    out = src
    # 长字面优先，避免短词先替换导致部分重叠
    for idx, (literal, target) in enumerate(
        sorted(terms, key=lambda x: -len(x[0]))
    ):
        ph = f"@TERM{idx}@"
        out = re.sub(_literal_pattern(literal), ph, out, flags=re.I)
        placeholders[ph] = target
    return InjectionResult(out, placeholders)


def restore_terms(text: str, placeholders: dict[str, str]) -> str:
    """占位符还原为译文。"""
    for ph, target in placeholders.items():
        text = text.replace(ph, target)
    return text


def count_preserved(text: str, placeholders: dict[str, str]) -> int:
    """统计译文（还原前）中仍保留的占位符数量，用于评估后端合规度。"""
    return sum(1 for ph in placeholders if ph in text)
