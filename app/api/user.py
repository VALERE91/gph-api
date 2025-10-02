from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select, or_
from starlette import status
from pydantic import BaseModel

from app.auth import get_current_active_user, AuthUser, PermissionChecker, get_password_hash
from app.database import DbSessionDep
from app.models.user import User, Role
from app.settings import get_settings

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    full_name: str | None = None
    is_active: bool = True
    role_id: int | None = None

class UserUpdate(BaseModel):
    username: str | None = None
    email: str | None = None
    password: str | None = None
    full_name: str | None = None
    is_active: bool | None = None
    role_id: int | None = None

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str | None = None
    is_active: bool
    role_id: int | None = None

class BatchUserCreateRequest(BaseModel):
    users: List[UserCreate]

class BatchUserUpdateRequest(BaseModel):
    identifiers: List[str]  # usernames or emails
    updates: UserUpdate

class BatchUserDeleteRequest(BaseModel):
    identifiers: List[str]  # usernames or emails

class BatchOperationResult(BaseModel):
    successful: List[str]
    failed: List[dict]
    total_processed: int
    successful_count: int
    failed_count: int

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", status_code=status.HTTP_201_CREATED, dependencies=[Depends(PermissionChecker(["user.create", "user.superadmin"]))])
def create_user(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    user_create: UserCreate
) -> UserResponse:
    """Create a new user"""
    # Check if username already exists
    existing_user = session.exec(select(User).where(User.username == user_create.username)).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists"
        )

    # Check if email already exists
    existing_email = session.exec(select(User).where(User.email == user_create.email)).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists"
        )

    # Validate role exists if provided
    if user_create.role_id is not None:
        role = session.get(Role, user_create.role_id)
        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found"
            )

    # Hash password and create user
    hashed_password = get_password_hash(user_create.password)
    db_user = User(
        username=user_create.username,
        email=user_create.email,
        hashed_password=hashed_password,
        full_name=user_create.full_name,
        is_active=user_create.is_active,
        role_id=user_create.role_id
    )

    session.add(db_user)
    session.commit()
    session.refresh(db_user)

    return UserResponse(
        id=db_user.id,
        username=db_user.username,
        email=db_user.email,
        full_name=db_user.full_name,
        is_active=db_user.is_active,
        role_id=db_user.role_id
    )

@router.get("/", dependencies=[Depends(PermissionChecker(["user.list", "user.superadmin"]))])
def list_users(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    role_id: int = None,
    is_active: bool = None,
    skip: int = 0,
    limit: int = 100
) -> List[UserResponse]:
    """List all users with optional filtering and pagination"""
    statement = select(User)

    if role_id is not None:
        statement = statement.where(User.role_id == role_id)
    if is_active is not None:
        statement = statement.where(User.is_active == is_active)

    statement = statement.offset(skip).limit(limit)
    users = session.exec(statement).all()

    return [
        UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            role_id=user.role_id
        )
        for user in users
    ]

@router.get("/{user_id}", dependencies=[Depends(PermissionChecker(["user.list", "user.superadmin"]))])
def get_user(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    user_id: int
) -> UserResponse:
    """Get a specific user by ID"""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        role_id=user.role_id
    )

@router.put("/{user_id}", dependencies=[Depends(PermissionChecker(["user.update", "user.superadmin"]))])
def update_user(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    user_id: int,
    user_update: UserUpdate
) -> UserResponse:
    """Update an existing user"""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Check for username conflicts if updating username
    if user_update.username and user_update.username != user.username:
        existing_user = session.exec(select(User).where(User.username == user_update.username)).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already exists"
            )
        user.username = user_update.username

    # Check for email conflicts if updating email
    if user_update.email and user_update.email != user.email:
        existing_email = session.exec(select(User).where(User.email == user_update.email)).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already exists"
            )
        user.email = user_update.email

    # Validate role exists if updating role
    if user_update.role_id is not None:
        role = session.get(Role, user_update.role_id)
        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found"
            )
        user.role_id = user_update.role_id

    # Handle password hashing if password is being updated
    if user_update.password is not None:
        user.hashed_password = get_password_hash(user_update.password)

    if user_update.full_name is not None:
        user.full_name = user_update.full_name
    if user_update.is_active is not None:
        user.is_active = user_update.is_active

    session.add(user)
    session.commit()
    session.refresh(user)

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        role_id=user.role_id
    )

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(PermissionChecker(["user.delete", "user.superadmin"]))])
def delete_user(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    user_id: int
):
    """Delete a user"""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Prevent users from deleting themselves
    if current_user.username == user.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own user account"
        )

    # Prevent deletion of the automatically created superuser (failsafe)
    settings = get_settings()
    if user.username == settings.superuser_username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete the system superuser account - this is a failsafe to ensure API access"
        )

    session.delete(user)
    session.commit()
    return None

@router.post("/batch", status_code=status.HTTP_200_OK, dependencies=[Depends(PermissionChecker(["user.create", "user.superadmin"]))])
def batch_create_users(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    request: BatchUserCreateRequest
) -> BatchOperationResult:
    """Create multiple users in batch"""
    successful = []
    failed = []

    for user_create in request.users:
        try:
            # Check if username already exists
            existing_user = session.exec(select(User).where(User.username == user_create.username)).first()
            if existing_user:
                failed.append({
                    "identifier": user_create.username,
                    "reason": "Username already exists"
                })
                continue

            # Check if email already exists
            existing_email = session.exec(select(User).where(User.email == user_create.email)).first()
            if existing_email:
                failed.append({
                    "identifier": user_create.username,
                    "reason": "Email already exists"
                })
                continue

            # Validate role exists if provided
            if user_create.role_id is not None:
                role = session.get(Role, user_create.role_id)
                if not role:
                    failed.append({
                        "identifier": user_create.username,
                        "reason": "Role not found"
                    })
                    continue

            # Hash password and create user
            hashed_password = get_password_hash(user_create.password)
            db_user = User(
                username=user_create.username,
                email=user_create.email,
                hashed_password=hashed_password,
                full_name=user_create.full_name,
                is_active=user_create.is_active,
                role_id=user_create.role_id
            )

            session.add(db_user)
            successful.append(user_create.username)

        except Exception as e:
            failed.append({
                "identifier": user_create.username,
                "reason": f"Unexpected error: {str(e)}"
            })

    # Commit all successful creations
    session.commit()

    return BatchOperationResult(
        successful=successful,
        failed=failed,
        total_processed=len(request.users),
        successful_count=len(successful),
        failed_count=len(failed)
    )

@router.put("/batch", status_code=status.HTTP_200_OK, dependencies=[Depends(PermissionChecker(["user.update", "user.superadmin"]))])
def batch_update_users(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    request: BatchUserUpdateRequest
) -> BatchOperationResult:
    """Update multiple users in batch by username or email"""
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

            # Validate role exists if updating role
            if request.updates.role_id is not None:
                role = session.get(Role, request.updates.role_id)
                if not role:
                    failed.append({
                        "identifier": identifier,
                        "reason": "Role not found"
                    })
                    continue

            # Update user fields
            update_data = request.updates.model_dump(exclude_unset=True)

            # Handle password hashing if password is being updated
            if 'password' in update_data:
                update_data['hashed_password'] = get_password_hash(update_data.pop('password'))

            for key, value in update_data.items():
                setattr(user, key, value)

            session.add(user)
            successful.append(identifier)

        except Exception as e:
            failed.append({
                "identifier": identifier,
                "reason": f"Unexpected error: {str(e)}"
            })

    # Commit all successful updates
    session.commit()

    return BatchOperationResult(
        successful=successful,
        failed=failed,
        total_processed=len(request.identifiers),
        successful_count=len(successful),
        failed_count=len(failed)
    )

@router.delete("/batch", status_code=status.HTTP_200_OK, dependencies=[Depends(PermissionChecker(["user.delete", "user.superadmin"]))])
def batch_delete_users(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    request: BatchUserDeleteRequest
) -> BatchOperationResult:
    """Delete multiple users in batch by username or email"""
    successful = []
    failed = []

    # Get the superuser username for failsafe check using settings
    settings = get_settings()
    superuser_username = settings.superuser_username

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

            # Prevent users from deleting themselves
            if current_user.username == user.username:
                failed.append({
                    "identifier": identifier,
                    "reason": "Cannot delete your own user account"
                })
                continue

            # Prevent deletion of the automatically created superuser (failsafe)
            if user.username == superuser_username:
                failed.append({
                    "identifier": identifier,
                    "reason": "Cannot delete the system superuser account - this is a failsafe to ensure API access"
                })
                continue

            session.delete(user)
            successful.append(identifier)

        except Exception as e:
            failed.append({
                "identifier": identifier,
                "reason": f"Unexpected error: {str(e)}"
            })

    # Commit all successful deletions
    session.commit()

    return BatchOperationResult(
        successful=successful,
        failed=failed,
        total_processed=len(request.identifiers),
        successful_count=len(successful),
        failed_count=len(failed)
    )
