"""数据库引擎与会话（企业级：连接池、读写分离占位、依赖注入）。

- 开发/测试：SQLite（默认）
- 生产：PostgreSQL（docker-compose 注入）
两者共用同一套 SQLAlchemy 模型与 Alembic 迁移。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


_engine = None
_SessionLocal = None


def _configure_sqlite_pragmas(engine: "Engine", url: str) -> None:
    """为文件型（非内存）SQLite 注册连接级 PRAGMA，提升并发写稳定性。

    - journal_mode=WAL：允许读写并发，减少写锁冲突。
    - busy_timeout=5000：写冲突时等待而非立即报错。
    注意：WAL 对内存库（URL 含 `:memory:`）无效，需跳过，否则会抛异常。
    """
    if url.startswith("sqlite") and ":memory:" not in url:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, conn_record) -> None:  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA busy_timeout=5000;")
            finally:
                cursor.close()


def get_engine() -> "Engine":
    """懒加载并缓存引擎（含连接池配置）。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        connect_args = {}
        # SQLite 需要 check_same_thread=False 以支持多线程 FastAPI
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        engine_kwargs: dict = {"echo": settings.database_echo}
        # 仅 PostgreSQL 走 QueuePool 参数；SQLite 不应传这些（否则可能报错）
        if url.startswith("postgresql"):
            engine_kwargs.update(
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
            )
        _engine = create_engine(url, connect_args=connect_args, **engine_kwargs)
        _configure_sqlite_pragmas(_engine, url)
    return _engine


def get_session_local() -> sessionmaker:
    """绑定引擎的会话工厂。"""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autocommit=False, autoflush=False
        )
    return _SessionLocal


def init_db() -> None:
    """创建全部表（开发/测试用；生产请使用 Alembic 迁移）。"""
    from .models import Base

    Base.metadata.create_all(bind=get_engine())


def dispose_engine() -> None:
    """释放引擎（测试/退出时调用）。"""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：请求级会话，自动关闭。"""
    factory = get_session_local()
    db = factory()
    try:
        yield db
    finally:
        db.close()
