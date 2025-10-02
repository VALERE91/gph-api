import os
from sqlmodel import Session, select
from .models.user import User, Role, Permission, RolePermission
from .auth import get_password_hash
from .settings import get_settings


def create_initial_roles_and_permissions(engine):
    """Create initial roles, permissions, and superuser on first database setup"""
    with Session(engine) as session:
        # Check if roles already exist to avoid duplicate creation
        existing_roles = session.exec(select(Role)).first()
        if existing_roles:
            print("Database already initialized with roles and permissions.")
            return

        print("Initializing database with roles, permissions, and superuser...")

        # Define all permissions
        permissions_data = [
            # User permissions
            ("user.create", "Create users"),
            ("user.list", "List users"),
            ("user.update", "Update users"),
            ("user.delete", "Delete users"),
            ("user.superadmin", "Super admin access to all user operations"),

            # Organization permissions
            ("organization.create", "Create organizations"),
            ("organization.list", "List organizations"),
            ("organization.update", "Update organizations"),
            ("organization.delete", "Delete organizations"),
            ("organization.superadmin", "Super admin access to all organization operations"),

            # Team permissions
            ("team.create", "Create teams"),
            ("team.list", "List teams"),
            ("team.update", "Update teams"),
            ("team.delete", "Delete teams"),
            ("team.superadmin", "Super admin access to all team operations"),

            # Build permissions
            ("build.create", "Create builds"),
            ("build.list", "List builds"),
            ("build.update", "Update builds"),
            ("build.delete", "Delete builds"),
            ("build.download", "Download builds"),
            ("build.superadmin", "Super admin access to all build operations"),
        ]

        # Create permissions
        permissions = {}
        for perm_name, perm_desc in permissions_data:
            permission = Permission(name=perm_name, description=perm_desc)
            session.add(permission)
            permissions[perm_name] = permission

        session.commit()

        # Refresh permissions to get their IDs
        for perm in permissions.values():
            session.refresh(perm)

        # Define roles and their permissions
        roles_data = [
            ("superuser", "Super user with all permissions", [
                "user.superadmin", "organization.superadmin", "team.superadmin", "build.superadmin"
            ]),
            ("organization_admin", "Organization administrator", [
                "organization.superadmin", "team.superadmin", "build.superadmin"
            ]),
            ("team_admin", "Team administrator", [
                "team.superadmin", "build.superadmin"
            ]),
            ("user_admin", "User administrator", [
                "user.superadmin"
            ]),
            ("build_admin", "Build administrator", [
                "build.superadmin"
            ]),
            ("user", "Regular user with build management permissions", [
                "build.list", "build.create", "build.download", "build.delete", "build.update"
            ]),
        ]

        # Create roles and assign permissions
        roles = {}
        for role_name, role_desc, role_permissions in roles_data:
            role = Role(name=role_name, description=role_desc)
            session.add(role)
            session.commit()
            session.refresh(role)
            roles[role_name] = role

            # Assign permissions to role
            for perm_name in role_permissions:
                if perm_name in permissions:
                    role_permission = RolePermission(
                        role_id=role.id,
                        permission_id=permissions[perm_name].id
                    )
                    session.add(role_permission)

        session.commit()

        # Create superuser using settings
        settings = get_settings()
        superuser_username = settings.superuser_username
        superuser_password = settings.superuser_password

        # Check if superuser already exists
        existing_superuser = session.exec(
            select(User).where(User.username == superuser_username)
        ).first()

        if not existing_superuser:
            hashed_password = get_password_hash(superuser_password)
            superuser = User(
                username=superuser_username,
                email=f"{superuser_username}@system.local",
                hashed_password=hashed_password,
                full_name="System Superuser",
                is_active=True,
                role_id=roles["superuser"].id
            )
            session.add(superuser)
            session.commit()

            print(f"Created superuser: {superuser_username}")
            print(f"Superuser password: {superuser_password}")
            print("Please change the default password after first login!")
        else:
            print(f"Superuser {superuser_username} already exists.")

        print("Database initialization completed successfully!")
