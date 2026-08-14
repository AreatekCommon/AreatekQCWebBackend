from pydantic import BaseModel, Field


class LogsResponse(BaseModel):
    lines: list[str] = Field(default_factory=list)


class LogSourceInfo(BaseModel):
    id: str
    path: str
    exists: bool
    size_bytes: int = 0
    modified_at: float | None = None


class LogSourcesResponse(BaseModel):
    sources: list[LogSourceInfo] = Field(default_factory=list)
