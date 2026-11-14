"""术语 API 路由（模块 M2）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db.base import get_db
from ..exceptions import NotFoundError, ValidationError
from ..schemas import (
    MessageResponse,
    TermCreate,
    TermRead,
    TermRelationCreate,
    TermSearchResult,
)
from ..terminology.service import TermService

router = APIRouter(prefix="/api/v1/terms", tags=["terminology"])


@router.post("", response_model=TermRead, status_code=201)
def create_term(payload: TermCreate, db: Session = Depends(get_db)) -> TermRead:
    svc = TermService(db)
    row = svc.add_term(
        payload.literal, payload.target, payload.domain,
        payload.confidence, payload.source, payload.enabled,
    )
    return TermRead.model_validate(row)


@router.post("/bulk", response_model=dict)
def bulk_terms(
    terms: list[TermCreate], source: str = Query("manual"),
    db: Session = Depends(get_db),
) -> dict:
    svc = TermService(db)
    n = svc.bulk_add([t.model_dump() for t in terms], source=source)
    return {"imported": n}


@router.get("", response_model=list[TermRead])
def list_terms(
    domain: str | None = Query(None),
    enabled: bool | None = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[TermRead]:
    svc = TermService(db)
    return [TermRead.model_validate(t) for t in svc.list(domain, enabled, limit, offset)]


@router.get("/search", response_model=list[TermSearchResult])
def search_terms(
    q: str = Query(..., min_length=1),
    domain: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[TermSearchResult]:
    svc = TermService(db)
    rows = svc.search(q, domain, limit)
    return [
        TermSearchResult(
            literal=r.literal, target=r.target, domain=r.domain,
            confidence=r.confidence, freq=r.freq,
        )
        for r in rows
    ]


@router.get("/{term_id}", response_model=TermRead)
def get_term(term_id: int, db: Session = Depends(get_db)) -> TermRead:
    svc = TermService(db)
    row = svc.get(term_id)
    if row is None:
        raise NotFoundError(f"term not found: {term_id}")
    return TermRead.model_validate(row)


@router.patch("/{term_id}", response_model=TermRead)
def update_term(
    term_id: int, payload: dict, db: Session = Depends(get_db)
) -> TermRead:
    svc = TermService(db)
    allowed = {"literal", "target", "domain", "confidence", "enabled", "source"}
    fields = {k: v for k, v in payload.items() if k in allowed}
    if not fields:
        raise ValidationError("no updatable fields provided")
    row = svc.update(term_id, **fields)
    return TermRead.model_validate(row)


@router.delete("/{term_id}", response_model=MessageResponse)
def delete_term(term_id: int, db: Session = Depends(get_db)) -> MessageResponse:
    svc = TermService(db)
    if not svc.delete(term_id):
        raise NotFoundError(f"term not found: {term_id}")
    return MessageResponse(message="deleted")


@router.post("/relations", response_model=dict, status_code=201)
def create_relation(
    payload: TermRelationCreate, db: Session = Depends(get_db)
) -> dict:
    svc = TermService(db)
    rel = svc.add_relation(
        payload.source_literal, payload.target_literal, payload.relation_type,
        payload.weight, payload.domain, payload.evidence,
    )
    return svc.relation_to_dict(rel)


@router.get("/{term_id}/relations", response_model=list[dict])
def list_relations(term_id: int, db: Session = Depends(get_db)) -> list[dict]:
    svc = TermService(db)
    return [svc.relation_to_dict(r) for r in svc.relations_of(term_id)]


@router.post("/extract", response_model=dict)
def extract_terms(
    domain: str = Query("general"),
    min_conf: float = Query(0.7, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> dict:
    svc = TermService(db)
    stored = svc.extract_and_store(domain=domain, min_conf=min_conf)
    return {"domain": domain, "extracted": len(stored),
            "literals": [t.literal for t in stored[:50]]}


@router.post("/suggest-network", response_model=dict)
def suggest_network(
    domain: str = Query("general"), db: Session = Depends(get_db)
) -> dict:
    svc = TermService(db)
    rels = svc.suggest_network(domain=domain)
    return {"domain": domain, "relations": len(rels)}


@router.post("/conflicts", response_model=list[dict])
def find_term_conflicts(
    domain: str | None = Query(None), db: Session = Depends(get_db)
) -> list[dict]:
    """全局术语冲突扫描（可选按 domain 过滤）。

    返回冲突列表，每项形如
    ``{literal, domain, candidates:[{target, source, confidence, count}]}``。
    """
    svc = TermService(db)
    return svc.find_conflicts(domain=domain)


@router.get("/{term_id}/conflicts", response_model=list[dict])
def term_conflicts(
    term_id: int, db: Session = Depends(get_db)
) -> list[dict]:
    """查询单个术语所属 literal+domain 的冲突（若存在）。"""
    svc = TermService(db)
    term = svc.get(term_id)
    if term is None:
        raise NotFoundError(f"term not found: {term_id}")
    conflicts = svc.find_conflicts(domain=term.domain)
    return [c for c in conflicts if c["literal"].lower() == term.literal.lower()]
