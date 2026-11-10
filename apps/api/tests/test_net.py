import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.core.config import Settings
from app.core.net import client_ip


def request(peer: str, forwarded: str | None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("8.8.8.8", "1.1.1.1", "8.8.8.8"),
        ("10.0.0.2", "6.6.6.6, 8.8.4.4, 10.0.0.9", "8.8.4.4"),
        ("127.0.0.1", None, "127.0.0.1"),
        ("10.0.0.2", "junk, 192.168.1.1", "10.0.0.2"),
    ],
)
def test_client_ip_ignores_spoofed_header(peer: str, forwarded: str | None, expected: str) -> None:
    assert client_ip(request(peer, forwarded)) == expected


def test_prod_rejects_example_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(env="prod", jwt_secret="dev-only-change-me-0000000000000000000000000000")
