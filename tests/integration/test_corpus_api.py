"""语料 API 集成测试（路由级）。"""

from __future__ import annotations

import json
from pathlib import Path


def test_create_and_get_corpus(client):
    payload = {
        "src_text": "The board approved the merger agreement.",
        "tgt_text": "董事会批准了并购协议。",
        "domain": "legal",
        "source": "manual",
    }
    r = client.post("/api/v1/corpus", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["domain"] == "legal"
    assert body["quality_score"] > 0.5

    rid = body["id"]
    r2 = client.get(f"/api/v1/corpus/{rid}")
    assert r2.status_code == 200
    assert r2.json()["id"] == rid


def test_create_rejects_dirty_pair(client):
    # 明显漏译（目标无 CJK），质量过低应被拒
    payload = {
        "src_text": "The company reported earnings.",
        "tgt_text": "The company reported earnings.",
    }
    r = client.post("/api/v1/corpus", json=payload)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == 40000


def test_list_and_count(client):
    for i in range(3):
        client.post("/api/v1/corpus", json={
            "src_text": f"The bond matures in {i} years.",
            "tgt_text": f"该债券在 {i} 年后到期。",
            "domain": "finance",
        })
    r = client.get("/api/v1/corpus?domain=finance&limit=10")
    assert r.status_code == 200
    assert len(r.json()) == 3

    c = client.get("/api/v1/corpus/count?domain=finance")
    assert c.status_code == 200
    assert c.json()["count"] == 3


def test_ingest_jsonl_file(client, tmp_path):
    sample = tmp_path / "sample.jsonl"
    rows = [
        {"src_text": "Force majeure excuses performance.", "tgt_text": "不可抗力免除履行。", "domain": "legal"},
        {"src_text": "The underwriter allocated shares.", "tgt_text": "承销商分配了股份。", "domain": "finance"},
        {"src_text": "The issuer may call the bonds.", "tgt_text": "The issuer may call the bonds."},
    ]
    sample.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")

    r = client.post("/api/v1/corpus/ingest", params={"path": str(sample), "fmt": "jsonl"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert body["accepted"] == 2
    assert body["rejected"] == 1
    assert body["provenance_id"] is not None


def test_delete_corpus(client):
    r = client.post("/api/v1/corpus", json={
        "src_text": "Dividends are payable quarterly.",
        "tgt_text": "股息按季度支付。",
    })
    rid = r.json()["id"]
    d = client.delete(f"/api/v1/corpus/{rid}")
    assert d.status_code == 200
    g = client.get(f"/api/v1/corpus/{rid}")
    assert g.status_code == 404
