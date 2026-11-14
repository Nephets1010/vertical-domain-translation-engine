"""翻译 API 集成测试（路由级）。"""

from __future__ import annotations

import os

from vdtmt.exceptions import TranslationError
from vdtmt.translation.translators import MockTranslator


class _FailingTranslator(MockTranslator):
    """测试用主后端：translate 必抛 TranslationError，用于验证降级。"""

    name = "failing"

    def translate(self, text: str, source_lang: str = "en", target_lang: str = "zh") -> str:
        raise TranslationError("primary backend unavailable")


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
    jb = job.json()
    assert jb["processed"] == 2
    # DEBT-018：完成时写入 finished_at；DEBT-019：result_path 为绝对路径（CWD 无关）
    assert jb["finished_at"] is not None
    assert os.path.isabs(jb["result_path"])


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


def test_translate_fallback_on_primary_failure(client, monkeypatch):
    """需求 6：主后端故障时经 FallbackTranslator 降级，返回 200 且 warnings 含 fallback_used。"""
    monkeypatch.setattr(
        "vdtmt.translation.service.get_translator",
        lambda *a, **k: _FailingTranslator(),
    )
    r = client.post("/api/v1/translate", json={
        "text": "Hello world.", "domain": "general", "use_term_injection": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["translated"] == "Hello world."
    assert any(w.startswith("fallback_used:") for w in body["warnings"])


def test_metrics_expose_domain_label_and_error_counter(client, monkeypatch):
    """可观测性：/metrics 含 domain 标签的命中率，以及错误计数。"""
    client.post("/api/v1/translate", json={
        "text": "hi", "domain": "metricsdom", "use_term_injection": False,
    })
    # 触发主后端失败，使错误计数 +1
    monkeypatch.setattr(
        "vdtmt.translation.service.get_translator",
        lambda *a, **k: _FailingTranslator(),
    )
    client.post("/api/v1/translate", json={
        "text": "hi", "domain": "metricsdom", "use_term_injection": False,
    })
    r = client.get("/metrics")
    assert r.status_code == 200
    text = r.text
    assert "vdt_term_hit_rate" in text
    assert 'domain="metricsdom"' in text
    assert "vdt_translation_errors_total" in text
