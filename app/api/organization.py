from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select, or_
from starlette import status
from pydantic import BaseModel

from app.auth import get_current_active_user, AuthUser, PermissionChecker
from app.database import DbSessionDep
from app.models.organization import Organization, OrganizationMemberLink
from app.models.user import User
from app.dependencies.organization import get_organization_by_id_or_name

class BatchUserIdentifiersRequest(BaseModel):
    identifiers: List[str]  # Can be usernames or emails

class BatchOperationResult(BaseModel):
    successful: List[str]
    failed: List[dict]
    total_processed: int
    successful_count: int
    failed_count: int

router = APIRouter(
    prefix="/organizations",
    tags=["organizations"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", status_code=status.HTTP_201_CREATED, dependencies=[Depends(PermissionChecker(["organization.create", "organization.superadmin"]))])
def create_organization(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    organization: Organization
):
    """Create a new organization"""
    # Check if organization name already exists
    existing_org = session.exec(
        select(Organization).where(Organization.name == organization.name)
    ).first()
    if existing_org:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Organization name '{organization.name}' already exists"
        )

    db_organization = Organization.model_validate(organization)
    session.add(db_organization)
    session.commit()
    session.refresh(db_organization)
    return db_organization

@router.get("/", dependencies=[Depends(PermissionChecker(["organization.list", "organization.superadmin"]))])
def list_organizations(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    skip: int = 0,
    limit: int = 100
):
    """List all organizations with pagination"""
    statement = select(Organization).offset(skip).limit(limit)
    organizations = session.exec(statement).all()
    return organizations

@router.get("/{organization_identifier}", dependencies=[Depends(PermissionChecker(["organization.list", "organization.superadmin"]))])
def get_organization(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    organization_identifier: str
):
    """Get a specific organization by ID or name"""
    organization = get_organization_by_id_or_name(session, organization_identifier)
    return organization

@router.put("/{organization_identifier}", dependencies=[Depends(PermissionChecker(["organization.update", "organization.superadmin"]))])
def update_organization(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    organization_identifier: str,
    organization_update: Organization
):
    """Update an existing organization"""
    organization = get_organization_by_id_or_name(session, organization_identifier)

    # Check if new name conflicts with existing organization (if name is being changed)
    if organization_update.name and organization_update.name != organization.name:
        existing_org = session.exec(
            select(Organization).where(Organization.name == organization_update.name)
        ).first()
        if existing_org:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Organization name '{organization_update.name}' already exists"
            )

    organization_data = organization_update.model_dump(exclude_unset=True)
    for key, value in organization_data.items():
        setattr(organization, key, value)

    session.add(organization)
    session.commit()
    session.refresh(organization)
    return organization

@router.delete("/{organization_identifier}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(PermissionChecker(["organization.delete", "organization.superadmin"]))])
def delete_organization(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    organization_identifier: str
):
    """Delete an organization"""
    organization = get_organization_by_id_or_name(session, organization_identifier)

    session.delete(organization)
    session.commit()
    return None

@router.post("/{organization_identifier}/users/{user_id}", status_code=status.HTTP_201_CREATED, dependencies=[Depends(PermissionChecker(["organization.update", "organization.superadmin"]))])
def add_user_to_organization(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    organization_identifier: str,
    user_id: int
):
    """Add a user to an organization"""
    # Get organization by ID or name
    organization = get_organization_by_id_or_name(session, organization_identifier)

    # Check if user exists
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Check if user is already a member
    existing_link = session.exec(
        select(OrganizationMemberLink).where(
            OrganizationMemberLink.organization_id == organization.id,
            OrganizationMemberLink.user_id == user_id
        )
    ).first()

    if existing_link:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this organization"
        )

    # Add user to organization
    member_link = OrganizationMemberLink(organization_id=organization.id, user_id=user_id)
    session.add(member_link)
    session.commit()

    return {"message": "User added to organization successfully", "organization_id": organization.id, "organization_name": organization.name, "user_id": user_id}

@router.delete("/{organization_identifier}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(PermissionChecker(["organization.update", "organization.superadmin"]))])
def remove_user_from_organization(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    organization_identifier: str,
    user_id: int
):
    """Remove a user from an organization"""
    # Get organization by ID or name
    organization = get_organization_by_id_or_name(session, organization_identifier)

    # Check if user exists
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Find the membership link
    member_link = session.exec(
        select(OrganizationMemberLink).where(
            OrganizationMemberLink.organization_id == organization.id,
            OrganizationMemberLink.user_id == user_id
        )
    ).first()

    if not member_link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this organization"
        )

    # Remove user from organization
    session.delete(member_link)
    session.commit()
    return None

@router.get("/{organization_identifier}/users", dependencies=[Depends(PermissionChecker(["organization.list", "organization.superadmin"]))])
def list_organization_users(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    organization_identifier: str,
    skip: int = 0,
    limit: int = 100
):
    """List all users in an organization"""
    # Get organization by ID or name
    organization = get_organization_by_id_or_name(session, organization_identifier)

    # Get users in the organization
    statement = (
        select(User)
        .join(OrganizationMemberLink, OrganizationMemberLink.user_id == User.id)
        .where(OrganizationMemberLink.organization_id == organization.id)
        .offset(skip)
        .limit(limit)
    )

    users = session.exec(statement).all()
    return users

@router.post("/{organization_identifier}/users/batch", status_code=status.HTTP_200_OK, dependencies=[Depends(PermissionChecker(["organization.update", "organization.superadmin"]))])
def batch_add_users_to_organization(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    organization_identifier: str,
    request: BatchUserIdentifiersRequest
) -> BatchOperationResult:
    """Add multiple users to an organization by their username or email addresses"""
    # Get organization by ID or name
    organization = get_organization_by_id_or_name(session, organization_identifier)

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

            # Check if user is already a member
            existing_link = session.exec(
                select(OrganizationMemberLink).where(
                    OrganizationMemberLink.organization_id == organization.id,
                    OrganizationMemberLink.user_id == user.id
                )
            ).first()

            if existing_link:
                failed.append({
                    "identifier": identifier,
                    "reason": "User is already a member of this organization"
                })
                continue

            # Add user to organization
            member_link = OrganizationMemberLink(organization_id=organization.id, user_id=user.id)
            session.add(member_link)
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

@router.delete("/{organization_identifier}/users/batch", status_code=status.HTTP_200_OK, dependencies=[Depends(PermissionChecker(["organization.update", "organization.superadmin"]))])
def batch_remove_users_from_organization(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    organization_identifier: str,
    request: BatchUserIdentifiersRequest
) -> BatchOperationResult:
    """Remove multiple users from an organization by their username or email addresses"""
    # Get organization by ID or name
    organization = get_organization_by_id_or_name(session, organization_identifier)

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

            # Find the membership link
            member_link = session.exec(
                select(OrganizationMemberLink).where(
                    OrganizationMemberLink.organization_id == organization.id,
                    OrganizationMemberLink.user_id == user.id
                )
            ).first()

            if not member_link:
                failed.append({
                    "identifier": identifier,
                    "reason": "User is not a member of this organization"
                })
                continue

            # Remove user from organization
            session.delete(member_link)
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
