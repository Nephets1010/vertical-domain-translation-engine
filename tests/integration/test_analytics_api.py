"""智能分析与可视化 API 集成测试（路由级）。"""

from __future__ import annotations

import json
from pathlib import Path


def _seed(client, tmp_path):
    # 术语
    for lit, tgt in [("merger agreement", "并购协议"), ("regulatory approval", "监管批准")]:
        r = client.post("/api/v1/terms", json={
            "literal": lit, "target": tgt, "domain": "legal", "confidence": 0.98,
        })
        assert r.status_code == 201
    # 语料：含一条同时包含两个术语的句子以产生共现
    sample = tmp_path / "legal.jsonl"
    rows = [
        {"src_text": "The board approved the merger agreement.", "tgt_text": "董事会批准了并购协议。"},
        {"src_text": "The merger agreement and regulatory approval were completed.", "tgt_text": "并购协议与监管批准已完成。"},
        {"src_text": "Regulatory approval is required for the deal.", "tgt_text": "该交易需要监管批准。"},
    ]
    sample.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")
    r = client.post("/api/v1/corpus/ingest", params={"path": str(sample), "domain": "legal", "fmt": "jsonl"})
    assert r.status_code == 200
    # 评估记录（供报告/相似案例）
    client.post("/api/v1/eval/evaluate", json={
        "src": "The board approved the merger agreement.", "tgt": "董事会批准了并购协议。",
        "domain": "legal", "term_hit_rate": 1.0,
    })
    client.post("/api/v1/eval/evaluate", json={
        "src": "The merger agreement was signed.", "tgt": "并购协议已签署。",
        "domain": "legal", "term_hit_rate": 0.0,
    })


def test_associations(client, tmp_path):
    _seed(client, tmp_path)
    r = client.get("/api/v1/analytics/associations", params={"domain": "legal", "min_cooccur": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    # 两个术语在同一句中共现 -> 至少一条关联
    assert len(body) >= 1
    assert {body[0]["term_a"], body[0]["term_b"]} == {"merger agreement", "regulatory approval"}


def test_similar_cases(client, tmp_path):
    _seed(client, tmp_path)
    r = client.post("/api/v1/analytics/similar-cases", json={
        "snippet": "The board approved the merger agreement.", "top_k": 3,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    assert body[0]["similarity"] > 0.0


def test_report(client, tmp_path):
    _seed(client, tmp_path)
    r = client.get("/api/v1/analytics/report", params={"domain": "all"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sample_size"] >= 2
    assert "平均" in body["summary"]


def test_viz_term_graph(client, tmp_path):
    _seed(client, tmp_path)
    r = client.get("/api/v1/viz/term-graph", params={"domain": "legal"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["nodes"]) >= 2
    assert any(n["label"] == "merger agreement" for n in body["nodes"])


def test_viz_page(client, tmp_path):
    r = client.get("/viz")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_scheduler_jobs_run(client):
    # 调度任务直接调用不应抛异常
    from vdtmt.scheduler.jobs import detect_domain_drift, hot_reload_terms

    hot_reload_terms()
    detect_domain_drift()
