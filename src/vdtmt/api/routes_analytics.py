"""智能分析 API 路由（重映射自"智能投研"）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db.base import get_db
from ..schemas import AssociationItem, QualityReport, SimilarCase
from ..analytics.association import mine_term_associations
from ..analytics.report import build_quality_report
from ..analytics.similar_cases import find_similar_cases, find_similar_to_eval

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/associations", response_model=list[AssociationItem])
def associations(
    domain: str = Query("general"),
    min_cooccur: int = Query(2, ge=1),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[AssociationItem]:
    return mine_term_associations(db, domain=domain, min_cooccur=min_cooccur, limit=limit)


class SimilarCaseRequest(BaseModel):
    snippet: str = ""
    eval_id: int | None = None
    top_k: int = 5


@router.post("/similar-cases", response_model=list[SimilarCase])
def similar_cases(payload: SimilarCaseRequest, db: Session = Depends(get_db)) -> list[SimilarCase]:
    if payload.eval_id is not None:
        return find_similar_to_eval(db, payload.eval_id, top_k=payload.top_k)
    return find_similar_cases(db, payload.snippet, top_k=payload.top_k)


@router.get("/report", response_model=QualityReport)
def report(
    domain: str = Query("all"), db: Session = Depends(get_db)
) -> QualityReport:
    return build_quality_report(db, domain=domain)
