from datetime import datetime

from pydantic import BaseModel, Field


class IngestResponse(BaseModel):
    filename: str
    chunks: int


class UploadResponse(BaseModel):
    filename: str
    status: str
    kind: str  # "image" or "document"
    stored_name: str
    display_name: str
    mime: str
    size: int


class AttachmentRef(BaseModel):
    stored_name: str
    display_name: str
    kind: str
    mime: str
    size: int


class SourceRef(BaseModel):
    filename: str
    score: float | None = None


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)
    # Stored names from POST /upload, and nothing else: the server re-derives
    # display name, kind, MIME and size from the file on disk.
    attachments: list[str] = Field(default_factory=list, max_length=5)


class StreamChatRequest(ChatRequest):
    """Body of POST /chat/stream. truncate_after_id drops every row after it in
    this session before the turn runs -- the mechanism behind regenerate/edit."""

    truncate_after_id: int | None = None


class ChatResponse(BaseModel):
    answer: str
    tool_used: str | None = None
    sources: list[SourceRef] = []


class HistoryItem(BaseModel):
    id: int
    role: str
    message: str
    attachments: list[AttachmentRef] = []
    created_at: datetime


class SessionSummary(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class SessionPatch(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class UserResponse(BaseModel):
    username: str
    role: str
    created_at: datetime


class AdminStats(BaseModel):
    users: int
    active_users: int
    documents: int
    chunks: int
    sessions: int
    messages: int
    storage_bytes: int


class KnowledgeItem(BaseModel):
    """One ingested file. A document IS its filename: save_upload prefixes every
    stored name with a uuid, so the name is a safe grouping key (SP2 Decision 1)."""

    filename: str
    display_name: str
    chunks: int
    chars: int
    owner: str | None = None
    created_at: datetime


class ChunkItem(BaseModel):
    chunk_index: int
    chars: int
    content: str  # truncated for display; the full text is not the console's job
