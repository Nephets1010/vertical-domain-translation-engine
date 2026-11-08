"""质量评估与风险引擎单元测试（无 DB 依赖）。"""

from __future__ import annotations

import pytest

from vdtmt.quality.evaluator import lexical_similarity
from vdtmt.quality.risk_engine import RiskEngine


def test_lexical_similarity():
    assert lexical_similarity("并购协议", "并购协议") == 1.0
    assert lexical_similarity("abc", "xyz") == 0.0
    assert 0.0 < lexical_similarity("并购协议", "并购协议草案") < 1.0


def test_risk_engine_clean():
    eng = RiskEngine()
    hits = eng.evaluate(comet_score=None, term_hit_rate=1.0)
    assert hits == []
    assert eng.aggregate(hits) == 0.0


def test_risk_engine_term_miss():
    eng = RiskEngine()
    hits = eng.evaluate(comet_score=None, term_hit_rate=0.0)
    rules = {h.rule for h in hits}
    assert "term_miss" in rules
    assert eng.aggregate(hits) == 0.4


def test_risk_engine_low_comet_critical():
    eng = RiskEngine()
    # risk_comet_low=0.75；0.5 < 0.55 -> critical，聚合 +0.2
    hits = eng.evaluate(comet_score=0.5, term_hit_rate=1.0)
    assert any(h.rule == "low_comet" and h.severity == "critical" for h in hits)
    assert eng.aggregate(hits) == pytest.approx(0.6)


def test_risk_engine_low_confidence_info():
    eng = RiskEngine()
    hits = eng.evaluate(
        comet_score=None, term_hit_rate=1.0,
        warnings=["low_confidence_term:warrant"],
    )
    assert any(h.rule == "low_confidence_term" for h in hits)
