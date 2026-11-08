"""术语抽取单元测试（无 DB 依赖）。"""

from __future__ import annotations

from vdtmt.terminology.extractor import TermExtractor


def _pairs():
    return [
        ("The board approved the merger agreement.", "董事会批准了并购协议。"),
        ("We finalized the merger agreement yesterday.", "我们昨天敲定了并购协议。"),
        ("The merger agreement was signed.", "并购协议已签署。"),
        ("Regulatory approval is required.", "需要监管批准。"),
        ("The regulatory approval was granted.", "监管批准已获授予。"),
    ]


def test_extract_finds_consistent_term():
    ex = TermExtractor(min_freq=2, consistency=0.7)
    cands = ex.extract(_pairs(), domain="legal")
    literals = {c.literal for c in cands}
    # "merger agreement" 在 3 个句对中一致共现于「并购协议」
    assert "merger agreement" in literals
    match = next(c for c in cands if c.literal == "merger agreement")
    assert match.target == "并购协议"
    assert match.confidence >= 0.7


def test_extract_filters_stopwords_and_short():
    ex = TermExtractor(min_freq=1, consistency=0.5)
    cands = ex.extract(_pairs(), domain="legal")
    # 单停用词不应成为术语
    assert not any(c.literal in ("the", "a", "of", "is") for c in cands)


def test_score_dictionary_counts_corpus_freq():
    ex = TermExtractor()
    result = ex.score_dictionary(
        _pairs(), [("merger agreement", "并购协议"), ("regulatory approval", "监管批准")]
    )
    by_lit = {r.literal: r for r in result}
    assert by_lit["merger agreement"].freq == 3
    assert by_lit["merger agreement"].confidence == 1.0
    assert by_lit["regulatory approval"].freq == 2
