"""翻译 API 集成测试（路由级）。"""

from __future__ import annotations


def _add_terms(client):
    for lit, tgt in [("merger agreement", "并购协议"), ("regulatory approval", "监管批准")]:
        r = client.post("/api/v1/terms", json={
            "literal": lit, "target": tgt, "domain": "legal", "confidence": 0.98,
        })
        assert r.status_code == 201


def test_translate_with_injection(client):
    _add_terms(client)
    r = client.post("/api/v1/translate", json={
        "text": "The board approved the merger agreement subject to regulatory approval.",
        "domain": "legal", "use_term_injection": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "并购协议" in body["translated"]
    assert "监管批准" in body["translated"]
    assert body["term_hit_rate"] == 1.0
    assert body["backend"] == "mock"
    assert len(body["term_hits"]) == 2


def test_translate_without_injection(client):
    _add_terms(client)
    r = client.post("/api/v1/translate", json={
        "text": "The board approved the merger agreement.",
        "domain": "legal", "use_term_injection": False,
    })
    assert r.status_code == 200
    body = r.json()
    # mock 后端原样返回，未注入则不替换术语
    assert body["translated"] == "The board approved the merger agreement."
    assert body["term_hit_rate"] == 0.0


def test_batch_translate(client):
    _add_terms(client)
    r = client.post("/api/v1/translate/batch", json={
        "texts": [
            "We finalized the merger agreement.",
            "Regulatory approval is required.",
        ],
        "domain": "legal", "job_title": "batch-legal",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total"] == 2
    assert body["status"] == "completed"

    job = client.get(f"/api/v1/translate/jobs/{body['job_id']}")
    assert job.status_code == 200
    assert job.json()["processed"] == 2


def test_translate_document(client):
    _add_terms(client)
    text = ("The board approved the merger agreement. "
            "Regulatory approval is required for the deal.")
    r = client.post("/api/v1/translate/document", json={
        "text": text, "domain": "legal",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "并购协议" in body["translated"]
    assert "监管批准" in body["translated"]
    assert body["segments"] == 2
