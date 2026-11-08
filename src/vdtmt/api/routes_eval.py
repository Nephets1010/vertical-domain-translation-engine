"""质量评估与风险 API 路由（模块 M5）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db.base import get_db
from ..exceptions import NotFoundError
from ..schemas import EvalRecordRead, MessageResponse, QualityRiskRead
from ..quality.service import QualityService

router = APIRouter(prefix="/api/v1/eval", tags=["quality"])


class EvaluateRequest(BaseModel):
    src: str
    tgt: str
    domain: str = "general"
    ref: str | None = None
    term_hit_rate: float = 0.0
    warnings: list[str] = []
    job_id: int | None = None
    corpus_id: int | None = None


class FeedbackRequest(BaseModel):
    src: str
    tgt: str
    domain: str = "general"
    error_type: str = "manual_flag"
    note: str = ""


@router.post("/evaluate", response_model=dict)
def evaluate(payload: EvaluateRequest, db: Session = Depends(get_db)) -> dict:
    svc = QualityService(db)
    rec, hits = svc.evaluate_translation(
        payload.src, payload.tgt, payload.domain, payload.ref,
        payload.term_hit_rate, payload.warnings, payload.job_id, payload.corpus_id,
    )
    return {
        "eval_id": rec.id,
        "comet_score": rec.comet_score,
        "term_hit_rate": rec.term_hit_rate,
        "error_type": rec.error_type,
        "risk_score": rec.risk_score,
        "hits": [
            {"rule": h.rule, "severity": h.severity, "message": h.message}
            for h in hits
        ],
    }


@router.post("/feedback", response_model=dict, status_code=201)
def feedback(payload: FeedbackRequest, db: Session = Depends(get_db)) -> dict:
    svc = QualityService(db)
    return svc.feedback_bad_pair(payload.src, payload.tgt, payload.domain, payload.error_type, payload.note)


@router.get("/records", response_model=list[EvalRecordRead])
def list_records(
    domain: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[EvalRecordRead]:
    svc = QualityService(db)
    return [EvalRecordRead.model_validate(r) for r in svc.list_records(domain, limit)]


@router.get("/risks", response_model=list[QualityRiskRead])
def list_risks(
    resolved: bool | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[QualityRiskRead]:
    svc = QualityService(db)
    return [QualityRiskRead.model_validate(r) for r in svc.list_risks(resolved, limit)]


@router.post("/risks/{risk_id}/resolve", response_model=MessageResponse)
def resolve_risk(risk_id: int, db: Session = Depends(get_db)) -> MessageResponse:
    svc = QualityService(db)
    if not svc.resolve_risk(risk_id):
        raise NotFoundError(f"risk not found: {risk_id}")
    return MessageResponse(message="resolved")
