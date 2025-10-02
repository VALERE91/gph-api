from sqlmodel import SQLModel, Field

class Organization(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str | None = None

class OrganizationMemberLink(SQLModel, table=True):
    organization_id: int = Field(foreign_key="organization.id", primary_key=True)
    user_id: int = Field(foreign_key="user.id", primary_key=True)