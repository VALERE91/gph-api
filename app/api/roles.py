from typing import Annotated, List
from fastapi import APIRouter, Depends
from sqlmodel import select
from pydantic import BaseModel

from app.auth import get_current_active_user, AuthUser, PermissionChecker
from app.database import DbSessionDep
from app.models.user import Role

class RoleResponse(BaseModel):
    id: int
    name: str
    description: str | None = None

router = APIRouter(
    prefix="/roles",
    tags=["roles"],
    responses={404: {"description": "Not found"}},
)

@router.get("/", dependencies=[Depends(PermissionChecker(["user.superadmin"]))])
def list_roles(
    session: DbSessionDep,
    current_user: Annotated[AuthUser, Depends(get_current_active_user)]
) -> List[RoleResponse]:
    """List all roles (requires superadmin permission)"""
    statement = select(Role)
    roles = session.exec(statement).all()

    return [
        RoleResponse(
            id=role.id,
            name=role.name,
            description=role.description
        )
        for role in roles
    ]
