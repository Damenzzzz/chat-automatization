from fastapi import Response

from app.core.config import Settings

ACCESS_COOKIE = "satushy_access"
REFRESH_COOKIE = "satushy_refresh"
REFRESH_PATH = "/auth"
SESSION_COOKIE = "satushy_session"


def set_access_cookie(response: Response, value: str, settings: Settings) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        value,
        max_age=settings.access_token_ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def set_refresh_cookie(response: Response, value: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        value,
        max_age=settings.refresh_token_ttl,
        path=REFRESH_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.set_cookie(
        SESSION_COOKIE,
        "1",
        max_age=settings.refresh_token_ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)
    response.delete_cookie(SESSION_COOKIE)
