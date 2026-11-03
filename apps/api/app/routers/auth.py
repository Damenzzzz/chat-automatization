import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.auth.cookies import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_access_cookie,
    set_refresh_cookie,
)
from app.auth.deps import get_code_sender, get_otp, get_refresh_store
from app.auth.identity import IdentityIn
from app.auth.otp import (
    CodeExpiredError,
    OtpError,
    OtpService,
    TooManyAttemptsError,
    TooManyRequestsError,
    WrongCodeError,
)
from app.auth.senders import CodeSender, SenderUnavailableError
from app.auth.tokens import AccessClaims, RefreshStore, create_access_token
from app.auth.users import UserRef, find_user, load_user
from app.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

OTP_ERRORS: dict[type[OtpError], tuple[int, str]] = {
    TooManyRequestsError: (status.HTTP_429_TOO_MANY_REQUESTS, "too_many_requests"),
    TooManyAttemptsError: (status.HTTP_429_TOO_MANY_REQUESTS, "too_many_attempts"),
    CodeExpiredError: (status.HTTP_400_BAD_REQUEST, "code_expired"),
    WrongCodeError: (status.HTTP_400_BAD_REQUEST, "wrong_code"),
}


def _otp_http_error(exc: OtpError) -> HTTPException:
    code, detail = OTP_ERRORS[type(exc)]
    return HTTPException(code, detail)


class VerifyIn(IdentityIn):
    code: str = Field(pattern=r"^\d{6}$")


class SessionOut(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


async def _start_session(response: Response, user: UserRef, store: RefreshStore) -> SessionOut:
    settings = get_settings()
    access = create_access_token(AccessClaims(user.id, user.tenant_id, user.role), settings)
    refresh = await store.issue(user.id, user.tenant_id)
    set_access_cookie(response, access, settings)
    set_refresh_cookie(response, refresh, settings)
    return SessionOut(user_id=user.id, tenant_id=user.tenant_id, role=user.role)


@router.post("/request-code", status_code=status.HTTP_202_ACCEPTED)
async def request_code(
    body: IdentityIn,
    otp: Annotated[OtpService, Depends(get_otp)],
    sender: Annotated[CodeSender, Depends(get_code_sender)],
) -> dict[str, bool]:
    try:
        code = await otp.issue(body.identity)
    except OtpError as exc:
        raise _otp_http_error(exc) from exc
    try:
        await sender.send(body.identity, code)
    except SenderUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "channel_unavailable") from exc
    return {"sent": True}


@router.post("/verify")
async def verify(
    body: VerifyIn,
    response: Response,
    otp: Annotated[OtpService, Depends(get_otp)],
    store: Annotated[RefreshStore, Depends(get_refresh_store)],
) -> SessionOut:
    identity = body.identity
    user = await find_user(identity)
    try:
        await otp.verify(identity, body.code, consume=user is not None)
    except OtpError as exc:
        raise _otp_http_error(exc) from exc

    if user is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "signup_required")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user_disabled")
    return await _start_session(response, user, store)


@router.post("/refresh")
async def refresh(
    response: Response,
    store: Annotated[RefreshStore, Depends(get_refresh_store)],
    token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> SessionOut:
    session = await store.consume(token) if token else None
    user = await load_user(session.user_id, session.tenant_id) if session else None
    if user is None or not user.is_active:
        clear_auth_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_refresh")
    return await _start_session(response, user, store)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    store: Annotated[RefreshStore, Depends(get_refresh_store)],
    token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> None:
    if token:
        await store.revoke(token)
    clear_auth_cookies(response)
