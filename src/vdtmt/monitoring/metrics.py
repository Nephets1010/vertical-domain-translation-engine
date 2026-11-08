"""可观测性：Prometheus 指标（企业级：请求量、延迟、术语命中、风险告警）。"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    CollectorRegistry,
    generate_latest,
)
from prometheus_client.multiprocess import MultiProcessCollector

try:  # 多进程模式（gunicorn/uvicorn workers）可选
    import prometheus_client  # noqa: F401

    _MULTI = False
except Exception:  # pragma: no cover
    _MULTI = False


class Metrics:
    """集中管理指标收集器。单例。"""

    _instance = None

    def __new__(cls) -> "Metrics":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self.registry = CollectorRegistry()
        self.translation_requests = Counter(
            "vdt_translation_requests_total",
            "翻译请求总数",
            ["domain", "backend", "status"],
            registry=self.registry,
        )
        self.translation_latency = Histogram(
            "vdt_translation_latency_seconds",
            "翻译延迟（秒）",
            ["domain"],
            registry=self.registry,
        )
        self.term_hit_rate = Histogram(
            "vdt_term_hit_rate",
            "术语命中率分布",
            registry=self.registry,
        )
        self.risk_alerts = Counter(
            "vdt_risk_alerts_total",
            "质量风险告警总数",
            ["severity"],
            registry=self.registry,
        )
        self.corpus_size = Gauge(
            "vdt_corpus_size",
            "语料条数",
            registry=self.registry,
        )
        self.term_size = Gauge(
            "vdt_term_size",
            "术语条数",
            registry=self.registry,
        )
        self.eval_records = Counter(
            "vdt_eval_records_total",
            "评估记录总数",
            registry=self.registry,
        )

    def render(self) -> tuple[bytes, str]:
        if _MULTI and False:  # 预留多进程采集
            reg = CollectorRegistry()
            MultiProcessCollector(reg)
        else:
            reg = self.registry
        return generate_latest(reg), CONTENT_TYPE_LATEST


def get_metrics() -> Metrics:
    return Metrics()
