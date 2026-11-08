"""语料 API 路由（模块 M1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..corpus.service import CorpusService, IngestReport
from ..db.base import get_db
from ..exceptions import NotFoundError, ValidationError
from ..schemas import CorpusCreate, CorpusRead, MessageResponse

router = APIRouter(prefix="/api/v1/corpus", tags=["corpus"])


@router.post("/ingest", response_model=dict)
def ingest_corpus(
    path: str,
    domain: str | None = Query(None, description="覆盖文件内 domain"),
    source: str | None = Query(None),
    fmt: str = Query("auto", description="jsonl|tsv|csv|tmx|auto"),
    accept_low_quality: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict:
    """接入语料文件并返回汇总报告。"""
    svc = CorpusService(db)
    try:
        rep: IngestReport = svc.ingest_file(
            path, domain=domain, source=source, fmt=fmt,
            accept_low_quality=accept_low_quality,
        )
    except (FileNotFoundError, NotFoundError):
        raise NotFoundError(f"corpus file not found: {path}")
    return {
        "source_name": rep.source_name,
        "total": rep.total,
        "accepted": rep.accepted,
        "rejected": rep.rejected,
        "low_quality": rep.low_quality,
        "first_id": rep.first_id,
        "provenance_id": rep.provenance_id,
    }


@router.post("", response_model=CorpusRead, status_code=201)
def create_corpus(payload: CorpusCreate, db: Session = Depends(get_db)) -> CorpusRead:
    svc = CorpusService(db)
    row = svc.add_pair(
        payload.src_text, payload.tgt_text, payload.domain, payload.source
    )
    return CorpusRead.model_validate(row)


@router.get("", response_model=list[CorpusRead])
def list_corpus(
    domain: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[CorpusRead]:
    svc = CorpusService(db)
    return [CorpusRead.model_validate(r) for r in svc.list(domain, limit, offset)]


@router.get("/count", response_model=dict)
def count_corpus(domain: str | None = Query(None), db: Session = Depends(get_db)) -> dict:
    svc = CorpusService(db)
    return {"domain": domain, "count": svc.count(domain)}


@router.get("/{corpus_id}", response_model=CorpusRead)
def get_corpus(corpus_id: int, db: Session = Depends(get_db)) -> CorpusRead:
    svc = CorpusService(db)
    row = svc.get(corpus_id)
    if row is None:
        raise NotFoundError(f"corpus not found: {corpus_id}")
    return CorpusRead.model_validate(row)


@router.delete("/{corpus_id}", response_model=MessageResponse)
def delete_corpus(corpus_id: int, db: Session = Depends(get_db)) -> MessageResponse:
    svc = CorpusService(db)
    if not svc.delete(corpus_id):
        raise NotFoundError(f"corpus not found: {corpus_id}")
    return MessageResponse(message="deleted")
