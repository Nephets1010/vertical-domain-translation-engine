"""翻译 API 路由（模块 M4）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db.base import get_db
from ..schemas import (
    BatchTranslateRequest,
    BatchTranslateResponse,
    TranslateRequest,
    TranslateResponse,
)
from ..translation.service import TranslationService

router = APIRouter(prefix="/api/v1/translate", tags=["translation"])


class DocumentRequest(BaseModel):
    text: str
    domain: str = "general"
    source_lang: str = "en"
    target_lang: str = "zh"
    use_term_injection: bool = True


@router.post("", response_model=TranslateResponse)
def translate(payload: TranslateRequest, db: Session = Depends(get_db)) -> TranslateResponse:
    svc = TranslationService(db)
    return svc.translate(payload)


@router.post("/batch", response_model=BatchTranslateResponse, status_code=201)
def batch_translate(
    payload: BatchTranslateRequest, db: Session = Depends(get_db)
) -> BatchTranslateResponse:
    svc = TranslationService(db)
    return svc.batch_translate(payload)


@router.post("/document", response_model=dict)
def translate_document(
    payload: DocumentRequest, db: Session = Depends(get_db)
) -> dict:
    svc = TranslationService(db)
    return svc.translate_document(
        payload.text, payload.domain, payload.source_lang, payload.target_lang,
        payload.use_term_injection,
    )


@router.get("/jobs/{job_id}", response_model=dict)
def get_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import select

    from ..db.models import TranslationJob
    from ..exceptions import NotFoundError

    job = db.execute(select(TranslationJob).where(TranslationJob.id == job_id)).scalars().first()
    if job is None:
        raise NotFoundError(f"translation job not found: {job_id}")
    return {
        "id": job.id, "title": job.title, "domain": job.domain,
        "status": job.status, "total": job.total, "processed": job.processed,
        "result_path": job.result_path,
    }
