import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx

SHEET_ID = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]{20,})")


class SheetError(Exception):
    pass


@dataclass(frozen=True)
class SheetRef:
    sheet_id: str
    gid: str

    @property
    def export_url(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/export?format=csv&gid={self.gid}"


def parse_sheet_url(url: str) -> SheetRef:
    parsed = urlparse(url.strip())
    if parsed.hostname != "docs.google.com":
        raise SheetError("not_google_sheet")
    match = SHEET_ID.search(parsed.path)
    if match is None:
        raise SheetError("not_google_sheet")
    gid = (
        parse_qs(parsed.query).get("gid", [None])[0]
        or parse_qs(parsed.fragment).get("gid", ["0"])[0]
    )
    if not gid.isdigit():
        raise SheetError("bad_gid")
    return SheetRef(match.group(1), gid)


async def download_csv(client: httpx.AsyncClient, ref: SheetRef, limit: int) -> bytes:
    data = bytearray()
    async with client.stream("GET", ref.export_url, follow_redirects=True) as response:
        content_type = response.headers.get("content-type", "")
        if response.status_code != 200 or "text/csv" not in content_type:
            raise SheetError("sheet_not_public")
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > limit:
                raise SheetError("file_too_large")
    return bytes(data)
