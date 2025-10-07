from typing import List

from pydantic import BaseModel
from sqlmodel import SQLModel, Field

class Team(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str | None = None
    organization_id: int | None = Field(default=None, foreign_key="organization.id")
    max_builds: int = Field(default=5)

class TeamMember(SQLModel, table=True):
    team_id: int | None = Field(default=None, primary_key=True, foreign_key="team.id")
    user_id: int | None = Field(default=None, primary_key=True, foreign_key="user.id")
    is_owner: bool = Field(default=False)

class BatchUserIdentifiersRequest(BaseModel):
    identifiers: List[str]  # Can be usernames or emails
    is_owner: bool = False  # Whether to add users as owners

class AddUserToTeamRequest(BaseModel):
    is_owner: bool = False  # Whether to add user as owner

class TeamCreateRequest(BaseModel):
    name: str
    description: str | None = None
    organization_id: int | None = None
    max_builds: int = 5

class BatchTeamRequest(BaseModel):
    teams: List[TeamCreateRequest]

class BatchOperationResult(BaseModel):
    successful: List[str]
    failed: List[dict]
    total_processed: int
    successful_count: int
    failed_count: int