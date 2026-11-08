"""术语注入单元测试（无 DB 依赖）。"""

from __future__ import annotations

from vdtmt.translation.injection import (
    count_preserved,
    inject_terms,
    restore_terms,
)


def test_inject_and_restore_roundtrip():
    src = "The merger agreement was signed by both parties."
    terms = [("merger agreement", "并购协议"), ("signed", "签署")]
    inj = inject_terms(src, terms)
    assert "@TERM0@" in inj.injected and "@TERM1@" in inj.injected
    assert "merger agreement" not in inj.injected
    restored = restore_terms(inj.injected, inj.placeholders)
    assert restored == "The 并购协议 was 签署 by both parties."


def test_inject_handles_overlap_by_length():
    # 长字面优先，避免 "agreement" 先替换破坏 "merger agreement"
    src = "We signed the merger agreement."
    terms = [("agreement", "协议"), ("merger agreement", "并购协议")]
    inj = inject_terms(src, terms)
    restored = restore_terms(inj.injected, inj.placeholders)
    assert restored == "We signed the 并购协议."


def test_count_preserved():
    terms = [("merger agreement", "并购协议")]
    inj = inject_terms("The merger agreement.", terms)
    assert count_preserved(inj.injected, inj.placeholders) == 1
    # 模拟后端丢失占位符
    assert count_preserved("The agreement.", inj.placeholders) == 0
