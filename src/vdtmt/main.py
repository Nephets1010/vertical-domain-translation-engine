"""VDT-MT 应用入口（uvicorn vdtmt.main:app）。

装配：配置/日志、API 路由、全局异常处理、调度启停、指标。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 将 src 加入路径，支持 `python -m vdtmt.main`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from .api import register_routers  # noqa: E402
from .config import get_settings  # noqa: E402
from .db.base import dispose_engine, init_db  # noqa: E402
from .exceptions import VdtmtError, map_exception  # noqa: E402
from .logging_setup import configure_logging, get_logger  # noqa: E402
from .scheduler import get_scheduler  # noqa: E402

configure_logging()
logger = get_logger("vdtmt.main")

settings = get_settings()

app = FastAPI(
    title="VDT-MT 垂直领域专业术语机器翻译引擎",
    description=(
        "企业级垂直领域专业术语机器翻译引擎：语料接入与清洗、术语抽取与术语库网络、"
        "领域微调管线、术语约束翻译、质量风险规则引擎与评分、翻译智能分析、"
        "可视化检索、任务调度与监控告警。"
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(VdtmtError)
async def vdtmt_exception_handler(request: Request, exc: VdtmtError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    mapped = map_exception(exc)
    logger.error("unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=mapped.http_status, content=mapped.to_dict())


@app.on_event("startup")
def on_startup() -> None:
    # 开发/测试用 create_all；生产由 docker 启动命令 `alembic upgrade head` 负责
    if settings.environment in ("dev", "test"):
        try:
            init_db()
        except Exception as exc:  # noqa: BLE001
            logger.warning("init_db skipped: %s", exc)
    try:
        from .scheduler.jobs import refresh_metrics_gauges

        refresh_metrics_gauges()
    except Exception:  # noqa: BLE001
        pass
    get_scheduler().start()
    logger.info("VDT-MT started (env=%s, backend=%s)", settings.environment, settings.translator_backend)


@app.on_event("shutdown")
def on_shutdown() -> None:
    get_scheduler().shutdown()
    dispose_engine()
    logger.info("VDT-MT stopped")


register_routers(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("vdtmt.main:app", host="0.0.0.0", port=8000, reload=False)
