"""质量评估 API 集成测试（路由级）。"""

from __future__ import annotations


def test_evaluate_clean(client):
    r = client.post("/api/v1/eval/evaluate", json={
        "src": "The board approved the plan.",
        "tgt": "董事会批准了该计划。", "domain": "legal",
        "term_hit_rate": 1.0,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["risk_score"] == 0.0
    assert body["error_type"] == "none"
    assert body["hits"] == []


def test_evaluate_term_miss_raises_risk(client):
    r = client.post("/api/v1/eval/evaluate", json={
        "src": "The merger agreement was signed.",
        "tgt": "并购协议已签署。", "domain": "legal",
        "term_hit_rate": 0.0,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["risk_score"] > 0.0
    assert any(h["rule"] == "term_miss" for h in body["hits"])

    risks = client.get("/api/v1/eval/risks")
    assert risks.status_code == 200
    assert any(h["rule"] == "term_miss" for h in risks.json())


def test_risk_resolve(client):
    ev = client.post("/api/v1/eval/evaluate", json={
        "src": "x", "tgt": "y", "domain": "legal", "term_hit_rate": 0.0,
    })
    risks = client.get("/api/v1/eval/risks", params={"resolved": False})
    rid = risks.json()[0]["id"]
    res = client.post(f"/api/v1/eval/risks/{rid}/resolve")
    assert res.status_code == 200
    after = client.get("/api/v1/eval/risks", params={"resolved": True})
    assert any(r["id"] == rid and r["resolved"] for r in after.json())


def test_feedback_bad_pair_and_records(client):
    fb = client.post("/api/v1/eval/feedback", json={
        "src": "The warrant expired.", "tgt": "认股权证过期了。",
        "domain": "finance", "error_type": "term_miss",
    })
    assert fb.status_code == 201, fb.text
    assert fb.json()["corpus_id"] > 0

    recs = client.get("/api/v1/eval/records")
    assert recs.status_code == 200
    assert any(r["error_type"] == "term_miss" for r in recs.json())
