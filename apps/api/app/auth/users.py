import uuid
from dataclasses import dataclass

from sqlalchemy import select, text

from app.auth.identity import Identity
from app.db.session import get_sessionmaker, tenant_session
from app.models import Tenant, User


@dataclass(frozen=True)
class UserRef:
    id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    is_active: bool
    suspended: bool = False


async def find_user(identity: Identity) -> UserRef | None:
    phone = identity.value if identity.kind == "phone" else None
    email = identity.value if identity.kind == "email" else None
    async with get_sessionmaker()() as session:
        row = (
            await session.execute(
                text("SELECT * FROM auth_find_user(:phone, :email)"),
                {"phone": phone, "email": email},
            )
        ).first()
    return UserRef(row.id, row.tenant_id, row.role, row.is_active) if row else None


async def load_user(user_id: uuid.UUID, tenant_id: uuid.UUID) -> UserRef | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                select(User, Tenant.status)
                .join(Tenant, Tenant.id == User.tenant_id)
                .where(User.id == user_id)
            )
        ).first()
    if row is None:
        return None
    user, status = row
    return UserRef(user.id, user.tenant_id, user.role, user.is_active, status == "suspended")


async def create_owner(
    identity: Identity, *, name: str, city: str | None, niche: str | None
) -> UserRef:
    tenant_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name=name, city=city, niche=niche))
        await session.flush()
        user = User(tenant_id=tenant_id, role="owner", **{identity.kind: identity.value})
        session.add(user)
        await session.flush()
        return UserRef(user.id, tenant_id, user.role, True)
