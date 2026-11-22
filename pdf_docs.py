import os
from typing import List, Optional, Tuple
from aiogram.types import BufferedInputFile, FSInputFile, InputFile


def _ascii_safe(text: str) -> str:
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2192": "->",
        "\u2022": "*",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "ignore").decode("latin-1")


def _pdf_escape(text: str) -> str:
    clean = _ascii_safe(text)
    return clean.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_single_page_pdf(
    ops: List[str],
    uri_link: Optional[Tuple[float, float, float, float, str]] = None,
) -> bytes:
    """Build a crisp, zero-dependency A4 PDF 1.4 document with optional clickable URI link."""
    content_stream = "\n".join(ops).encode("latin-1")

    objects: List[bytes] = []
    # 1: Catalog
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    # 2: Pages
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    # 3: Page (A4: 595 x 842 pt)
    annot_ref = b" /Annots [7 0 R]" if uri_link else b""
    page_dict = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> "
        b"/Contents 6 0 R" + annot_ref + b" >>"
    )
    objects.append(page_dict)
    # 4: Helvetica Regular
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    # 5: Helvetica Bold
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    # 6: Content Stream
    stream_obj = (
        f"<< /Length {len(content_stream)} >>\nstream\n".encode("latin-1")
        + content_stream
        + b"\nendstream"
    )
    objects.append(stream_obj)

    if uri_link:
        x1, y1, x2, y2, url = uri_link
        safe_url = _pdf_escape(url)
        annot_obj = (
            f"<< /Type /Annot /Subtype /Link /Rect [{x1:.1f} {y1:.1f} {x2:.1f} {y2:.1f}] "
            f"/Border [0 0 0] /A << /S /URI /URI ({safe_url}) >> >>"
        ).encode("latin-1")
        objects.append(annot_obj)

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{idx} 0 obj\n".encode("latin-1"))
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("latin-1"))

    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "latin-1"
        )
    )
    return bytes(out)


def _text(x: float, y: float, size: float, txt: str, bold: bool = False, rgb: Tuple[float, float, float] = (0.06, 0.09, 0.16)) -> str:
    font = "/F2" if bold else "/F1"
    r, g, b = rgb
    return f"BT {font} {size:.1f} Tf {r:.2f} {g:.2f} {b:.2f} rg {x:.1f} {y:.1f} Td ({_pdf_escape(txt)}) Tj ET"


def _rect(x: float, y: float, w: float, h: float, fill_rgb: Tuple[float, float, float], stroke_rgb: Optional[Tuple[float, float, float]] = None) -> str:
    fr, fg, fb = fill_rgb
    if stroke_rgb:
        sr, sg, sb = stroke_rgb
        return f"{fr:.2f} {fg:.2f} {fb:.2f} rg {sr:.2f} {sg:.2f} {sb:.2f} RG 1.2 w {x:.1f} {y:.1f} {w:.1f} {h:.1f} re B"
    return f"{fr:.2f} {fg:.2f} {fb:.2f} rg {x:.1f} {y:.1f} {w:.1f} {h:.1f} re f"


def get_connect_guide_pdf() -> InputFile:
    custom_path = os.path.join("docs", "akkaunt_ulash.pdf")
    if os.path.exists(custom_path):
        return FSInputFile(custom_path, filename="Reels2Lead_Akkaunt_Ulash_Yoriqnomasi.pdf")

    ops: List[str] = []
    # Top header banner
    ops.append(_rect(42, 745, 511, 56, (0.06, 0.09, 0.16)))
    ops.append(_text(58, 779, 10, "REELS2LEAD CRM  |  RASMIY ULASH YO'RIQNOMASI", bold=True, rgb=(0.98, 0.45, 0.45)))
    ops.append(_text(58, 758, 15.5, "Instagram'ni Botga Ulash (3 Daqiqalik Qo'llanma)", bold=True, rgb=(1.0, 1.0, 1.0)))

    # Steps section
    ops.append(_text(42, 718, 12.5, "1. Qadam-baqadam bajarish tartibi:", bold=True, rgb=(0.06, 0.09, 0.16)))
    steps = [
        ("1-qadam. Instagram Professional rejim:", "Settings -> Account type and tools -> Switch to professional (Creator yoki Business)."),
        ("2-qadam. Facebook sahifa (Page) ochish:", "Facebook ilovasida Menu -> Pages -> Create tugmasi orqali yangi sahifa yarating."),
        ("3-qadam. Instagram'ni Page'ga ulash:", "Page -> Settings -> Linked accounts -> Instagram -> Connect account."),
        ("   Muhim ruxsat:", "'Allow access to Instagram messages in Inbox' tugmasini albatta YOQING (ON)."),
        ("4-qadam. Page Access bo'limiga kirish:", "Page -> Settings -> Page setup -> Page access (yoki Meta Business Suite -> People)."),
        ("5-qadam. Admin taklifini yuborish:", "People with full control -> Manage -> Add New -> participantpartic@gmail.com"),
        ("   Huquqni tasdiqlash:", "'Allow this person to also have full control' ni yoqib Give Access bosing."),
    ]
    y = 692
    for title, desc in steps:
        ops.append(_text(48, y, 10.2, title, bold=True, rgb=(0.06, 0.09, 0.16)))
        ops.append(_text(62, y - 15, 9.6, desc, bold=False, rgb=(0.25, 0.32, 0.42)))
        y -= 38

    # Summary Table Box
    ops.append(_rect(42, 345, 511, 68, (0.97, 0.98, 0.99), (0.80, 0.84, 0.90)))
    ops.append(_text(54, 394, 10.5, "TEZKOR TEKSHIRUV:", bold=True, rgb=(0.06, 0.09, 0.16)))
    ops.append(_text(54, 377, 9.6, "* IG rejimi: Creator yoki Business   |   * Inbox ruxsati: Allow access to IG messages (ON)", rgb=(0.15, 0.23, 0.35)))
    ops.append(_text(54, 360, 9.6, "* Taklif Gmail manzili: participantpartic@gmail.com  (Full control huquqi bilan)", bold=True, rgb=(0.72, 0.11, 0.11)))

    # URGENT RED BOX AT BOTTOM
    ops.append(_rect(42, 145, 511, 182, (0.99, 0.94, 0.94), (0.86, 0.15, 0.15)))
    ops.append(_rect(42, 145, 8, 182, (0.86, 0.15, 0.15)))
    ops.append(_text(62, 304, 11.5, "URGENT / MUHIM: TAKLIF YUBORGANDAN SO'NG ADMINGA YOZING!", bold=True, rgb=(0.72, 0.11, 0.11)))
    ops.append(_text(62, 284, 10, "Taklif yuborilganidan so'ng admin: @Yahyobek_U ga xabar yozishingiz shart.", bold=True, rgb=(0.50, 0.11, 0.11)))
    ops.append(_text(62, 267, 9.6, "Pastdagi tugmani bossangiz Telegram'da @Yahyobek_U oynasi tayyor shablon", rgb=(0.25, 0.10, 0.10)))
    ops.append(_text(62, 253, 9.6, "matni bilan avtomatik ochiladi - siz faqat JONATISH (Send) tugmasini bosing:", rgb=(0.25, 0.10, 0.10)))

    # Clickable Red CTA Button
    ops.append(_rect(62, 214, 330, 28, (0.86, 0.15, 0.15)))
    ops.append(_text(76, 224, 10.5, ">> ADMINGA TAYYOR XABAR YUBORISH: @Yahyobek_U", bold=True, rgb=(1.0, 1.0, 1.0)))

    ops.append(_text(62, 191, 9.8, "KEYINGI QADAM:", bold=True, rgb=(0.72, 0.11, 0.11)))
    ops.append(_text(62, 175, 9.5, "Admin sizga o'zi tayyor IG Business ID va Long-Lived Tokenni yuboradi.", rgb=(0.15, 0.15, 0.15)))
    ops.append(_text(62, 160, 9.5, "Siz ularni botdagi 'Instagram Ulash' bo'limiga kiritib ulanishni davom ettirasiz!", bold=True, rgb=(0.06, 0.09, 0.16)))

    # Footer
    ops.append(_text(42, 42, 8.5, "Reels2Lead CRM - Rasmiy Akkaunt Ulash Yo'riqnomasi", rgb=(0.45, 0.50, 0.58)))
    ops.append(_text(500, 42, 8.5, "Page 1 of 1", rgb=(0.45, 0.50, 0.58)))

    tg_url = (
        "https://t.me/Yahyobek_U?text=Assalomu%20alaykum!%20Reels2Lead%20CRM%20uchun%20"
        "Facebook%20sahifamga%20adminlik%20taklifini%20yubordim.%20Menga%20IG%20Business%20ID%20"
        "va%20Long-Lived%20Tokenni%20tayyorlab%20berasizmi%3F"
    )
    pdf_bytes = _build_single_page_pdf(ops, uri_link=(62, 214, 392, 242, tg_url))
    return BufferedInputFile(pdf_bytes, filename="Reels2Lead_Akkaunt_Ulash_Yoriqnomasi.pdf")


def get_user_guide_pdf() -> InputFile:
    custom_path = os.path.join("docs", "qollanma.pdf")
    if os.path.exists(custom_path):
        return FSInputFile(custom_path, filename="Reels2Lead_CRM_Qollanma.pdf")

    ops: List[str] = []
    # Top header
    ops.append(_rect(42, 745, 511, 56, (0.06, 0.46, 0.43)))
    ops.append(_text(58, 779, 10, "REELS2LEAD CRM  |  MIJOZLAR UCHUN QO'LLANMA", bold=True, rgb=(0.80, 0.98, 0.94)))
    ops.append(_text(58, 758, 15.5, "Instagram Reels Orqali Avtomatik Mijoz Yig'ish", bold=True, rgb=(1.0, 1.0, 1.0)))

    ops.append(_text(42, 718, 12.5, "1. Botdan foydalanishning 5 oddiy qadami:", bold=True, rgb=(0.06, 0.09, 0.16)))
    steps = [
        ("1-qadam. /start va Bonus tanlash:", "Biznes nomi va Gmail kiriting -> avtomatik Google Sheets CRM ochiladi. C+P (100 bonus DM) yoki C+P+L (15 bonus lid) tanlang."),
        ("2-qadam. Instagram sahifani ulash:", "Admin bergan IG Business ID va Long-Lived Tokenni 'Instagram Ulash' bo'limiga kiriting."),
        ("3-qadam. Reels videoni ulash:", "'Reels Ulash' -> 'Oxirgi Reels'lardan tanlash' orqali videoni tanlang yoki Reels link yuboring."),
        ("4-qadam. Skriptlar va Kalit so'zlar:", "C+P rejimida havolani, C+P+L da DM 1-xabar va DM 2-xabar (yoqish/o'chirish) ni sozlang. 'Kalit so'zlar' da + yoki barcha izohlarni belgilang."),
        ("5-qadam. Tayyor mijozlarni qabul qilish:", "Raqam qoldirgan mijozlar Telegram va Google Sheets'ga tushadi. Limit tugasa ham 'Zaxira Lidlar'da saqlanadi."),
    ]
    y = 692
    for title, desc in steps:
        ops.append(_text(48, y, 10.2, title, bold=True, rgb=(0.07, 0.37, 0.35)))
        # Wrap desc cleanly across two lines if long
        if len(desc) > 88:
            split_idx = desc.rfind(" ", 0, 88)
            line1 = desc[:split_idx]
            line2 = desc[split_idx + 1 :]
            ops.append(_text(58, y - 14, 9.4, line1, rgb=(0.20, 0.26, 0.34)))
            ops.append(_text(58, y - 27, 9.4, line2, rgb=(0.20, 0.26, 0.34)))
            y -= 48
        else:
            ops.append(_text(58, y - 14, 9.4, desc, rgb=(0.20, 0.26, 0.34)))
            y -= 38

    # Comparison Box
    ops.append(_rect(42, 260, 511, 165, (0.94, 0.99, 0.98), (0.06, 0.46, 0.43)))
    ops.append(_text(56, 404, 11.5, "2. Ikki Rejim Taqqoslamasi (O'zingizga mosini tanlang):", bold=True, rgb=(0.07, 0.37, 0.35)))
    ops.append(_text(56, 382, 10, "C+P REJIMI (Bloger va Kanallar uchun):", bold=True, rgb=(0.06, 0.09, 0.16)))
    ops.append(_text(66, 366, 9.5, "* Boshlang'ich bonus: 100 ta bonus DM kontakt", rgb=(0.20, 0.26, 0.34)))
    ops.append(_text(66, 351, 9.5, "* Vazifasi: Izohga javob yozish + Direct'ga tayyor havola (link) yuborish", rgb=(0.20, 0.26, 0.34)))

    ops.append(_text(56, 326, 10, "C+P+L REJIMI (Biznes va Sotuvlar uchun):", bold=True, rgb=(0.06, 0.09, 0.16)))
    ops.append(_text(66, 310, 9.5, "* Boshlang'ich bonus: 15 ta bonus tayyor telefon raqam", rgb=(0.20, 0.26, 0.34)))
    ops.append(_text(66, 295, 9.5, "* Vazifasi: 1 qadam (Faqat tel) yoki 2 qadam (Tel + Izoh) orqali raqam yig'ish", rgb=(0.20, 0.26, 0.34)))
    ops.append(_text(66, 280, 9.5, "* Avtomatik View-Only Google Sheets CRM + Zaxira Lidlar himoyasi", rgb=(0.20, 0.26, 0.34)))

    # Security Callout
    ops.append(_rect(42, 175, 511, 64, (0.96, 0.97, 0.99), (0.75, 0.80, 0.88)))
    ops.append(_text(56, 219, 10.2, "XAVFSIZLIK VA ANTI-BAN KAFOLATI:", bold=True, rgb=(0.06, 0.09, 0.16)))
    ops.append(_text(56, 202, 9.4, "Barcha javoblar rasmiy Meta Graph API hamda 10 soniyali Anti-Ban navbat orqali", rgb=(0.22, 0.28, 0.36)))
    ops.append(_text(56, 188, 9.4, "yuboriladi. Instagram parolingiz hech qachon so'ralmaydi va sahifangiz himoyalangan.", rgb=(0.22, 0.28, 0.36)))

    ops.append(_text(42, 42, 8.5, "Reels2Lead CRM - Mijozlar Uchun Qo'llanma", rgb=(0.45, 0.50, 0.58)))
    ops.append(_text(500, 42, 8.5, "Page 1 of 1", rgb=(0.45, 0.50, 0.58)))

    pdf_bytes = _build_single_page_pdf(ops)
    return BufferedInputFile(pdf_bytes, filename="Reels2Lead_CRM_Qollanma.pdf")