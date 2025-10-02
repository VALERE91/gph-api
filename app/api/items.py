from typing import Union, Annotated

from fastapi import APIRouter, Depends

from app.auth import get_current_active_user, AuthUser, PermissionChecker
from app.database import DbSessionDep

router = APIRouter(
    prefix="/items",
    tags=["items"],
    responses={404: {"description": "Not found"}},
)

@router.get("/")
def read_root():
    return {"Hello": "Items"}

@router.get("/{item_id}", dependencies=[Depends(PermissionChecker(["team.create", "team.update", "team.superadmin"]))])
def read_item(session: DbSessionDep, current_user: Annotated[AuthUser, Depends(get_current_active_user)], item_id: int, q: Union[str, None] = None):
    return current_user