from datetime import datetime

from pydantic import BaseModel
from sqlmodel import SQLModel, Field


class Build(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    version: str
    path: str
    size: int
    short_id: str = Field(unique=True, index=True)  # Short identifier for download URLs
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})
    created_by: int | None = Field(default=None, foreign_key="user.id")
    team_id: int | None = Field(default=None, foreign_key="team.id")

class BuildCreate(BaseModel):
    name: str
    version: str
    team_id: int

class BuildResponse(BaseModel):
    id: int
    name: str
    version: str
    path: str
    size: int
    short_id: str
    created_at: datetime
    updated_at: datetime
    created_by: int
    team_id: int
    upload_url: str | None = None
    short_download_url: str | None = None

class BuildUpdate(BaseModel):
    name: str | None = None
    version: str | None = None
    size: int | None = None