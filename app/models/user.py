from sqlmodel import SQLModel, Field

class Role(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str | None = None

class Permission(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str | None = None

class RolePermission(SQLModel, table=True):
    role_id: int | None = Field(default=None, primary_key=True)
    permission_id: int | None = Field(default=None, primary_key=True)

class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str
    email: str
    hashed_password: str
    full_name: str | None = None
    is_active: bool = True
    role_id: int | None = Field(default=None, foreign_key="role.id")