# All models imported here for Alembic auto-detection
from backend.models.user import User
from backend.models.conversation import Conversation
from backend.models.message import Message
from backend.models.knowledge_base import KnowledgeBase
from backend.models.document import Document
from backend.models.document_chunk import DocumentChunk
from backend.models.research_report import ResearchReport
from backend.models.agent_execution import AgentExecution

__all__ = [
    "User", "Conversation", "Message", "KnowledgeBase",
    "Document", "DocumentChunk", "ResearchReport", "AgentExecution",
]
