"""质量报告摘要（重映射自"智能投研·研报摘要"）。

聚合评估记录，产出：样本量、平均 COMET/术语命中/风险分、Top 错误类型、风险分布，以及
一段可读摘要。确定性、可复现，便于定期生成日报/周报。
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Corpus, EvalRecord
from ..logging_setup import get_logger
from ..schemas import QualityReport

logger = get_logger("vdtmt.analytics.report")


def _risk_bucket(score: float) -> str:
    if score >= 0.6:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"


def build_quality_report(db: Session, domain: str = "all", limit: int = 5000) -> QualityReport:
    stmt = select(EvalRecord).join(
        Corpus, EvalRecord.corpus_id == Corpus.id, isouter=True
    )
    if domain and domain != "all":
        stmt = stmt.where(Corpus.domain == domain)
    recs = db.execute(stmt.limit(limit)).scalars().all()

    n = len(recs)
    if n == 0:
        return QualityReport(
            domain=domain, sample_size=0, avg_comet=0.0, avg_term_hit_rate=0.0,
            avg_risk_score=0.0, top_error_types=[], risk_distribution={},
            summary="暂无评估数据。",
        )

    avg_comet = sum(r.comet_score for r in recs) / n
    avg_term = sum(r.term_hit_rate for r in recs) / n
    avg_risk = sum(r.risk_score for r in recs) / n
    err_counter = Counter(r.error_type for r in recs)
    risk_dist = Counter(_risk_bucket(r.risk_score) for r in recs)

    top_errors = [
        {"error_type": k, "count": v} for k, v in err_counter.most_common(5)
    ]
    summary = (
        f"共评估 {n} 条；平均质量分 {avg_comet:.2f}，平均术语命中率 {avg_term:.2f}，"
        f"平均风险分 {avg_risk:.2f}。主要错误类型为 "
        f"{'、'.join(f'{e['error_type']}({e['count']})' for e in top_errors[:3]) or '无'}；"
        f"高风险占比 {risk_dist.get('high', 0) / n:.0%}。"
    )
    return QualityReport(
        domain=domain, sample_size=n, avg_comet=round(avg_comet, 3),
        avg_term_hit_rate=round(avg_term, 3), avg_risk_score=round(avg_risk, 3),
        top_error_types=top_errors,
        risk_distribution=dict(risk_dist),
        summary=summary,
    )
