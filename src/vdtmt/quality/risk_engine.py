"""翻译质量风险规则引擎（模块 M5，重映射自"风险预警规则引擎与评分模型"）。

规则（可配置阈值，见 config）：
- low_comet：COMET/近似分低于阈值 -> warning/critical。
- term_miss：术语未命中率高于阈值 -> warning。
- low_confidence_term：翻译阶段标记的低置信度术语 -> info。
- domain_drift：译文与领域预期不符的弱信号（占位，可由后续 ML 扩展）。

加权聚合为 0~1 风险分；命中即写入 ``QualityRisk`` 并触发告警（AlertManager）。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import get_settings
from ..logging_setup import get_logger

logger = get_logger("vdtmt.quality.risk_engine")


@dataclass
class RuleHit:
    rule: str
    severity: str  # info | warning | critical
    message: str
    weight: float


class RiskEngine:
    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()

    def evaluate(
        self,
        comet_score: float | None,
        term_hit_rate: float,
        warnings: list[str] | None = None,
        domain_drift: bool = False,
    ) -> list[RuleHit]:
        hits: list[RuleHit] = []
        warnings = warnings or []

        if comet_score is not None:
            low = self.settings.risk_comet_low
            if comet_score < low:
                sev = "critical" if comet_score < low - 0.2 else "warning"
                hits.append(RuleHit(
                    "low_comet", sev,
                    f"quality score {comet_score:.3f} < {low}", 0.40,
                ))

        miss_rate = 1.0 - term_hit_rate
        if miss_rate > self.settings.risk_term_miss_rate_high:
            hits.append(RuleHit(
                "term_miss", "warning",
                f"term miss rate {miss_rate:.3f} > {self.settings.risk_term_miss_rate_high}",
                0.40,
            ))

        for w in warnings:
            if w.startswith("low_confidence_term"):
                hits.append(RuleHit("low_confidence_term", "info", w, 0.10))

        if domain_drift:
            hits.append(RuleHit("domain_drift", "info", "possible domain drift", 0.10))

        return hits

    @staticmethod
    def aggregate(hits: list[RuleHit]) -> float:
        """加权聚合（critical 额外加成），上限 1.0。"""
        score = sum(h.weight for h in hits)
        if any(h.severity == "critical" for h in hits):
            score += 0.2
        return min(1.0, score)
