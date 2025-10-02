from datetime import timedelta, datetime, timezone
from typing import Annotated

import jwt
from fastapi import Depends, APIRouter, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from pydantic.v1 import BaseModel
from sqlmodel import select
from starlette import status

from app.database import DbSessionDep
from app.models.user import User, RolePermission, Role, Permission
from app.settings import get_settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    responses={404: {"description": "Not found"}},
)

password_hash = PasswordHash.recommended()

class AuthUser(BaseModel):
    username: str
    hashed_password: str
    email: str | None = None
    full_name: str | None = None
    disabled: bool | None = None
    permissions: list[str] = []

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None
    permissions: list[str] = []

def get_user(session: DbSessionDep, username: str):
    statement = (select(User, Role)
                    .where(User.username == username, User.role_id == Role.id))
    results = session.exec(statement)

    # Get the first result and check if it exists
    first_result = results.first()
    if first_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User not found: {username}"
        )

    [user_db, role] = first_result
    if user_db:
        role_permissions = session.exec(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        ).all()
        permissions = [perm.name for perm in role_permissions]
        return AuthUser(
            username=user_db.username,
            hashed_password=user_db.hashed_password,
            email=user_db.email,
            full_name=user_db.full_name,
            disabled=not user_db.is_active,
            permissions=permissions
        )
    return None

def verify_password(plain_password, hashed_password):
    return password_hash.verify(plain_password, hashed_password)

def get_password_hash(password):
    return password_hash.hash(password)

def authenticate_user(session: DbSessionDep, username: str, password: str):
    user = get_user(session, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)],session: DbSessionDep):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except InvalidTokenError:
        raise credentials_exception
    user = get_user(session, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    settings = get_settings()
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return encoded_jwt

async def get_current_active_user(
    current_user: Annotated[AuthUser, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

class PermissionChecker:
    def __init__(self, permission: [str]):
        self.permission = permission

    def __call__(self, current_user: Annotated[AuthUser, Depends(get_current_active_user)]):
        permissions_to_check = self.permission if isinstance(self.permission, list) else [self.permission]

        # Check if user has at least one of the required permissions (OR logic)
        has_permission = any(perm in current_user.permissions for perm in permissions_to_check)

        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted",
            )

@router.post("/token")
async def login(session: DbSessionDep, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    user = authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    settings = get_settings()
    access_token_expires = timedelta(minutes=settings.access_token_expire_seconds/60)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")

@router.post("/signup", status_code=201)
async def login(session: DbSessionDep, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    session.add(User(
        username=form_data.username,
        email=form_data.username,
        hashed_password=get_password_hash(form_data.password),
        is_active=True
    ))
    session.commit()
    user = authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    settings = get_settings()
    access_token_expires = timedelta(minutes=settings.access_token_expire_seconds/60)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")