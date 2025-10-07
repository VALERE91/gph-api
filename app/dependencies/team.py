from sqlmodel import select

from app.database import DbSessionDep
from app.models.team import TeamMember

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