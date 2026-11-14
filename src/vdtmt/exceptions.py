"""统一异常体系（企业级：可分类、可映射 HTTP 状态、可观测）。

所有业务异常继承自 VdtmtError；API 层据此返回结构化错误。
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class ErrorCode(IntEnum):
    """错误码分类。"""

    INTERNAL = 50000
    VALIDATION = 40000
    NOT_FOUND = 40400
    CONFLICT = 40900
    UNAVAILABLE = 50300
    RATE_LIMIT = 42900
    TRANSLATION_FAILED = 50200
    EVALUATION_FAILED = 50210
    RESOURCE_EXHAUSTED = 50700
    ELASTICSEARCH_NOT_IMPLEMENTED = 50100


class VdtmtError(Exception):
    """基类。携带 code / 可读消息 / 可附加上下文。"""

    code: ErrorCode = ErrorCode.INTERNAL
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode | None = None,
        http_status: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.context = context or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": int(self.code),
                "message": self.message,
                "context": self.context,
            }
        }


class ValidationError(VdtmtError):
    code = ErrorCode.VALIDATION
    http_status = 400


class NotFoundError(VdtmtError):
    code = ErrorCode.NOT_FOUND
    http_status = 404


class ConflictError(VdtmtError):
    code = ErrorCode.CONFLICT
    http_status = 409


class UnavailableError(VdtmtError):
    code = ErrorCode.UNAVAILABLE
    http_status = 503


class TranslationError(VdtmtError):
    code = ErrorCode.TRANSLATION_FAILED
    http_status = 502


class EvaluationError(VdtmtError):
    code = ErrorCode.EVALUATION_FAILED
    http_status = 502


def map_exception(exc: Exception) -> VdtmtError:
    """将任意异常归一化为 VdtmtError，避免泄露内部信息。"""
    if isinstance(exc, VdtmtError):
        return exc
    # 意外异常：记录原始信息由日志层负责，对外仅暴露通用消息
    return VdtmtError(
        "内部服务错误，请查看日志或联系管理员。",
        code=ErrorCode.INTERNAL,
        context={"type": type(exc).__name__},
    )
