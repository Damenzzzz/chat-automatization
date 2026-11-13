import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import Principal, TenantDb, require_role
from app.models import BotProfile
from app.niches import NICHES, Niche, find_niche, preset_values

router = APIRouter(prefix="/bot-profile", tags=["bot-profile"])

Member = Annotated[Principal, Depends(require_role("owner", "manager"))]
EDITABLE = ("tone", "greeting", "rules", "languages", "model_policy")


class ProfileIn(BaseModel):
    tone: str | None = Field(None, max_length=2000)
    greeting: str | None = Field(None, max_length=2000)
    rules: dict[str, Any] = Field(default_factory=dict)
    languages: list[str] = Field(default_factory=lambda: ["ru", "kk"], min_length=1)
    model_policy: dict[str, Any] = Field(default_factory=dict)


class ProfileOut(ProfileIn):
    version: int
    is_active: bool
    based_on: int | None
    created_by: uuid.UUID | None
    created_at: datetime


class RollbackIn(BaseModel):
    version: int | None = None


class PresetIn(BaseModel):
    niche: str = Field(min_length=1, max_length=100)


class NicheOut(BaseModel):
    key: str
    title: str
    hint: str
    tone: str
    greeting: str
    rules: dict[str, Any]


def niche_out(niche: Niche) -> NicheOut:
    return NicheOut(
        key=niche.key,
        title=niche.title,
        hint=niche.hint,
        tone=niche.tone,
        greeting=niche.greeting,
        rules=niche.rules(),
    )


def _out(profile: BotProfile) -> ProfileOut:
    return ProfileOut(
        version=profile.version,
        is_active=profile.is_active,
        based_on=profile.based_on,
        created_by=profile.created_by,
        created_at=profile.created_at,
        **{name: getattr(profile, name) for name in EDITABLE},
    )


async def _active(session: AsyncSession) -> BotProfile | None:
    return await session.scalar(select(BotProfile).where(BotProfile.is_active))


async def _new_version(
    session: AsyncSession,
    principal: Principal,
    values: dict[str, Any],
    based_on: int | None,
) -> BotProfile:
    last = await session.scalar(select(func.max(BotProfile.version))) or 0
    await session.execute(update(BotProfile).where(BotProfile.is_active).values(is_active=False))
    profile = BotProfile(
        tenant_id=principal.tenant_id,
        version=last + 1,
        is_active=True,
        based_on=based_on,
        created_by=principal.actor_id or principal.user_id,
        **values,
    )
    session.add(profile)
    await session.flush()
    await session.refresh(profile)
    return profile


@router.get("")
async def get_profile(principal: Member, session: TenantDb) -> ProfileOut:
    profile = await _active(session)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "bot_profile_not_found")
    return _out(profile)


@router.get("/versions")
async def list_versions(principal: Member, session: TenantDb) -> list[ProfileOut]:
    rows = await session.scalars(select(BotProfile).order_by(BotProfile.version.desc()))
    return [_out(p) for p in rows]


@router.put("")
async def save_profile(body: ProfileIn, principal: Member, session: TenantDb) -> ProfileOut:
    current = await _active(session)
    profile = await _new_version(
        session, principal, body.model_dump(), current.version if current else None
    )
    return _out(profile)


@router.post("/preset")
async def apply_preset(body: PresetIn, principal: Member, session: TenantDb) -> ProfileOut:
    niche = find_niche(body.niche)
    if niche is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "niche_not_found")
    current = await _active(session)
    values = {
        "languages": current.languages if current else ["ru", "kk"],
        "model_policy": current.model_policy if current else {},
        **preset_values(niche, current.rules if current else None),
    }
    profile = await _new_version(session, principal, values, current.version if current else None)
    return _out(profile)


@router.post("/rollback")
async def rollback(
    principal: Member, session: TenantDb, body: RollbackIn | None = None
) -> ProfileOut:
    current = await _active(session)
    target_version = body.version if body and body.version else None
    if target_version is None:
        if current is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "no_previous_version")
        target_version = await session.scalar(
            select(func.max(BotProfile.version)).where(BotProfile.version < current.version)
        )
    target = (
        await session.scalar(select(BotProfile).where(BotProfile.version == target_version))
        if target_version
        else None
    )
    if target is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no_previous_version")
    values = {name: getattr(target, name) for name in EDITABLE}
    return _out(await _new_version(session, principal, values, target.version))


niches_router = APIRouter(tags=["bot-profile"])


@niches_router.get("/niches")
async def list_niches() -> list[NicheOut]:
    return [niche_out(niche) for niche in NICHES]
