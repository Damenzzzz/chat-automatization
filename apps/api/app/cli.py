import argparse
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.auth.identity import IdentityIn
from app.db.session import tenant_session
from app.models import Tenant, User

SATUSHY_TENANT_ID = uuid.UUID("5a705e00-0000-4000-8000-000000000001")


async def create_admin(identity_in: IdentityIn, name: str | None = None) -> uuid.UUID:
    identity = identity_in.identity
    async with tenant_session(SATUSHY_TENANT_ID) as session:
        await session.execute(
            insert(Tenant)
            .values(id=SATUSHY_TENANT_ID, name="Satushy", status="active", plan="internal")
            .on_conflict_do_nothing(index_elements=[Tenant.id])
        )
        column = getattr(User, identity.kind)
        user = await session.scalar(select(User).where(column == identity.value))
        if user is None:
            user = User(tenant_id=SATUSHY_TENANT_ID, role="admin", name=name)
            setattr(user, identity.kind, identity.value)
            session.add(user)
            await session.flush()
        return user.id


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="создать админа Satushy")
    group = admin.add_mutually_exclusive_group(required=True)
    group.add_argument("--phone")
    group.add_argument("--email")
    admin.add_argument("--name")
    args = parser.parse_args()

    if args.command == "create-admin":
        user_id = asyncio.run(
            create_admin(IdentityIn(phone=args.phone, email=args.email), args.name)
        )
        print(user_id)


if __name__ == "__main__":
    main()
