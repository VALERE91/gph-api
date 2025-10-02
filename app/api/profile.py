from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from starlette import status
from pydantic import BaseModel

from app.auth import get_current_active_user, AuthUser, get_password_hash
from app.database import DbSessionDep
from app.models.user import User, Role, Permission, RolePermission
from app.models.organization import Organization, OrganizationMemberLink
from app.models.team import Team, TeamMember

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

router = APIRouter(
    prefix="/profile",
    tags=["profile"],
    responses={404: {"description": "Not found"}},
)

@router.get("/")
def get_profile(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)]
) -> ProfileResponse:
    """Get current user's profile including organizations and teams"""
    # Get user details with role
    user = session.exec(select(User).where(User.username == current_user.username)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Get user's role
    role_data = None
    if user.role_id:
        role = session.get(Role, user.role_id)
        if role:
            role_data = {
                "id": role.id,
                "name": role.name,
                "description": role.description
            }

    # Get user's organizations
    organizations_query = (
        select(Organization)
        .join(OrganizationMemberLink, OrganizationMemberLink.organization_id == Organization.id)
        .where(OrganizationMemberLink.user_id == user.id)
    )
    organizations = session.exec(organizations_query).all()

    # Get user's teams
    teams_query = (
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user.id)
    )
    teams = session.exec(teams_query).all()

    # Get user's permissions
    permissions_query = (
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == user.role_id)
    )
    permissions = session.exec(permissions_query).all()

    return ProfileResponse(
        user=UserProfileResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            role=role_data
        ),
        organizations=[
            OrganizationResponse(
                id=org.id,
                name=org.name,
                description=org.description
            )
            for org in organizations
        ],
        teams=[
            TeamResponse(
                id=team.id,
                name=team.name,
                description=team.description,
                organization_id=team.organization_id
            )
            for team in teams
        ],
        permissions=[
            PermissionResponse(
                id=perm.id,
                name=perm.name,
                description=perm.description
            )
            for perm in permissions
        ]
    )

@router.put("/password", status_code=status.HTTP_200_OK)
def change_password(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    password_request: PasswordChangeRequest
) -> dict:
    """Change current user's password"""
    # Get user from database
    user = session.exec(select(User).where(User.username == current_user.username)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Verify current password
    from app.auth import verify_password
    if not verify_password(password_request.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # Hash new password and update
    new_hashed_password = get_password_hash(password_request.new_password)
    user.hashed_password = new_hashed_password

    session.add(user)
    session.commit()

    return {"message": "Password changed successfully"}

@router.get("/organizations")
def get_user_organizations(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)]
) -> List[OrganizationResponse]:
    """Get current user's organizations"""
    user = session.exec(select(User).where(User.username == current_user.username)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    organizations_query = (
        select(Organization)
        .join(OrganizationMemberLink, OrganizationMemberLink.organization_id == Organization.id)
        .where(OrganizationMemberLink.user_id == user.id)
    )
    organizations = session.exec(organizations_query).all()

    return [
        OrganizationResponse(
            id=org.id,
            name=org.name,
            description=org.description
        )
        for org in organizations
    ]

@router.get("/teams")
def get_user_teams(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)]
) -> List[TeamResponse]:
    """Get current user's teams"""
    user = session.exec(select(User).where(User.username == current_user.username)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    teams_query = (
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user.id)
    )
    teams = session.exec(teams_query).all()

    return [
        TeamResponse(
            id=team.id,
            name=team.name,
            description=team.description,
            organization_id=team.organization_id
        )
        for team in teams
    ]
