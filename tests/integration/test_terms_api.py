"""术语 API 集成测试（路由级）。"""

from __future__ import annotations

import json
from pathlib import Path


def test_term_crud_and_search(client):
    r = client.post("/api/v1/terms", json={
        "literal": "merger agreement", "target": "并购协议",
        "domain": "legal", "confidence": 0.98,
    })
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    # 幂等 upsert：重复 literal+domain 不应新建
    r2 = client.post("/api/v1/terms", json={
        "literal": "merger agreement", "target": "并购协议（更新）",
        "domain": "legal",
    })
    assert r2.status_code == 201
    assert r2.json()["id"] == tid  # 同一条

    s = client.get("/api/v1/terms/search", params={"q": "merger", "domain": "legal"})
    assert s.status_code == 200
    assert any(t["literal"] == "merger agreement" for t in s.json())

    g = client.get(f"/api/v1/terms/{tid}")
    assert g.status_code == 200

    d = client.delete(f"/api/v1/terms/{tid}")
    assert d.status_code == 200
    assert client.get(f"/api/v1/terms/{tid}").status_code == 404


def test_term_relation_and_search(client):
    a = client.post("/api/v1/terms", json={"literal": "warrant", "target": "认股权证", "domain": "finance"})
    b = client.post("/api/v1/terms", json={"literal": "bonds", "target": "债券", "domain": "finance"})
    aid, bid = a.json()["id"], b.json()["id"]
    rel = client.post("/api/v1/terms/relations", json={
        "source_literal": "warrant", "target_literal": "bonds",
        "relation_type": "cooccurrence", "domain": "finance", "weight": 0.8,
    })
    assert rel.status_code == 201, rel.text
    rels = client.get(f"/api/v1/terms/{aid}/relations")
    assert rels.status_code == 200
    assert len(rels.json()) == 1
    assert rels.json()[0]["relation_type"] == "cooccurrence"


def test_extract_and_suggest(client, tmp_path):
    # 构造含重复术语对的语料并接入
    sample = tmp_path / "legal.jsonl"
    base = [
        {"src_text": "The board approved the merger agreement.", "tgt_text": "董事会批准了并购协议。"},
        {"src_text": "We finalized the merger agreement yesterday.", "tgt_text": "我们昨天敲定了并购协议。"},
        {"src_text": "The merger agreement was signed by both parties.", "tgt_text": "并购协议由双方签署。"},
    ]
    sample.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in base * 3),
                      encoding="utf-8")
    ing = client.post("/api/v1/corpus/ingest", params={"path": str(sample), "domain": "legal", "fmt": "jsonl"})
    assert ing.status_code == 200

    ext = client.post("/api/v1/terms/extract", params={"domain": "legal", "min_conf": 0.7})
    assert ext.status_code == 200, ext.text
    body = ext.json()
    assert body["extracted"] >= 1
    assert "merger agreement" in body["literals"]

    sug = client.post("/api/v1/terms/suggest-network", params={"domain": "legal"})
    assert sug.status_code == 200
    assert sug.json()["relations"] >= 0


def test_terms_conflicts_endpoint():
    """需求 1：冲突端点应返回非空数组且字段齐全（共享同一内存库构造冲突）。"""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from vdtmt.db.base import get_db
    from vdtmt.db.models import Base, Term
    from vdtmt.main import app

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool, pool_pre_ping=True,
    )
    Base.metadata.create_all(engine)
    SL = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SL()
    # 大小写不同的同字面 + 不同译文 -> 两条物理记录 -> 构成冲突
    db.add_all([
        Term(literal="Cloud", target="云", domain="tech", confidence=1.0,
             source="manual", enabled=True),
        Term(literal="cloud", target="云端", domain="tech", confidence=1.0,
             source="manual", enabled=True),
    ])
    db.commit()
    db.close()

    saved = dict(app.dependency_overrides)

    def _override():
        s = SL()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as c:
            r = c.post("/api/v1/terms/conflicts", params={"domain": "tech"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert isinstance(body, list) and len(body) >= 1
            c0 = body[0]
            assert c0["literal"] == "cloud"
            assert c0["domain"] == "tech"
            assert len(c0["candidates"]) == 2
            for cand in c0["candidates"]:
                assert {"target", "source", "confidence", "count"} <= set(cand.keys())

            terms = c.get("/api/v1/terms", params={"domain": "tech"}).json()
            tid = terms[0]["id"]
            r2 = c.get(f"/api/v1/terms/{tid}/conflicts")
            assert r2.status_code == 200
            assert isinstance(r2.json(), list) and len(r2.json()) >= 1
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
        engine.dispose()
