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