from typing import Any, Optional


class AppException(Exception):
    """Base exception with error code for unified response."""

    def __init__(self, code: int, message: str, detail: Any = None):
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)


# ── 1xxx: Client errors ─────────────────────────────

class ValidationError(AppException):
    def __init__(self, detail: Any = None):
        super().__init__(code=1001, message="请求参数校验失败", detail=detail)


class UnauthorizedError(AppException):
    def __init__(self):
        super().__init__(code=1002, message="未认证")


class ForbiddenError(AppException):
    def __init__(self):
        super().__init__(code=1003, message="无权限访问该资源")


class NotFoundError(AppException):
    def __init__(self, resource: str = "资源"):
        super().__init__(code=1004, message=f"{resource}不存在")


class RateLimitError(AppException):
    def __init__(self):
        super().__init__(code=1005, message="请求频率超限")


# ── 2xxx: Server errors ─────────────────────────────

class InternalError(AppException):
    def __init__(self, detail: Optional[str] = None):
        super().__init__(code=2001, message="服务器内部错误", detail=detail)


class LLMError(AppException):
    def __init__(self, detail: Optional[str] = None):
        super().__init__(code=2002, message="LLM 调用失败", detail=detail)


class ExternalServiceError(AppException):
    def __init__(self, service: str = "外部服务"):
        super().__init__(code=2003, message=f"{service}不可用")


# ── 3xxx: Domain errors ─────────────────────────────

class KnowledgeBaseNotFound(AppException):
    def __init__(self):
        super().__init__(code=3001, message="知识库不存在")


class DocumentParseError(AppException):
    def __init__(self, detail: Optional[str] = None):
        super().__init__(code=3002, message="文档解析失败", detail=detail)


class AgentExecutionError(AppException):
    def __init__(self, detail: Optional[str] = None):
        super().__init__(code=3003, message="Agent 执行失败", detail=detail)


class MaxIterationsExceeded(AppException):
    def __init__(self):
        super().__init__(code=3004, message="已达到最大迭代次数")
