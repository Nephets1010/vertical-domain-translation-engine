"""API 路由聚合。各阶段在此注册路由。"""

from __future__ import annotations

from fastapi import APIRouter

from .routes_corpus import router as corpus_router
from .routes_health import router as health_router
from .routes_terms import router as terms_router
from .routes_training import router as training_router
from .routes_translate import router as translate_router
from .routes_eval import router as eval_router
from .routes_analytics import router as analytics_router
from .routes_viz import router as viz_router

# 所有启用的路由
routers: list[APIRouter] = [
    health_router, corpus_router, terms_router, training_router,
    translate_router, eval_router, analytics_router, viz_router,
]


def register_routers(app) -> None:  # noqa: ANN001
    for r in routers:
        app.include_router(r)
