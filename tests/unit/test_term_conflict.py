"""术语冲突检测单元测试（使用 conftest 的 session 内存库）。

注意：术语表对 (literal, domain) 有大小写敏感的唯一约束，且 add_term 是大小写
不敏感幂等合并，因此"同一字面不同译文"的冲突只能通过大小写变体（如 "Cloud" 与
"cloud"）产生两条物理记录。测试据此直接插入两条记录构造冲突。

覆盖：
- 同字面(大小写不同)+domain 不同 target -> find_conflicts 返回该 literal 且候选数=2。
- 同字面(大小写不同)+domain 相同 target 但 source 不一致 -> 视为冲突。
- 不相同字面的重复 / 无冲突场景 -> 不误报。
- 仅按 domain 过滤生效。
- DEBT-008：use_elasticsearch=True 时 search 应 fail-loud（抛出 50100）。
"""

from __future__ import annotations

import pytest

from vdtmt.db.models import Term
from vdtmt.exceptions import ErrorCode, VdtmtError
from vdtmt.terminology.service import TermService


def _add(db, literal, target, domain, source="manual"):
    db.add(Term(
        literal=literal, target=target, domain=domain,
        confidence=1.0, source=source, enabled=True,
    ))
    db.commit()


def test_find_conflicts_different_targets(session):
    _add(session, "Cloud", "云", "tech")
    _add(session, "cloud", "云端", "tech")

    conflicts = TermService(session).find_conflicts(domain="tech")
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["literal"] == "cloud"
    assert c["domain"] == "tech"
    assert len(c["candidates"]) == 2
    targets = {x["target"] for x in c["candidates"]}
    assert targets == {"云", "云端"}
    for cand in c["candidates"]:
        assert {"target", "source", "confidence", "count"} <= set(cand.keys())


def test_find_conflicts_source_inconsistency(session):
    # 同字面(大小写变体)同译文但来源不同 -> source 不一致也算冲突
    _add(session, "Model", "模型", "ai", source="manual")
    _add(session, "model", "模型", "ai", source="extracted")

    conflicts = TermService(session).find_conflicts(domain="ai")
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["literal"] == "model"
    assert len(c["candidates"]) == 2


def test_find_conflicts_no_false_positive(session):
    # 不同字面不互相影响；单条不冲突
    _add(session, "kernel", "内核", "os")
    _add(session, "module", "模块", "os")

    assert TermService(session).find_conflicts(domain="os") == []


def test_find_conflicts_domain_filter(session):
    _add(session, "Bank", "银行", "finance")
    _add(session, "bank", "河岸", "finance")
    _add(session, "bank", "银行", "geography")  # 另一 domain，无冲突

    finance = TermService(session).find_conflicts(domain="finance")
    assert len(finance) == 1
    assert finance[0]["literal"] == "bank"

    geo = TermService(session).find_conflicts(domain="geography")
    assert geo == []


def test_search_fail_loud_when_elasticsearch_enabled(session, monkeypatch):
    """DEBT-008：开启 use_elasticsearch 时不再静默走 DB，而是明确报错 50100。"""
    monkeypatch.setattr(
        TermService, "_settings",
        staticmethod(lambda: type("S", (), {"use_elasticsearch": True})()),
    )
    svc = TermService(session)
    with pytest.raises(VdtmtError) as exc_info:
        svc.search("anything")
    assert exc_info.value.code == ErrorCode.ELASTICSEARCH_NOT_IMPLEMENTED
    assert exc_info.value.http_status == 501
