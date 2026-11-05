from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.agent.prompt import money
from app.core.config import Settings

FONTS = Path(__file__).parent / "fonts"
SERVICE = "Пополнение баланса сервиса Satushy (ответы чат-бота)"


class RequisitesNotConfiguredError(Exception):
    pass


@dataclass(frozen=True)
class Seller:
    name: str
    iin: str
    iik: str
    bank: str
    bik: str
    kbe: str
    knp: str
    address: str | None
    vat_note: str


def seller_from(settings: Settings) -> Seller:
    required = {
        "name": settings.billing_seller_name,
        "iin": settings.billing_seller_iin,
        "iik": settings.billing_seller_iik,
        "bank": settings.billing_seller_bank,
        "bik": settings.billing_seller_bik,
    }
    if not all(required.values()):
        raise RequisitesNotConfiguredError
    return Seller(
        name=required["name"] or "",
        iin=required["iin"] or "",
        iik=required["iik"] or "",
        bank=required["bank"] or "",
        bik=required["bik"] or "",
        kbe=settings.billing_seller_kbe,
        knp=settings.billing_seller_knp,
        address=settings.billing_seller_address,
        vat_note=settings.billing_seller_vat_note,
    )


def render_invoice(
    *, number: str, issued: date, amount_kzt: int, buyer: str, seller: Seller
) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font("DejaVu", "", FONTS / "DejaVuSans.ttf")
    pdf.add_font("DejaVu", "B", FONTS / "DejaVuSans-Bold.ttf")
    pdf.set_title(f"Счёт на оплату № {number}")
    pdf.add_page()

    pdf.set_font("DejaVu", "B", 10)
    pdf.cell(text="Образец платёжного поручения", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.set_font("DejaVu", "", 9)
    with pdf.table(
        col_widths=(60, 80, 50), first_row_as_headings=False, text_align="LEFT"
    ) as table:
        row = table.row()
        row.cell(f"Бенефициар:\n{seller.name}\nИИН/БИН: {seller.iin}")
        row.cell(f"ИИК\n{seller.iik}")
        row.cell(f"Кбе\n{seller.kbe}")
        row = table.row()
        row.cell(f"Банк бенефициара:\n{seller.bank}")
        row.cell(f"БИК\n{seller.bik}")
        row.cell(f"Код назначения платежа\n{seller.knp}")

    pdf.ln(8)
    pdf.set_font("DejaVu", "B", 14)
    title = f"Счёт на оплату № {number} от {issued:%d.%m.%Y}"
    pdf.multi_cell(0, 8, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    pdf.set_font("DejaVu", "", 10)
    supplier = f"Поставщик: {seller.name}, ИИН/БИН {seller.iin}"
    if seller.address:
        supplier += f", {seller.address}"
    pdf.multi_cell(0, 6, supplier, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.multi_cell(0, 6, f"Покупатель: {buyer}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    with pdf.table(col_widths=(8, 82, 20, 14, 33, 33), text_align="LEFT") as table:
        header = table.row()
        for label in ("№", "Наименование", "Кол-во", "Ед.", "Цена", "Сумма"):
            header.cell(label)
        row = table.row()
        for value in ("1", SERVICE, "1", "усл.", money(amount_kzt), money(amount_kzt)):
            row.cell(value)

    pdf.ln(4)
    pdf.set_font("DejaVu", "B", 11)
    total = f"Итого к оплате: {money(amount_kzt)}"
    pdf.cell(0, 7, total, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DejaVu", "", 10)
    pdf.cell(0, 6, seller.vat_note, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(6)
    pdf.set_font("DejaVu", "", 9)
    pdf.multi_cell(
        0,
        5,
        align="L",
        text=f"В назначении платежа укажите номер счёта {number}. "
        "Баланс пополняется после подтверждения оплаты.",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    return bytes(pdf.output())
