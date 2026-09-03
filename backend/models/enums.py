from enum import Enum


class AgentRunStatus(str, Enum):
    PENDING = "PENDING"
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    WAITING_HUMAN = "WAITING_HUMAN"
    RESUME_QUEUED = "RESUME_QUEUED"
    RESUMED = "RESUMED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    CANCELLED = "CANCELLED"


class AgentRunStepStatus(str, Enum):
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    SKIPPED = "SKIPPED"
    INTERRUPTED = "INTERRUPTED"


class HumanReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class HumanReviewAction(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class ToolCallStatus(str, Enum):
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RETRY = "RETRY"
