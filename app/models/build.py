from datetime import datetime

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