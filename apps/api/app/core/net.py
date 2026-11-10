import ipaddress

from fastapi import Request


def _public(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if _public(peer):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    for part in reversed(forwarded.split(",")):
        if _public(part.strip()):
            return part.strip()
    return peer
