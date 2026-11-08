"""训练 API 路由（模块 M3）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db.base import get_db
from ..exceptions import NotFoundError
from ..schemas import MessageResponse
from ..training.pipeline import TrainingConfig, TrainingPipeline

router = APIRouter(prefix="/api/v1/training", tags=["training"])


class TrainingConfigPayload(BaseModel):
    base_model: str = "Qwen2.5-7B"
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    learning_rate: float = 2e-4
    num_epochs: int = 3
    per_device_batch_size: int = 4
    max_seq_length: int = 1024
    output_dir: str = "./models/lora"
    deepspeed_config: str | None = None
    use_term_hints: bool = True


@router.post("/prepare", response_model=dict)
def prepare_dataset(
    domain: str = Query("general"),
    out_path: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    pipe = TrainingPipeline(db)
    return pipe.prepare(domain=domain, out_path=out_path)


@router.post("/run", response_model=dict)
def run_training(
    domain: str = Query("general"),
    payload: TrainingConfigPayload | None = None,
    db: Session = Depends(get_db),
) -> dict:
    cfg = TrainingConfig(**payload.model_dump()) if payload else TrainingConfig()
    pipe = TrainingPipeline(db, cfg)
    res = pipe.run(domain=domain)
    return {
        "model_version_id": res.model_version_id, "name": res.name,
        "adapter_path": res.adapter_path, "status": res.status,
        "metrics": res.metrics,
    }


@router.post("/dry-run", response_model=dict)
def dry_run_training(
    domain: str = Query("general"), db: Session = Depends(get_db)
) -> dict:
    pipe = TrainingPipeline(db)
    res = pipe.dry_run(domain=domain)
    return {
        "model_version_id": res.model_version_id, "name": res.name,
        "status": res.status,
    }


@router.get("/versions", response_model=list[dict])
def list_versions(db: Session = Depends(get_db)) -> list[dict]:
    pipe = TrainingPipeline(db)
    return [
        {
            "id": v.id, "name": v.name, "base_model": v.base_model,
            "adapter_path": v.adapter_path, "metrics": v.metrics,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in pipe.list_versions()
    ]


@router.get("/versions/{version_id}", response_model=dict)
def get_version(version_id: int, db: Session = Depends(get_db)) -> dict:
    pipe = TrainingPipeline(db)
    v = next((x for x in pipe.list_versions() if x.id == version_id), None)
    if v is None:
        raise NotFoundError(f"model version not found: {version_id}")
    return {
        "id": v.id, "name": v.name, "base_model": v.base_model,
        "adapter_path": v.adapter_path, "metrics": v.metrics,
    }


@router.delete("/versions/{version_id}", response_model=MessageResponse)
def delete_version(version_id: int, db: Session = Depends(get_db)) -> MessageResponse:
    from sqlalchemy import select

    from ..db.models import ModelVersion

    row = db.execute(select(ModelVersion).where(ModelVersion.id == version_id)).scalars().first()
    if row is None:
        raise NotFoundError(f"model version not found: {version_id}")
    db.delete(row)
    db.commit()
    return MessageResponse(message="deleted")
