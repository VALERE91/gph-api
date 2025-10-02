from typing import Annotated, List
from datetime import datetime
import uuid
import random
import string
import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from starlette import status
from pydantic import BaseModel

from app.auth import get_current_active_user, AuthUser, PermissionChecker
from app.database import DbSessionDep
from app.models.build import Build
from app.models.team import Team, TeamMember
from app.models.user import User
from app.settings import get_settings

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

router = APIRouter(
    prefix="/builds",
    tags=["builds"],
    responses={404: {"description": "Not found"}},
)

def get_s3_client():
    """Get configured S3 client"""
    settings = get_settings()
    return boto3.client(
        's3',
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region_name
    )

def generate_s3_path(team_id: int, build_name: str, version: str) -> str:
    """Generate S3 path for build upload"""
    # Create unique filename to avoid conflicts
    unique_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{build_name}_{version}_{timestamp}_{unique_id}"
    return f"builds/team_{team_id}/{filename}"

def generate_presigned_upload_url(s3_path: str, expiration: int = 3600) -> str:
    """Generate presigned URL for S3 upload"""
    settings = get_settings()
    s3_client = get_s3_client()

    try:
        url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': settings.s3_bucket_name,
                'Key': s3_path,
                'ContentType': 'application/octet-stream'
            },
            ExpiresIn=expiration
        )
        return url
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate upload URL: {str(e)}"
        )

def check_user_team_membership(session: DbSessionDep, user_id: int, team_id: int) -> bool:
    """Check if user is a member of the specified team"""
    membership = session.exec(
        select(TeamMember).where(
            TeamMember.user_id == user_id,
            TeamMember.team_id == team_id
        )
    ).first()
    return membership is not None

def check_user_team_ownership(session: DbSessionDep, user_id: int, team_id: int) -> bool:
    """Check if user is an owner of the specified team"""
    membership = session.exec(
        select(TeamMember).where(
            TeamMember.user_id == user_id,
            TeamMember.team_id == team_id,
            TeamMember.is_owner == True
        )
    ).first()
    return membership is not None

def generate_short_id(length: int = 6) -> str:
    """Generate a random short ID using alphanumeric characters"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def generate_unique_short_id(session: DbSessionDep, length: int = 6) -> str:
    """Generate a unique short ID that doesn't exist in the database"""
    max_attempts = 100
    for _ in range(max_attempts):
        short_id = generate_short_id(length)
        existing = session.exec(select(Build).where(Build.short_id == short_id)).first()
        if not existing:
            return short_id
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to generate unique short ID"
    )

@router.post("/", status_code=status.HTTP_201_CREATED, dependencies=[Depends(PermissionChecker(["build.create", "build.superadmin"]))])
def create_build(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    build_create: BuildCreate,
    override_quota: bool = False
) -> BuildResponse:
    """Create a new build and return it with a presigned S3 upload URL"""
    # Check if team exists
    team = session.get(Team, build_create.team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    # Get current user's ID
    user = session.exec(select(User).where(User.username == current_user.username)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current user not found"
        )

    # Check if user is a member of the team or has superadmin permission
    if not (check_user_team_membership(session, user.id, build_create.team_id) or "build.superadmin" in current_user.permissions):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must be a member of the team or have superadmin permission to create builds"
        )

    # Check build quota
    current_builds = session.exec(
        select(Build).where(Build.team_id == build_create.team_id)
    ).all()

    if len(current_builds) >= team.max_builds and not override_quota:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"Build quota exceeded ({len(current_builds)}/{team.max_builds}). As a team owner, you can override this by adding '?override_quota=true' to your request.",
                "current_builds": len(current_builds),
                "max_builds": team.max_builds,
                "override_url": f"/builds/?override_quota=true"
            }
        )

    # If override_quota is True and quota exceeded, delete oldest build
    if override_quota and len(current_builds) >= team.max_builds:
        oldest_build = session.exec(
            select(Build)
            .where(Build.team_id == build_create.team_id)
            .order_by(Build.created_at.asc())
        ).first()

        if oldest_build:
            # Delete from S3
            settings = get_settings()
            s3_client = get_s3_client()

            try:
                s3_client.delete_object(
                    Bucket=settings.s3_bucket_name,
                    Key=oldest_build.path
                )
            except ClientError as e:
                print(f"Warning: Failed to delete S3 object {oldest_build.path}: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "message": f"Unable to override quota because deletion of the oldest build from storage failed: {str(e)}",
                        "current_builds": len(current_builds),
                        "max_builds": team.max_builds
                    }
                )

            # Delete from database
            session.delete(oldest_build)
            session.commit()

    # Generate S3 path for the build
    s3_path = generate_s3_path(build_create.team_id, build_create.name, build_create.version)

    # Generate unique short ID
    short_id = generate_unique_short_id(session)

    # Create build record
    db_build = Build(
        name=build_create.name,
        version=build_create.version,
        path=s3_path,
        size=0,  # Will be updated when file is uploaded
        short_id=short_id,
        created_by=user.id,
        team_id=build_create.team_id
    )

    session.add(db_build)
    session.commit()
    session.refresh(db_build)

    # Generate presigned upload URL
    upload_url = generate_presigned_upload_url(s3_path)

    return BuildResponse(
        id=db_build.id,
        name=db_build.name,
        version=db_build.version,
        path=db_build.path,
        size=db_build.size,
        short_id=db_build.short_id,
        created_at=db_build.created_at,
        updated_at=db_build.updated_at,
        created_by=db_build.created_by,
        team_id=db_build.team_id,
        upload_url=upload_url,
        short_download_url=f"/builds/download/{db_build.short_id}"
    )

@router.get("/", dependencies=[Depends(PermissionChecker(["build.list", "build.superadmin"]))])
def list_builds(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    team_id: int = None,
    user_id: int = None,
    skip: int = 0,
    limit: int = 100
) -> List[BuildResponse]:
    """List builds with optional team or user filtering and pagination"""
    statement = select(Build)

    if team_id is not None:
        statement = statement.where(Build.team_id == team_id)
    if user_id is not None:
        statement = statement.where(Build.created_by == user_id)

    statement = statement.offset(skip).limit(limit).order_by(Build.created_at.desc())
    builds = session.exec(statement).all()

    return [
        BuildResponse(
            id=build.id,
            name=build.name,
            version=build.version,
            path=build.path,
            size=build.size,
            short_id=build.short_id,
            created_at=build.created_at,
            updated_at=build.updated_at,
            created_by=build.created_by,
            team_id=build.team_id,
            short_download_url=f"/builds/download/{build.short_id}"
        )
        for build in builds
    ]

@router.get("/team/{team_id}", dependencies=[Depends(PermissionChecker(["build.list", "build.superadmin"]))])
def list_team_builds(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    team_id: int,
    skip: int = 0,
    limit: int = 100
) -> List[BuildResponse]:
    """List builds for a specific team"""
    # Check if team exists
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    # Get current user's ID
    user = session.exec(select(User).where(User.username == current_user.username)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current user not found"
        )

    # Check if user is a member of the team or has superadmin permission
    if not (check_user_team_membership(session, user.id, team_id) or "build.superadmin" in current_user.permissions):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must be a member of the team or have superadmin permission to view builds"
        )

    statement = select(Build).where(Build.team_id == team_id).offset(skip).limit(limit).order_by(Build.created_at.desc())
    builds = session.exec(statement).all()

    return [
        BuildResponse(
            id=build.id,
            name=build.name,
            version=build.version,
            path=build.path,
            size=build.size,
            short_id=build.short_id,
            created_at=build.created_at,
            updated_at=build.updated_at,
            created_by=build.created_by,
            team_id=build.team_id,
            short_download_url=f"/builds/download/{build.short_id}"
        )
        for build in builds
    ]

@router.get("/user/{user_id}", dependencies=[Depends(PermissionChecker(["build.list", "build.superadmin"]))])
def list_user_builds(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    user_id: int,
    skip: int = 0,
    limit: int = 100
) -> List[BuildResponse]:
    """List builds for a specific user"""
    # Check if user exists
    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Get current user's ID
    current_user_db = session.exec(select(User).where(User.username == current_user.username)).first()
    if not current_user_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current user not found"
        )

    # Check if user is viewing their own builds or has superadmin permission
    if not (current_user_db.id == user_id or "build.superadmin" in current_user.permissions):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Users can only view their own builds unless they have superadmin permission"
        )

    statement = select(Build).where(Build.created_by == user_id).offset(skip).limit(limit).order_by(Build.created_at.desc())
    builds = session.exec(statement).all()

    return [
        BuildResponse(
            id=build.id,
            name=build.name,
            version=build.version,
            path=build.path,
            size=build.size,
            short_id=build.short_id,
            created_at=build.created_at,
            updated_at=build.updated_at,
            created_by=build.created_by,
            team_id=build.team_id,
            short_download_url=f"/builds/download/{build.short_id}"
        )
        for build in builds
    ]

@router.get("/{build_id}", dependencies=[Depends(PermissionChecker(["build.list", "build.superadmin"]))])
def get_build(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    build_id: int
) -> BuildResponse:
    """Get a specific build by ID"""
    build = session.get(Build, build_id)
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Build not found"
        )

    # Get current user's ID
    user = session.exec(select(User).where(User.username == current_user.username)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current user not found"
        )

    # Check if user is a member of the team or has superadmin permission
    if not (check_user_team_membership(session, user.id, build.team_id) or "build.superadmin" in current_user.permissions):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must be a member of the team or have superadmin permission to view build details"
        )

    return BuildResponse(
        id=build.id,
        name=build.name,
        version=build.version,
        path=build.path,
        size=build.size,
        short_id=build.short_id,
        created_at=build.created_at,
        updated_at=build.updated_at,
        created_by=build.created_by,
        team_id=build.team_id,
        short_download_url=f"/builds/download/{build.short_id}"
    )

@router.put("/{build_id}", dependencies=[Depends(PermissionChecker(["build.update", "build.superadmin"]))])
def update_build(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    build_id: int,
    build_update: BuildUpdate
) -> BuildResponse:
    """Update an existing build"""
    build = session.get(Build, build_id)
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Build not found"
        )

    # Get current user's ID
    user = session.exec(select(User).where(User.username == current_user.username)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current user not found"
        )

    # Check if user is a member of the team or has superadmin permission
    if not (check_user_team_membership(session, user.id, build.team_id) or "build.superadmin" in current_user.permissions):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must be a member of the team or have superadmin permission to update builds"
        )

    # Update build fields
    update_data = build_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(build, key, value)

    build.updated_at = datetime.utcnow()

    session.add(build)
    session.commit()
    session.refresh(build)

    return BuildResponse(
        id=build.id,
        name=build.name,
        version=build.version,
        path=build.path,
        size=build.size,
        short_id=build.short_id,
        created_at=build.created_at,
        updated_at=build.updated_at,
        created_by=build.created_by,
        team_id=build.team_id,
        short_download_url=f"/builds/download/{build.short_id}"
    )

@router.delete("/{build_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(PermissionChecker(["build.delete", "build.superadmin"]))])
def delete_build(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    build_id: int
):
    """Delete a build and its S3 object"""
    build = session.get(Build, build_id)
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Build not found"
        )

    # Get current user's ID
    user = session.exec(select(User).where(User.username == current_user.username)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current user not found"
        )

    # Check if user is a member of the team or has superadmin permission
    if not (check_user_team_membership(session, user.id, build.team_id) or "build.superadmin" in current_user.permissions):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must be a member of the team or have superadmin permission to delete builds"
        )

    # Delete from S3
    settings = get_settings()
    s3_client = get_s3_client()

    try:
        s3_client.delete_object(
            Bucket=settings.s3_bucket_name,
            Key=build.path
        )
    except ClientError as e:
        # Log the error but don't fail the deletion if S3 delete fails
        print(f"Warning: Failed to delete S3 object {build.path}: {str(e)}")

    # Delete from database
    session.delete(build)
    session.commit()
    return None

@router.get("/download/{short_id}")
def get_build_by_short_id(
    session: DbSessionDep,
    short_id: str
) -> dict:
    """Get presigned download URL for a build using short ID - no authentication required"""
    build = session.exec(select(Build).where(Build.short_id == short_id)).first()
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Build not found"
        )

    settings = get_settings()
    s3_client = get_s3_client()

    try:
        download_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': settings.s3_bucket_name,
                'Key': build.path
            },
            ExpiresIn=3600  # 1 hour expiration
        )

        return {
            "download_url": download_url,
            "expires_in": 3600,
            "build_id": build.id,
            "short_id": build.short_id,
            "name": build.name,
            "version": build.version,
            "size": build.size
        }
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate download URL: {str(e)}"
        )

@router.get("/{build_id}/download", dependencies=[Depends(PermissionChecker(["build.download", "build.superadmin"]))])
def get_build_download_url(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    build_id: int
) -> dict:
    """Get presigned download URL for a build"""
    build = session.get(Build, build_id)
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Build not found"
        )

    # Get current user's ID
    user = session.exec(select(User).where(User.username == current_user.username)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current user not found"
        )

    # Check if user is a member of the team or has superadmin permission
    if not (check_user_team_membership(session, user.id, build.team_id) or "build.superadmin" in current_user.permissions):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must be a member of the team or have superadmin permission to download builds"
        )

    settings = get_settings()
    s3_client = get_s3_client()

    try:
        download_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': settings.s3_bucket_name,
                'Key': build.path
            },
            ExpiresIn=3600  # 1 hour expiration
        )

        return {
            "download_url": download_url,
            "expires_in": 3600,
            "build_id": build.id,
            "name": build.name,
            "version": build.version,
            "size": build.size
        }
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate download URL: {str(e)}"
        )
