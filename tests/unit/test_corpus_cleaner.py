"""语料清洗管线单元测试（无 DB 依赖）。"""

from __future__ import annotations

from vdtmt.corpus.cleaner import CleaningConfig, clean_pair, normalize_text, score_quality

ZWJ = "\u200b"  # 零宽连字
BEL = "\u0007"  # 告警控制符


def test_normalize_strips_html_and_entities():
    text, issues = normalize_text("<p>Hello&nbsp;World</p>", CleaningConfig())
    assert "<p>" not in text
    assert "Hello" in text and "World" in text
    assert "html_tags_stripped" in issues


def test_normalize_removes_zero_width_and_control():
    text, _ = normalize_text("a" + ZWJ + "b" + BEL + "c", CleaningConfig())
    assert ZWJ not in text
    assert BEL not in text
    assert text == "abc"


def test_clean_valid_pair():
    res = clean_pair(
        "The board approved the merger agreement.",
        "董事会批准了并购协议。",
        CleaningConfig(),
    )
    assert res.valid is True
    assert res.quality_score > 0.5
    assert res.src == "The board approved the merger agreement."
    assert res.tgt == "董事会批准了并购协议。"


def test_clean_rejects_too_short():
    res = clean_pair("", "你好", CleaningConfig())
    assert res.valid is False
    assert "too_short" in res.issues


def test_clean_rejects_identical():
    src = "The company reported earnings this quarter."
    res = clean_pair(src, src, CleaningConfig())
    assert res.valid is False
    assert "identical_src_tgt" in res.issues


def test_clean_rejects_untranslated_latin():
    # 目标与源同属拉丁语系（未翻译），字符一致性判 0
    res = clean_pair(
        "The company reported earnings this quarter.",
        "The company reported its earnings during the quarter.",
        CleaningConfig(),
    )
    assert res.valid is False
    assert "char_consistency_warning" in res.issues or "low_quality" in res.issues


def test_clean_detects_untranslated_target():
    # 目标与源一致（未翻译）-> identical_src_tgt 硬失效
    src = "The company reported earnings this quarter."
    res = clean_pair(src, src, CleaningConfig())
    assert res.valid is False
    assert "identical_src_tgt" in res.issues


def test_clean_html_in_input():
    res = clean_pair(
        "<b>Regulatory approval</b> is required.",
        "需要监管批准。",
        CleaningConfig(),
    )
    assert "<b>" not in res.src
    assert "Regulatory approval" in res.src


def test_score_quality_length_ratio():
    # 极端长度比应显著拉低分数
    low, _ = score_quality("short", "这是一个非常非常非常非常非常非常非常非常长的翻译结果明显不匹配", CleaningConfig())
    good, _ = score_quality("The bond matures next year.", "该债券明年到期。", CleaningConfig())
    assert low < good


def test_clean_handles_non_string_gracefully():
    res = clean_pair(None, "目标", CleaningConfig())  # type: ignore[arg-type]
    assert res.valid is False
    assert "non_string_input" in res.issues
