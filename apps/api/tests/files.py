import csv
import io
from collections.abc import Sequence
from typing import Any

from openpyxl import Workbook

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def xlsx_bytes(rows: Sequence[Sequence[Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def csv_bytes(
    rows: Sequence[Sequence[Any]], delimiter: str = ",", encoding: str = "utf-8"
) -> bytes:
    buf = io.StringIO()
    csv.writer(buf, delimiter=delimiter).writerows(rows)
    return buf.getvalue().encode(encoding)


DIRTY_CATALOG: list[list[Any]] = [
    ["Артикул", "Наименование", "Цена, тг", "Остаток", "Категория", "Описание", "Фото", "Цвет"],
    [
        "PN-001",
        "Букет из 15 пионов",
        "32 000 тг",
        "6",
        "Пионы",
        "<p>Розовые <b>пионы</b></p>",
        "https://img/1.jpg",
        "розовый",
    ],
    [
        "pn 002",
        "Букет из 25 белых пионов",
        "52 000,00 ₸",
        "3 шт",
        "Пионы",
        "Белые пионы",
        "",
        "белый",
    ],
    [None, None, None, None, None, None, None, None],
    [
        "RS-101",
        "25 красных роз",
        24000,
        12,
        "Розы",
        "Розы Freedom 60 см",
        "https://img/2.jpg; https://img/3.jpg",
        "красный",
    ],
    ["PN-001", "Дубль пионов", "1000", "1", "Пионы", "дубль", "", ""],
    ["TL-201", "Тюльпаны 25 шт", "договорная", "20", "Тюльпаны", "", "", "микс"],
    [None, "Открытка", "1 500", "нет", "Дополнения", "", "", ""],
    ["GF-602", "", "5000", "15", "Дополнения", "", "", ""],
    ["CH-401", "Ромашки 15 шт", "8 000.50", "-2", "Полевые", "", "", ""],
]
