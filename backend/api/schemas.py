from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


# ── Auth ──────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(min_length=6, max_length=100)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Chat ──────────────────────────────────────────────

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str = Field(min_length=1, max_length=10000)
    knowledge_base_ids: list[int] = []
    model: str | None = None
    temperature: float | None = 0.3
    max_iterations: int = 3
    use_react: bool = True


class ChatResponse(BaseModel):
    conversation_id: int
    message_id: int
    response: str
    sources: list[dict] = []
    agent_trace: list[dict] = []
    quality_score: float = 0.0
    token_usage: dict | None = None


class ConversationItem(BaseModel):
    id: int
    title: str | None
    thread_id: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageItem(BaseModel):
    id: int
    role: str
    content: str | None
    tool_calls: Any | None
    token_count: int | None
    sources: list | None = None
    agent_trace: list | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def extract_metadata(cls, data: Any) -> Any:
        if isinstance(data, dict):
            meta = data.get("extra_metadata") or {}
            if "sources" not in data or data["sources"] is None:
                data["sources"] = meta.get("sources")
            if "agent_trace" not in data or data["agent_trace"] is None:
                data["agent_trace"] = meta.get("agent_trace")
        elif hasattr(data, "extra_metadata"):
            meta = data.extra_metadata or {}
            if not hasattr(data, "sources") or getattr(data, "sources", None) is None:
                object.__setattr__(data, "sources", meta.get("sources"))
            if not hasattr(data, "agent_trace") or getattr(data, "agent_trace", None) is None:
                object.__setattr__(data, "agent_trace", meta.get("agent_trace"))
        return data


class ConversationDetail(BaseModel):
    id: int
    title: str | None
    thread_id: str
    status: str
    messages: list[MessageItem] = []
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Knowledge Base ────────────────────────────────────

class KBCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class KBCreateResponse(BaseModel):
    id: int
    name: str
    description: str | None
    doc_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class KBListItem(BaseModel):
    id: int
    name: str
    description: str | None
    doc_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentItem(BaseModel):
    id: int
    filename: str
    file_type: str
    file_size_bytes: int | None
    ingestion_status: str
    ingestion_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UploadResponse(BaseModel):
    document_id: int
    task_id: str
    filename: str
    status: str
    message: str


# ── Reports ───────────────────────────────────────────

class ReportListItem(BaseModel):
    id: int
    title: str
    content: str
    sources: object | None
    conversation_id: int | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReportCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1)
    sections: list[dict] | None = None
    sources: list[dict] | None = None
    status: Literal["draft", "completed", "archived"] = "draft"
    conversation_id: int | None = None


class ReportUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, min_length=1)
    sections: list[dict] | None = None
    sources: list[dict] | None = None
    status: Literal["draft", "completed", "archived"] | None = None


class ReportDetail(BaseModel):
    id: int
    title: str
    content: str
    sections: object | None
    sources: object | None
    status: str
    conversation_id: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Workflow ──────────────────────────────────────────

# ── SSE / WebSocket Events ─────────────────────────────

class SSEEventType:
    AGENT_STATUS = "agent_status"
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    ERROR = "error"
    DONE = "done"


class AgentStatusPayload(BaseModel):
    agent_name: str
    status: str  # "started" | "completed" | "failed"
    output: dict | None = None
    error: str | None = None


class TokenPayload(BaseModel):
    content: str


class ToolCallPayload(BaseModel):
    name: str
    action: str  # "started" | "completed" | "failed"
    input: dict | None = None
    output: dict | None = None
    error: str | None = None


class ErrorPayload(BaseModel):
    message: str
    agent: str | None = None


class DonePayload(BaseModel):
    conversation_id: int
    message_id: int
    quality_score: float = 0.0


# ── Workflow ──────────────────────────────────────────

class TaskStatus(BaseModel):
    task_id: str
    task_type: str
    status: str
    progress: dict = {}
    created_at: str
    estimated_remaining_seconds: int | None = None


class AgentExecutionItem(BaseModel):
    id: int
    agent_name: str
    status: str
    duration_ms: int | None
    token_usage: object | None
    tool_calls: object | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Common ────────────────────────────────────────────

# ── Search ─────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=50)
    strategy: str = Field(default="hybrid")  # "hybrid" | "dense" | "bm25" | "parent_child"
    use_rerank: bool = True
    use_hyde: bool = False
    use_rewrite: bool = False
    num_rewrites: int = Field(default=3, ge=1, le=5)
    filter_metadata: dict | None = None


class ChunkResult(BaseModel):
    chunk_id: str
    document_id: int
    chunk_index: int = 0
    content: str
    score: float = 0.0
    source: str = ""
    filename: str = ""


class SearchResponse(BaseModel):
    query: str
    rewrites: list[str] = []
    chunks: list[ChunkResult] = []
    total_hits: int = 0


# ── Common ────────────────────────────────────────────

class ApiResponse(BaseModel):
    code: int = 0
    data: object = None
    message: str = "success"
    detail: object = None
