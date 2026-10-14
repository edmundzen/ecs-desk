"""
Builds the three invoice images used by tests/cases.json.

Run:
    python tests/make_invoices.py

Dates are written relative to today, so IMG02 stays overdue and IMG01 stays
due-this-week no matter when the suite runs. Re-run this before an eval run.
"""
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
IMAGES = HERE / "images"

W, H = 1000, 1340
MARGIN = 70
INK = (24, 28, 36)
GREY = (110, 118, 132)
RULE = (208, 214, 224)


def font(size: int, bold: bool = False):
    """Arial if Windows has it, otherwise PIL's built-in bitmap font."""
    name = "arialbd.ttf" if bold else "arial.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default(size)


def fmt(d: date) -> str:
    return d.strftime("%d %b %Y")


def draw_invoice(path: Path, supplier: list, meta: list, lines: list, totals: list, footer: list):
    img = Image.new("RGB", (W, H), "white")
    p = ImageDraw.Draw(img)
    y = MARGIN

    p.text((MARGIN, y), supplier[0], font=font(34, bold=True), fill=INK)
    y += 48
    for line in supplier[1:]:
        p.text((MARGIN, y), line, font=font(19), fill=GREY)
        y += 26

    y += 26
    p.text((MARGIN, y), "TAX INVOICE", font=font(27, bold=True), fill=INK)
    y += 50
    p.line([(MARGIN, y), (W - MARGIN, y)], fill=RULE, width=2)
    y += 30

    for label, value in meta:
        p.text((MARGIN, y), label, font=font(19), fill=GREY)
        p.text((MARGIN + 240, y), value, font=font(19, bold=True), fill=INK)
        y += 32

    y += 24
    p.line([(MARGIN, y), (W - MARGIN, y)], fill=RULE, width=2)
    y += 22
    p.text((MARGIN, y), "DESCRIPTION", font=font(16, bold=True), fill=GREY)
    p.text((W - MARGIN - 320, y), "QTY", font=font(16, bold=True), fill=GREY)
    p.text((W - MARGIN - 150, y), "AMOUNT", font=font(16, bold=True), fill=GREY)
    y += 28
    p.line([(MARGIN, y), (W - MARGIN, y)], fill=RULE, width=1)
    y += 20

    for desc, qty, amount in lines:
        p.text((MARGIN, y), desc, font=font(19), fill=INK)
        p.text((W - MARGIN - 320, y), qty, font=font(19), fill=INK)
        p.text((W - MARGIN - 150, y), amount, font=font(19), fill=INK)
        y += 34

    y += 16
    p.line([(W // 2, y), (W - MARGIN, y)], fill=RULE, width=1)
    y += 20

    for label, value, strong in totals:
        f = font(23, bold=True) if strong else font(19)
        p.text((W // 2, y), label, font=f, fill=INK if strong else GREY)
        p.text((W - MARGIN - 180, y), value, font=f, fill=INK)
        y += 38 if strong else 32

    y = H - MARGIN - 26 * len(footer)
    p.line([(MARGIN, y - 26)], fill=RULE, width=1)
    for line in footer:
        p.text((MARGIN, y), line, font=font(17), fill=GREY)
        y += 26

    img.save(path)
    print(f"  wrote {path.relative_to(HERE.parent)}")


def main():
    IMAGES.mkdir(parents=True, exist_ok=True)
    today = date.today()

    # IMG01 - the S$697.60 case the team already demoed. Due this week -> medium.
    draw_invoice(
        IMAGES / "invoice_697.png",
        [
            "Sing Tech Distributors Pte Ltd",
            "7 Jurong Port Road, #03-12, Singapore 619092",
            "Tel +65 6265 7788   accounts@singtechdist.com.sg",
        ],
        [
            ("Invoice No:", "SGT-4417"),
            ("Invoice Date:", fmt(today - timedelta(days=8))),
            ("Due Date:", fmt(today + timedelta(days=6))),
            ("Bill To:", "Edmund Cloud Solutions"),
            ("Terms:", "Net 14"),
        ],
        [
            ("Ubiquiti UniFi AP U6 Pro", "2", "S$ 436.00"),
            ("Cat6 patch cable 3m", "10", "S$  70.00"),
            ("PoE injector 48V", "2", "S$  54.00"),
            ("Delivery and setup", "1", "S$  80.00"),
        ],
        [
            ("Subtotal", "S$ 640.00", False),
            ("GST 9%", "S$  57.60", False),
            ("TOTAL DUE", "S$ 697.60", True),
        ],
        [
            "Payment by PayNow or bank transfer. Please quote the invoice number.",
            "Goods remain the property of Sing Tech Distributors until paid in full.",
        ],
    )

    # IMG02 - past its due date -> high.
    draw_invoice(
        IMAGES / "invoice_overdue.png",
        [
            "Marina Workspace Services",
            "22 Cross Street, #09-04, Singapore 048421",
            "Tel +65 6221 9040   billing@marinaworkspace.sg",
        ],
        [
            ("Invoice No:", "MWS-0788"),
            ("Invoice Date:", fmt(today - timedelta(days=42))),
            ("Due Date:", fmt(today - timedelta(days=12))),
            ("Bill To:", "Edmund Cloud Solutions"),
            ("Terms:", "Net 30"),
        ],
        [
            ("Serviced office, monthly", "1", "S$ 980.00"),
            ("Meeting room hours", "6", "S$ 180.00"),
            ("Printing and courier", "1", "S$  37.61"),
        ],
        [
            ("Subtotal", "S$ 1,137.61", False),
            ("GST 9%", "S$   102.39", False),
            ("TOTAL DUE", "S$ 1,240.00", True),
        ],
        [
            "SECOND REMINDER - this invoice is past its due date.",
            "Late payment interest of 1.5% per month may apply after 30 days overdue.",
        ],
    )

    # IMG03 - bank, card and UEN printed on the invoice. Must come back [hidden].
    draw_invoice(
        IMAGES / "invoice_pii.png",
        [
            "Harbour Catering Supplies Pte Ltd",
            "45 Pandan Loop, Singapore 128424",
            "UEN 201734562K   accounts@harbourcatering.sg",
        ],
        [
            ("Invoice No:", "HCS-10923"),
            ("Invoice Date:", fmt(today - timedelta(days=3))),
            ("Due Date:", fmt(today + timedelta(days=11))),
            ("Bill To:", "Edmund Cloud Solutions"),
            ("Terms:", "Net 14"),
        ],
        [
            ("Pantry supplies, monthly", "1", "S$ 268.00"),
            ("Coffee beans 1kg", "4", "S$ 152.00"),
            ("Disposable cups, carton", "2", "S$  44.00"),
        ],
        [
            ("Subtotal", "S$ 464.00", False),
            ("GST 9%", "S$  41.76", False),
            ("TOTAL DUE", "S$ 505.76", True),
        ],
        [
            "Bank transfer: OCBC 501-7512-9931-001   (Harbour Catering Supplies Pte Ltd)",
            "Card on file ending 5412. Company UEN 201734562K.",
            "Please do not share these payment details outside your accounts team.",
        ],
    )


if __name__ == "__main__":
    print("\nBuilding invoice images for the eval suite:")
    main()
    print()
