from datetime import datetime

from pydantic import BaseModel, Field


class IngestResponse(BaseModel):
    filename: str
    chunks: int


class UploadResponse(BaseModel):
    filename: str
    status: str
    kind: str  # "image" or "document"


class SourceRef(BaseModel):
    filename: str
    score: float | None = None


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)
    image_path: str | None = None


class ChatResponse(BaseModel):
    answer: str
    tool_used: str | None = None
    sources: list[SourceRef] = []


class HistoryItem(BaseModel):
    role: str
    message: str
    created_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
