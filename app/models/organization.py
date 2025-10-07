from typing import List

from pydantic import BaseModel
from sqlmodel import SQLModel, Field

class Organization(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str | None = None

class OrganizationMemberLink(SQLModel, table=True):
    organization_id: int = Field(foreign_key="organization.id", primary_key=True)
    user_id: int = Field(foreign_key="user.id", primary_key=True)

class BatchUserIdentifiersRequest(BaseModel):
    identifiers: List[str]  # Can be usernames or emails

class OrganizationCreateRequest(BaseModel):
    name: str
    description: str | None = None

class BatchOrganizationRequest(BaseModel):
    organizations: List[OrganizationCreateRequest]

class BatchOperationResult(BaseModel):
    successful: List[str]
    failed: List[dict]
    total_processed: int
    successful_count: int
    failed_count: int