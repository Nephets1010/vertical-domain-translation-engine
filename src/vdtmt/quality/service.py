"""质量服务层（模块 M5）：评估编排、风险落库、告警、错误回流闭环。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Corpus, EvalRecord, QualityRisk
from ..exceptions import NotFoundError, ValidationError
from ..logging_setup import get_logger
from ..monitoring.alerting import get_alert_manager
from ..monitoring.metrics import get_metrics
from .evaluator import Evaluator
from .risk_engine import RiskEngine

logger = get_logger("vdtmt.quality.service")


class QualityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def evaluate_translation(
        self, src: str, tgt: str, domain: str = "general", ref: str | None = None,
        term_hit_rate: float = 0.0, warnings: list[str] | None = None,
        job_id: int | None = None, corpus_id: int | None = None,
    ) -> tuple[EvalRecord, list]:
        evaluator = Evaluator()
        res = evaluator.evaluate(src, tgt, ref, term_hit_rate, warnings)
        engine = RiskEngine()
        hits = engine.evaluate(res.comet_score, term_hit_rate, warnings)
        res.risk_score = engine.aggregate(hits)

        rec = EvalRecord(
            job_id=job_id, corpus_id=corpus_id, src_text=src, tgt_text=tgt,
            comet_score=res.comet_score if res.comet_score is not None else 0.0,
            term_hit_rate=term_hit_rate, error_type=res.error_type,
            risk_score=res.risk_score,
        )
        self.db.add(rec)
        self.db.commit()
        self.db.refresh(rec)

        alert_mgr = get_alert_manager()
        for h in hits:
            qr = QualityRisk(
                eval_id=rec.id, rule=h.rule, severity=h.severity, message=h.message,
            )
            self.db.add(qr)
            alert_mgr.raise_alert(
                h.rule, h.severity, h.message, {"eval_id": rec.id, "domain": domain}
            )
        self.db.commit()

        try:
            get_metrics().eval_records.inc()
            for h in hits:
                get_metrics().risk_alerts.labels(severity=h.severity).inc()
        except Exception:  # noqa: BLE001
            pass
        return rec, hits

    def feedback_bad_pair(
        self, src: str, tgt: str, domain: str, error_type: str, note: str = ""
    ) -> dict:
        """错误回流闭环：将坏样本重新入库待复审，并登记评估记录。"""
        if not src or not tgt:
            raise ValidationError("src and tgt required for feedback")
        corpus = Corpus(
            src_text=src, tgt_text=tgt, domain=domain, quality_score=0.0,
            source="feedback",
            meta={"needs_review": True, "error_type": error_type, "note": note},
        )
        self.db.add(corpus)
        self.db.commit()
        self.db.refresh(corpus)
        rec = EvalRecord(
            corpus_id=corpus.id, src_text=src, tgt_text=tgt,
            comet_score=0.0, term_hit_rate=0.0, error_type=error_type, risk_score=1.0,
        )
        self.db.add(rec)
        self.db.commit()
        logger.info("feedback bad pair recorded: corpus_id=%s error_type=%s", corpus.id, error_type)
        return {"corpus_id": corpus.id, "eval_id": rec.id}

    def list_records(self, domain: str | None = None, limit: int = 200) -> list[EvalRecord]:
        stmt = select(EvalRecord).order_by(EvalRecord.id.desc())
        rows = self.db.execute(stmt.limit(limit)).scalars().all()
        if domain:
            rows = [r for r in rows if domain in (r.src_text or "")]  # 简化；生产应按 job/domain 关联
        return rows

    def list_risks(self, resolved: bool | None = None, limit: int = 200) -> list[QualityRisk]:
        stmt = select(QualityRisk).order_by(QualityRisk.id.desc())
        if resolved is not None:
            stmt = stmt.where(QualityRisk.resolved.is_(resolved))
        return list(self.db.execute(stmt.limit(limit)).scalars().all())

    def resolve_risk(self, risk_id: int) -> bool:
        row = self.db.get(QualityRisk, risk_id)
        if row is None:
            raise NotFoundError(f"risk not found: {risk_id}")
        row.resolved = True
        self.db.commit()
        return True
