"""质量评估与风险引擎单元测试（无 DB 依赖）。"""

from __future__ import annotations

import pytest

from vdtmt.db.models import Corpus
from vdtmt.quality.evaluator import lexical_similarity
from vdtmt.quality.risk_engine import RiskEngine
from vdtmt.quality.service import QualityService


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


def test_list_records_filters_by_domain(session):
    """DEBT-003：list_records(domain=...) 应按 corpus.domain 过滤，而非子串误匹配。"""
    legal = Corpus(src_text="legal src", tgt_text="legal tgt", domain="legal")
    finance = Corpus(src_text="fin src", tgt_text="fin tgt", domain="finance")
    session.add_all([legal, finance])
    session.commit()
    session.refresh(legal)
    session.refresh(finance)

    qs = QualityService(session)
    qs.evaluate_translation("legal pair", "合法对", domain="legal", corpus_id=legal.id)
    qs.evaluate_translation("finance pair", "金融对", domain="finance", corpus_id=finance.id)

    legal_rows = qs.list_records(domain="legal")
    assert len(legal_rows) == 1
    assert legal_rows[0].corpus_id == legal.id

    finance_rows = qs.list_records(domain="finance")
    assert len(finance_rows) == 1

    # 无 domain 时返回全部
    assert len(qs.list_records()) == 2
