"""健康、就绪与指标接口。"""

from __future__ import annotations

from fastapi import APIRouter, Response

from .. import __version__
from ..config import get_settings
from ..monitoring.metrics import get_metrics

router = APIRouter(tags=["system"])


@router.get("/health", summary="健康检查")
def health() -> dict:
    """存活探针。"""
    settings = get_settings()
    return {"status": "ok", "version": __version__, "env": settings.environment}


@router.get("/ready", summary="就绪检查")
def ready() -> dict:
    """就绪探针：检查数据库可连接。"""
    try:
        from ..db.base import get_engine

        with get_engine().connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail=f"db not ready: {exc}")


@router.get("/metrics", summary="Prometheus 指标")
def metrics() -> Response:
    data, ctype = get_metrics().render()
    return Response(content=data, media_type=ctype)
