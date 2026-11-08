"""结构化日志（企业级：JSON 输出、上下文注入、等级可配）。

本地开发可关闭 JSON 以方便阅读；生产环境默认 JSON 便于采集。
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from .config import get_settings


class JsonFormatter(logging.Formatter):
    """将日志记录渲染为单行 JSON，便于 ELK / Loki 采集。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # 允许通过 extra={"context": {...}} 注入业务上下文
        ctx = getattr(record, "context", None)
        if ctx:
            payload["context"] = ctx
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    """按配置初始化根日志。幂等。"""
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # 第三方库降噪
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("elasticsearch").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取带模块名的 logger。"""
    return logging.getLogger(name)
