from typing import List

from pydantic import BaseModel


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

class UserProfileResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str | None = None
    is_active: bool
    role: dict | None = None

class OrganizationResponse(BaseModel):
    id: int
    name: str
    description: str | None = None

class TeamResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    organization_id: int | None = None

class PermissionResponse(BaseModel):
    id: int
    name: str
    description: str | None = None

class ProfileResponse(BaseModel):
    user: UserProfileResponse
    organizations: List[OrganizationResponse]
    teams: List[TeamResponse]
    permissions: List[PermissionResponse]
