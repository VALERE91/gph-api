from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select, or_
from starlette import status
from pydantic import BaseModel

from app.auth import get_current_active_user, AuthUser, PermissionChecker
from app.database import DbSessionDep
from app.dependencies.team import check_user_team_ownership
from app.models.team import Team, TeamMember, BatchTeamRequest, BatchOperationResult, AddUserToTeamRequest, \
    BatchUserIdentifiersRequest
from app.models.user import User
from app.models.organization import Organization, OrganizationMemberLink
from app.dependencies.organization import get_organization_by_id_or_name

router = APIRouter(
    prefix="/teams",
    tags=["teams"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", status_code=status.HTTP_201_CREATED, dependencies=[Depends(PermissionChecker(["team.create", "team.superadmin"]))])
def create_team(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    team: Team
):
    """Create a new team"""
    # Validate that the organization exists if provided
    if team.organization_id:
        organization = session.get(Organization, team.organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found"
            )

    db_team = Team.model_validate(team)
    session.add(db_team)
    session.commit()
    session.refresh(db_team)
    return db_team

@router.post("/batch", status_code=status.HTTP_200_OK, dependencies=[Depends(PermissionChecker(["team.create", "team.superadmin"]))])
def batch_create_teams(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    request: BatchTeamRequest
) -> BatchOperationResult:
    """Create multiple teams in batch"""
    successful = []
    failed = []
    created_teams = []

    for team_data in request.teams:
        try:
            # Validate that the organization exists if provided
            if team_data.organization_id:
                organization = session.get(Organization, team_data.organization_id)
                if not organization:
                    failed.append({
                        "name": team_data.name,
                        "reason": f"Organization with ID {team_data.organization_id} not found"
                    })
                    continue

            # Create new team
            db_team = Team(
                name=team_data.name,
                description=team_data.description,
                organization_id=team_data.organization_id,
                max_builds=team_data.max_builds
            )
            session.add(db_team)
            created_teams.append(db_team)
            successful.append(team_data.name)

        except Exception as e:
            failed.append({
                "name": team_data.name,
                "reason": f"Unexpected error: {str(e)}"
            })

    # Commit all successful creations
    if created_teams:
        session.commit()
        # Refresh all created teams to get their IDs
        for team in created_teams:
            session.refresh(team)

    return BatchOperationResult(
        successful=successful,
        failed=failed,
        total_processed=len(request.teams),
        successful_count=len(successful),
        failed_count=len(failed)
    )

@router.get("/", dependencies=[Depends(PermissionChecker(["team.list", "team.superadmin"]))])
def list_teams(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    organization_identifier: str = None,
    skip: int = 0,
    limit: int = 100
):
    """List all teams with optional organization filtering and pagination"""
    statement = select(Team)
    if organization_identifier:
        # Get organization by ID or name using common dependency
        organization = get_organization_by_id_or_name(session, organization_identifier)
        statement = statement.where(Team.organization_id == organization.id)
    statement = statement.offset(skip).limit(limit)
    teams = session.exec(statement).all()
    return teams

@router.get("/{team_id}", dependencies=[Depends(PermissionChecker(["team.list", "team.superadmin"]))])
def get_team(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    team_id: int
):
    """Get a specific team by ID"""
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )
    return team

@router.put("/{team_id}", dependencies=[Depends(PermissionChecker(["team.update", "team.superadmin"]))])
def update_team(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    team_id: int,
    team_update: Team
):
    """Update an existing team"""
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    # Prevent updating organization_id as this scenario is not supported
    if team_update.name and team_update.name != team.name:
        team.name = team_update.name

    if team_update.description and team_update.description != team.description:
        team.description = team_update.description

    session.add(team)
    session.commit()
    session.refresh(team)
    return team

@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(PermissionChecker(["team.delete", "team.superadmin"]))])
def delete_team(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    team_id: int
):
    """Delete a team"""
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    session.delete(team)
    session.commit()
    return None

@router.post("/{team_id}/users/{user_id}", status_code=status.HTTP_201_CREATED, dependencies=[Depends(PermissionChecker(["team.update", "team.superadmin"]))])
def add_user_to_team(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    team_id: int,
    user_id: int,
    request: AddUserToTeamRequest
):
    """Add a user to a team (user must be a member of the team's organization and current user must be team owner or superadmin)"""
    # Check if team exists
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    # Get current user's ID
    current_user_db = session.exec(select(User).where(User.username == current_user.username)).first()
    if not current_user_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current user not found"
        )

    # Check if current user is a team owner OR has superadmin permission
    is_superadmin = "team.superadmin" in current_user.permissions
    if not is_superadmin and not check_user_team_ownership(session, current_user_db.id, team_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team owners or superadmins can add users to the team"
        )

    # Check if user exists
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Check if user is a member of the team's organization
    if team.organization_id:
        org_membership = session.exec(
            select(OrganizationMemberLink).where(
                OrganizationMemberLink.organization_id == team.organization_id,
                OrganizationMemberLink.user_id == user_id
            )
        ).first()

        if not org_membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User must be a member of the team's organization before being added to the team"
            )

    # Check if user is already a team member
    existing_member = session.exec(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user_id
        )
    ).first()

    if existing_member:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this team"
        )

    # Add user to team with specified ownership
    team_member = TeamMember(team_id=team_id, user_id=user_id, is_owner=request.is_owner)
    session.add(team_member)
    session.commit()

    return {"message": "User added to team successfully", "team_id": team_id, "user_id": user_id}

@router.delete("/{team_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(PermissionChecker(["team.update", "team.superadmin"]))])
def remove_user_from_team(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    team_id: int,
    user_id: int
):
    """Remove a user from a team (team owners or superadmins can remove users)"""
    # Check if team exists
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    # Get current user's ID
    current_user_db = session.exec(select(User).where(User.username == current_user.username)).first()
    if not current_user_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current user not found"
        )

    # Check if current user is a team owner OR has superadmin permission
    is_superadmin = "team.superadmin" in current_user.permissions
    if not is_superadmin and not check_user_team_ownership(session, current_user_db.id, team_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team owners or superadmins can remove users from the team"
        )

    # Check if user exists
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Find the team membership
    team_member = session.exec(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user_id
        )
    ).first()

    if not team_member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this team"
        )

    # Prevent removing the last owner
    if team_member.is_owner:
        owner_count = session.exec(
            select(TeamMember).where(
                TeamMember.team_id == team_id,
                TeamMember.is_owner == True
            )
        ).all()

        if len(owner_count) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last owner from the team"
            )

    # Remove user from team
    session.delete(team_member)
    session.commit()
    return None

@router.get("/{team_id}/users", dependencies=[Depends(PermissionChecker(["team.list", "team.superadmin"]))])
def list_team_users(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    team_id: int,
    skip: int = 0,
    limit: int = 100
):
    """List all users in a team"""
    # Check if team exists
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    # Get users in the team
    statement = (
        select(User)
        .join(TeamMember, TeamMember.user_id == User.id)
        .where(TeamMember.team_id == team_id)
        .offset(skip)
        .limit(limit)
    )

    users = session.exec(statement).all()
    return users

@router.post("/{team_id}/users/batch", status_code=status.HTTP_200_OK, dependencies=[Depends(PermissionChecker(["team.update", "team.superadmin"]))])
def batch_add_users_to_team(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    team_id: int,
    request: BatchUserIdentifiersRequest
) -> BatchOperationResult:
    """Add multiple users to a team by their username or email addresses (team owners or superadmins can do this)"""
    # Check if team exists
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    # Get current user's ID
    current_user_db = session.exec(select(User).where(User.username == current_user.username)).first()
    if not current_user_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current user not found"
        )

    # Check if current user is a team owner OR has superadmin permission
    is_superadmin = "team.superadmin" in current_user.permissions
    if not is_superadmin and not check_user_team_ownership(session, current_user_db.id, team_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team owners or superadmins can add users to the team"
        )

    successful = []
    failed = []

    for identifier in request.identifiers:
        try:
            # Find user by username or email
            user = session.exec(
                select(User).where(
                    or_(User.email == identifier, User.username == identifier)
                )
            ).first()

            if not user:
                failed.append({
                    "identifier": identifier,
                    "reason": "User not found"
                })
                continue

            # Check if user is a member of the team's organization
            if team.organization_id:
                org_membership = session.exec(
                    select(OrganizationMemberLink).where(
                        OrganizationMemberLink.organization_id == team.organization_id,
                        OrganizationMemberLink.user_id == user.id
                    )
                ).first()

                if not org_membership:
                    failed.append({
                        "identifier": identifier,
                        "reason": "User must be a member of the team's organization before being added to the team"
                    })
                    continue

            # Check if user is already a team member
            existing_member = session.exec(
                select(TeamMember).where(
                    TeamMember.team_id == team_id,
                    TeamMember.user_id == user.id
                )
            ).first()

            if existing_member:
                failed.append({
                    "identifier": identifier,
                    "reason": "User is already a member of this team"
                })
                continue

            # Add user to team with specified ownership
            team_member = TeamMember(team_id=team_id, user_id=user.id, is_owner=request.is_owner)
            session.add(team_member)
            successful.append(identifier)

        except Exception as e:
            failed.append({
                "identifier": identifier,
                "reason": f"Unexpected error: {str(e)}"
            })

    # Commit all successful additions
    session.commit()

    return BatchOperationResult(
        successful=successful,
        failed=failed,
        total_processed=len(request.identifiers),
        successful_count=len(successful),
        failed_count=len(failed)
    )

@router.delete("/{team_id}/users/batch", status_code=status.HTTP_200_OK, dependencies=[Depends(PermissionChecker(["team.update", "team.superadmin"]))])
def batch_remove_users_from_team(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    team_id: int,
    request: BatchUserIdentifiersRequest
) -> BatchOperationResult:
    """Remove multiple users from a team by their username or email addresses (team owners or superadmins can do this)"""
    # Check if team exists
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    # Get current user's ID
    current_user_db = session.exec(select(User).where(User.username == current_user.username)).first()
    if not current_user_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current user not found"
        )

    # Check if current user is a team owner OR has superadmin permission
    is_superadmin = "team.superadmin" in current_user.permissions
    if not is_superadmin and not check_user_team_ownership(session, current_user_db.id, team_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team owners or superadmins can remove users from the team"
        )

    successful = []
    failed = []

    for identifier in request.identifiers:
        try:
            # Find user by username or email
            user = session.exec(
                select(User).where(
                    or_(User.email == identifier, User.username == identifier)
                )
            ).first()

            if not user:
                failed.append({
                    "identifier": identifier,
                    "reason": "User not found"
                })
                continue

            # Find the team membership
            team_member = session.exec(
                select(TeamMember).where(
                    TeamMember.team_id == team_id,
                    TeamMember.user_id == user.id
                )
            ).first()

            if not team_member:
                failed.append({
                    "identifier": identifier,
                    "reason": "User is not a member of this team"
                })
                continue

            # Prevent removing the last owner
            if team_member.is_owner:
                owner_count = session.exec(
                    select(TeamMember).where(
                        TeamMember.team_id == team_id,
                        TeamMember.is_owner == True
                    )
                ).all()

                if len(owner_count) <= 1:
                    failed.append({
                        "identifier": identifier,
                        "reason": "Cannot remove the last owner from the team"
                    })
                    continue

            # Remove user from team
            session.delete(team_member)
            successful.append(identifier)

        except Exception as e:
            failed.append({
                "identifier": identifier,
                "reason": f"Unexpected error: {str(e)}"
            })

    # Commit all successful removals
    session.commit()

    return BatchOperationResult(
        successful=successful,
        failed=failed,
        total_processed=len(request.identifiers),
        successful_count=len(successful),
        failed_count=len(failed)
    )
