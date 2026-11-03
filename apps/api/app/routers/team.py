import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.deps import Principal, TenantDb, require_role
from app.auth.identity import IdentityIn
from app.models import User

router = APIRouter(prefix="/team", tags=["team"])

Owner = Annotated[Principal, Depends(require_role("owner"))]
Member = Annotated[Principal, Depends(require_role("owner", "manager"))]


class InviteIn(IdentityIn):
    name: str | None = Field(default=None, max_length=200)
    role: Literal["manager"] = "manager"


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone: str | None
    email: str | None
    name: str | None
    role: str
    is_active: bool
    created_at: datetime


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite(body: InviteIn, principal: Owner, db: TenantDb) -> MemberOut:
    identity = body.identity
    user = User(
        tenant_id=principal.tenant_id,
        role=body.role,
        name=body.name,
        **{identity.kind: identity.value},
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_registered") from exc
    await db.refresh(user)
    return MemberOut.model_validate(user)


@router.get("")
async def list_team(principal: Member, db: TenantDb) -> list[MemberOut]:
    users = await db.scalars(select(User).order_by(User.created_at))
    return [MemberOut.model_validate(u) for u in users]


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove(user_id: uuid.UUID, principal: Owner, db: TenantDb) -> None:
    if user_id == principal.user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot_remove_self")
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    await db.delete(user)
