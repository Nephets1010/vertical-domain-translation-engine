"""术语注入单元测试（无 DB 依赖）。"""

from __future__ import annotations

from vdtmt.translation.injection import (
    count_preserved,
    inject_terms,
    literal_present,
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


# ---- DEBT-014：词边界，避免 "cat" 误命中 "category" ----

def test_literal_present_word_boundary_excludes_substring():
    # 纯字母字面应走 \b 边界，不匹配更长单词内部的子串
    assert literal_present("category", "cat") is False
    assert literal_present("The cat sat.", "cat") is True
    assert literal_present("a cat's hat", "cat") is True


def test_literal_present_falls_back_for_special_chars():
    # 含非单词字符（如 "U.S."、"C++"）退化为子串判定，仍应命中
    assert literal_present("The U.S. economy", "U.S.") is True
    assert literal_present("C++ is fast", "C++") is True
    assert literal_present("US economy", "U.S.") is False


def test_inject_respects_word_boundary():
    # 不应把占位符插入到更长单词内部："cat" 不命中 "category"
    inj = inject_terms("The category is new.", [("cat", "猫")])
    assert inj.injected == "The category is new."  # 未注入
    # 无占位符被实际替换，还原后保持原文
    assert restore_terms(inj.injected, inj.placeholders) == "The category is new."

    inj2 = inject_terms("The cat sat.", [("cat", "猫")])
    assert "@TERM0@" in inj2.injected
    assert restore_terms(inj2.injected, inj2.placeholders) == "The 猫 sat."


def test_inject_special_char_literal_still_matches():
    # 含特殊字符的字面仍按子串注入
    inj = inject_terms("Refer to U.S. law.", [("U.S.", "美国")])
    assert "@TERM0@" in inj.injected
    assert restore_terms(inj.injected, inj.placeholders) == "Refer to 美国 law."
