"""测试基础设施。

- 测试环境隔离：通过环境变量锁定 test 环境、关闭调度与 Redis、使用内存 SQLite。
- 每个测试使用独立内存库，杜绝跨测试数据污染。
- 提供 ``client``（FastAPI TestClient，含路由覆盖）与 ``session``（服务层单测会话）。
"""

from __future__ import annotations

import os

# 必须在导入应用前设置好环境变量
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_test_vdtmt.db")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("TRANSLATOR_BACKEND", "mock")
os.environ.setdefault("METRICS_ENABLED", "false")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vdtmt.db.base import get_db  # noqa: E402
from vdtmt.db.models import Base  # noqa: E402
from vdtmt.main import app  # noqa: E402


def _make_engine():
    # StaticPool：所有连接共享同一内存库，避免 in-memory SQLite 跨连接丢表
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        pool_pre_ping=True,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client():
    """每个测试独立的 TestClient + 内存 SQLite（路由级集成测试）。"""
    engine = _make_engine()
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def session():
    """服务层单测会话（独立内存库）。"""
    engine = _make_engine()
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()
