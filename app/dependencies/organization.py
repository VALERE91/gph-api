from typing import Union
from fastapi import HTTPException
from sqlmodel import select
from starlette import status

from app.database import DbSessionDep
from app.models.organization import Organization


def get_organization_by_id_or_name(session: DbSessionDep, identifier: str) -> Organization:
    """Get organization by ID (int) or name (str)"""
    if identifier.isdigit():
        # It's an ID
        org_id = int(identifier)
        organization = session.get(Organization, org_id)
    else:
        # It's a name
        organization = session.exec(
            select(Organization).where(Organization.name == identifier)
        ).first()

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization not found: {identifier}"
        )
    return organization
