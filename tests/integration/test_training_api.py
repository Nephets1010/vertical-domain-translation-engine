"""训练 API 集成测试（路由级）。"""

from __future__ import annotations

import json
from pathlib import Path


def _ingest_legal(client, tmp_path):
    sample = tmp_path / "legal.jsonl"
    rows = [
        {"src_text": "The board approved the merger agreement.", "tgt_text": "董事会批准了并购协议。"},
        {"src_text": "Regulatory approval is required for the deal.", "tgt_text": "该交易需要监管批准。"},
        {"src_text": "The merger agreement was signed by both parties.", "tgt_text": "并购协议由双方签署。"},
    ]
    sample.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows),
                      encoding="utf-8")
    r = client.post("/api/v1/corpus/ingest", params={"path": str(sample), "domain": "legal", "fmt": "jsonl"})
    assert r.status_code == 200


def test_prepare_dataset(client, tmp_path):
    _ingest_legal(client, tmp_path)
    out = str(tmp_path / "train_legal.jsonl")
    r = client.post("/api/v1/training/prepare", params={"domain": "legal", "out_path": out})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 3
    assert Path(out).exists()
    # 数据集为合法 JSONL
    lines = Path(out).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["domain"] == "legal"


def test_dry_run_and_versions(client, tmp_path):
    _ingest_legal(client, tmp_path)
    dr = client.post("/api/v1/training/dry-run", params={"domain": "legal"})
    assert dr.status_code == 200, dr.text
    assert dr.json()["status"] == "dry_run"

    vs = client.get("/api/v1/training/versions")
    assert vs.status_code == 200
    assert any(v["name"].startswith("dry-") for v in vs.json())


def test_run_requires_gpu(client, tmp_path):
    _ingest_legal(client, tmp_path)
    # 本地无 GPU/torch，run 应返回 503 并给出明确指引（而非静默失败）
    r = client.post("/api/v1/training/run", params={"domain": "legal"})
    assert r.status_code == 503
    assert "GPU" in r.json()["error"]["message"] or "torch" in r.json()["error"]["message"]
