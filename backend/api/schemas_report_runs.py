from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CreateReportRunRequest(BaseModel):
    query: str = Field(min_length=1)
    title: str | None = None
    conversation_id: int | None = None
    document_ids: list[int | str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    client_request_id: str | None = None


class ReportRunResponse(BaseModel):
    run_id: int
    thread_id: str
    status: str
    current_node: str | None
    query: str
    created_at: datetime
    status_version: int
    celery_task_id: str | None = None


class ReportRunDetailResponse(BaseModel):
    run_id: int
    thread_id: str
    status: str
    current_node: str | None
    query: str
    iteration_count: int
    max_iterations: int
    human_review_round: int
    max_human_reviews: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    status_version: int


class ReportRunStatusResponse(BaseModel):
    run_id: int
    status: str
    current_node: str | None
    progress: int | None = None
    review_required: bool = False
    review_id: int | None = None
    task_id: str | None = None
    status_version: int
    updated_at: datetime
    source: Literal["redis", "postgresql"] = "postgresql"


class ReportRunStepResponse(BaseModel):
    step_id: int
    sequence: int
    node_name: str
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: int | None
    input_summary: Any | None
    output_summary: Any | None
    error_code: str | None
    error_message: str | None


class PendingReviewResponse(BaseModel):
    run_id: int
    pending: bool
    review: dict[str, Any] | None


class ResumeReportRunRequest(BaseModel):
    review_id: int
    action: Literal["approve", "edit", "reject"]
    feedback: str | None = None
    edited_report: dict[str, Any] | str | None = None
    idempotency_key: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_action_payload(self) -> "ResumeReportRunRequest":
        if self.action == "edit" and self.edited_report is None:
            raise ValueError("edited_report is required for edit")
        if self.action == "reject" and not self.feedback:
            raise ValueError("feedback is required for reject")
        return self


class ResumeReportRunResponse(BaseModel):
    run_id: int
    thread_id: str
    status: str
    review_id: int
    celery_task_id: str | None = None
    message: str
