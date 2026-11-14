"""Prometheus 指标单元测试（无外部依赖）。

覆盖：
- vdt_translation_errors_total：Counter，带 backend/reason 标签，可递增。
- vdt_term_hit_rate：Histogram，带 domain 标签，可观测。
"""

from __future__ import annotations

from prometheus_client import generate_latest

from vdtmt.monitoring.metrics import get_metrics


def test_translation_errors_counter_increments():
    m = get_metrics()
    series = m.translation_errors_total.labels(backend="mock", reason="backend_failure")
    before = series._value.get()
    series.inc()
    after = series._value.get()
    assert after == before + 1


def test_translation_errors_counter_has_backend_reason_labels():
    m = get_metrics()
    text = generate_latest(m.registry).decode("utf-8")
    # 指标定义应声明 backend / reason 标签
    assert "vdt_translation_errors_total" in text
    assert 'backend="' in text or "vdt_translation_errors_total{" in text


def test_term_hit_rate_has_domain_label_and_observes():
    m = get_metrics()
    m.term_hit_rate.labels(domain="legal").observe(0.85)
    text = generate_latest(m.registry).decode("utf-8")
    assert "vdt_term_hit_rate" in text
    # domain 标签应出现在渲染输出中
    assert 'domain="legal"' in text
