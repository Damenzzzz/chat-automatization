import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from openpyxl import load_workbook

Row = list[Any]


class FileFormatError(Exception):
    pass


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise FileFormatError("unknown_encoding")


def _csv_rows(data: bytes) -> tuple[Iterator[Row], int]:
    text = _decode(data)
    try:
        dialect: Any = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return csv.reader(io.StringIO(text), dialect), text.count("\n") + 1


def _xlsx_rows(data: bytes) -> tuple[Iterator[Row], int | None]:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise FileFormatError("bad_xlsx") from exc
    ws = wb.worksheets[0]

    def rows() -> Iterator[Row]:
        try:
            for row in ws.iter_rows(values_only=True):
                yield list(row)
        finally:
            wb.close()

    return rows(), ws.max_row


def is_empty(row: Row) -> bool:
    return all(v is None or (isinstance(v, str) and not v.strip()) for v in row)


def unique_headers(raw: Row) -> list[str]:
    seen: dict[str, int] = {}
    headers = []
    for i, cell in enumerate(raw):
        name = str(cell).strip() if cell is not None and str(cell).strip() else f"Колонка {i + 1}"
        seen[name] = seen.get(name, 0) + 1
        headers.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return headers


@dataclass
class Table:
    headers: list[str]
    header_row: int
    rows: Iterator[tuple[int, Row]]
    total_rows: int | None = None


def _pad(rows: Iterator[tuple[int, Row]], width: int) -> Iterator[tuple[int, Row]]:
    for number, row in rows:
        yield number, (list(row) + [None] * width)[:width]


def open_table(data: bytes, file_type: str) -> Table:
    source, max_row = _xlsx_rows(data) if file_type == "xlsx" else _csv_rows(data)
    numbered = enumerate(source, start=1)
    for number, row in numbered:
        if not is_empty(row):
            headers = unique_headers(row)
            total = max(max_row - number, 0) if max_row else None
            return Table(headers, number, _pad(numbered, len(headers)), total)
    raise FileFormatError("no_header")


def preview(data: bytes, file_type: str, limit: int = 5) -> tuple[list[str], list[Row]]:
    table = open_table(data, file_type)
    sample: list[Row] = []
    for _, row in table.rows:
        if is_empty(row):
            continue
        sample.append(row)
        if len(sample) >= limit:
            break
    return table.headers, sample
