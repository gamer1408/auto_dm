import os
from typing import List, Optional, Tuple
from aiogram.types import BufferedInputFile, FSInputFile, InputFile


def _ascii_safe(text: str) -> str:
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00ab": '"',
        "\u00bb": '"',
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


def _build_multi_page_pdf(
    pages_ops: List[List[str]],
    page_links: Optional[List[Optional[Tuple[float, float, float, float, str]]]] = None,
) -> bytes:
    """Build a multi-page A4 PDF 1.4 document with optional clickable URI links per page."""
    num_pages = len(pages_ops)
    # Object numbering:
    # 1: Catalog
    # 2: Pages
    # 3: Helvetica Regular
    # 4: Helvetica Bold
    # Then for each page i (0..num_pages-1):
    #   page_obj_id = 5 + i*3
    #   stream_obj_id = 5 + i*3 + 1
    #   annot_obj_id = 5 + i*3 + 2 (if link exists)
    objects: List[Tuple[int, bytes]] = []

    page_ids = [5 + i * 3 for i in range(num_pages)]
    kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append((1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    objects.append((2, f"<< /Type /Pages /Kids [{kids_str}] /Count {num_pages} >>".encode("latin-1")))
    objects.append((3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))
    objects.append((4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"))

    for i, ops in enumerate(pages_ops):
        page_id = 5 + i * 3
        stream_id = page_id + 1
        annot_id = page_id + 2
        link = page_links[i] if (page_links and i < len(page_links)) else None

        annot_part = f" /Annots [{annot_id} 0 R]".encode("latin-1") if link else b""
        page_dict = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            f"/Contents {stream_id} 0 R".encode("latin-1")
            + annot_part
            + b" >>"
        )
        objects.append((page_id, page_dict))

        content_stream = "\n".join(ops).encode("latin-1")
        stream_obj = (
            f"<< /Length {len(content_stream)} >>\nstream\n".encode("latin-1")
            + content_stream
            + b"\nendstream"
        )
        objects.append((stream_id, stream_obj))

        if link:
            x1, y1, x2, y2, url = link
            safe_url = _pdf_escape(url)
            annot_obj = (
                f"<< /Type /Annot /Subtype /Link /Rect [{x1:.1f} {y1:.1f} {x2:.1f} {y2:.1f}] "
                f"/Border [0 0 0] /A << /S /URI /URI ({safe_url}) >> >>"
            ).encode("latin-1")
            objects.append((annot_id, annot_obj))

    objects.sort(key=lambda item: item[0])
    max_obj_id = objects[-1][0]

    out = bytearray(b"%PDF-1.4\n")
    offsets = {0: 0}
    for obj_id, body in objects:
        offsets[obj_id] = len(out)
        out.extend(f"{obj_id} 0 obj\n".encode("latin-1"))
        out.extend(body)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {max_obj_id + 1}\n".encode("latin-1"))
    out.extend(b"0000000000 65535 f \n")
    for oid in range(1, max_obj_id + 1):
        if oid in offsets:
            out.extend(f"{offsets[oid]:010d} 00000 n \n".encode("latin-1"))
        else:
            out.extend(b"0000000000 65535 f \n")

    out.extend(
        f"trailer\n<< /Size {max_obj_id + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "latin-1"
        )
    )
    return bytes(out)


def _text(
    x: float,
    y: float,
    size: float,
    txt: str,
    bold: bool = False,
    rgb: Tuple[float, float, float] = (0.06, 0.09, 0.16),
) -> str:
    font = "/F2" if bold else "/F1"
    r, g, b = rgb
    return f"BT {font} {size:.1f} Tf {r:.2f} {g:.2f} {b:.2f} rg {x:.1f} {y:.1f} Td ({_pdf_escape(txt)}) Tj ET"


def _rect(
    x: float,
    y: float,
    w: float,
    h: float,
    fill_rgb: Tuple[float, float, float],
    stroke_rgb: Optional[Tuple[float, float, float]] = None,
) -> str:
    fr, fg, fb = fill_rgb
    if stroke_rgb:
        sr, sg, sb = stroke_rgb
        return f"{fr:.2f} {fg:.2f} {fb:.2f} rg {sr:.2f} {sg:.2f} {sb:.2f} RG 1.0 w {x:.1f} {y:.1f} {w:.1f} {h:.1f} re B"
    return f"{fr:.2f} {fg:.2f} {fb:.2f} rg {x:.1f} {y:.1f} {w:.1f} {h:.1f} re f"


def get_connect_guide_pdf() -> InputFile:
    custom_path = os.path.join("docs", "akkaunt_ulash.pdf")
    if os.path.exists(custom_path):
        return FSInputFile(custom_path, filename="Reels2Lead_Akkaunt_Ulash_Yoriqnomasi.pdf")

    # ================= PAGE 1 =================
    p1: List[str] = []
    p1.append(_rect(42, 748, 511, 56, (0.06, 0.09, 0.16)))
    p1.append(_text(58, 783, 9.8, "REELS2LEAD CRM  |  RASMIY AKKAUNT ULASH YO'RIQNOMASI", bold=True, rgb=(0.98, 0.45, 0.45)))
    p1.append(_text(58, 761, 14.5, "Instagram'ni Botga Ulash (3 Daqiqalik Batafsil Qo'llanma)", bold=True, rgb=(1.0, 1.0, 1.0)))
    p1.append(_text(42, 728, 9.5, "Parol bermasdan, rasmiy Meta Graph API v21.0 ruxsati orqali sahifangizni xavfsiz ulash ketma-ketligi", rgb=(0.28, 0.34, 0.44)))

    # 6-Step Visual Flow Diagram
    flow_boxes = [
        ("1. IG Pro", "Creator / Biz"),
        ("2. FB Page", "Yangi sahifa"),
        ("3. IG Ulash", "Inbox ON"),
        ("4. Access", "Page Setup"),
        ("5. Taklif", "Full control"),
        ("6. ID/Token", "Admin beradi"),
    ]
    bx = 42.0
    for idx, (top_lbl, sub_lbl) in enumerate(flow_boxes):
        is_last = idx == len(flow_boxes) - 1
        bg = (0.99, 0.94, 0.94) if is_last else (0.96, 0.97, 0.99)
        bd = (0.86, 0.15, 0.15) if is_last else (0.75, 0.80, 0.88)
        tc = (0.72, 0.11, 0.11) if is_last else (0.06, 0.09, 0.16)
        p1.append(_rect(bx, 668, 76, 44, bg, bd))
        p1.append(_text(bx + 8, 694, 8.8, top_lbl, bold=True, rgb=tc))
        p1.append(_text(bx + 8, 679, 8.0, sub_lbl, rgb=(0.30, 0.36, 0.46)))
        if not is_last:
            p1.append(_text(bx + 78.5, 686, 9.0, "->", bold=True, rgb=(0.86, 0.15, 0.15)))
        bx += 87.0

    p1.append(_text(42, 638, 11.5, "1. Har bir qadamni bajarish bo'yicha batafsil yo'riqnoma:", bold=True, rgb=(0.06, 0.09, 0.16)))

    detailed_steps = [
        (
            "1-qadam. Instagram'ni Professional akkauntga o'tkazing (Shaxsiy profil bo'lsa)",
            [
                "Instagram ilovasida: Profil -> Menyular (3 chiziq) -> Settings and privacy -> Account type and tools.",
                "'Switch to professional account' ni bosing va sahifangizga mos 'Business' yoki 'Creator' turini tanlang.",
            ],
            False,
        ),
        (
            "2-qadam. Facebook'da sahifa (Page) oching (Agar tayyor sahifangiz bo'lmasa)",
            [
                "Meta API faqat Facebook Page orqali ishlaydi. Facebook ilovasiga kiring -> Menu -> Pages -> Create.",
                "Brendingiz yoki blogingiz nomini yozib, istalgan kategoriya bilan yangi Facebook Page yarating.",
            ],
            False,
        ),
        (
            "3-qadam. Instagram sahifangizni shu Facebook Page'ga ulang (ENG MUHIM QADAM)",
            [
                "Facebook sahifangizga kiring -> Settings -> Linked accounts -> Instagram -> Connect account.",
                "DIQQAT: Oynada 'Allow access to Instagram messages in Inbox' tugmasini albatta YOQING (ON)!",
                "Agar bu ruxsat yoqilmasa, bot izohlarga javob beradi lekin Direct (DM) xabar yubora olmaydi.",
            ],
            True,
        ),
        (
            "4-qadam. Facebook Page ichida 'Page Access' bo'limini oching",
            [
                "Facebook sahifangiz ichida: Settings & privacy -> Settings -> menyudan Page setup -> Page access.",
                "(Agar 'Go to Meta Business Suite' tugmasi chiqsa, o'sha yerga o'tib Settings -> People bo'limini oching).",
            ],
            False,
        ),
        (
            "5-qadam. Texnik Gmail manzilga 'Full control' adminlik taklifini yuboring",
            [
                "'People with full control' qatoridagi Manage -> Add New tugmasini bosing.",
                "Qidiruvga participantpartic@gmail.com manzilini yozib profilni tanlang.",
                "Pastdagi 'Allow this person to also have full control' tugmasini yoqing, Give Access bosing va FB parolni kiriting.",
            ],
            True,
        ),
        (
            "6-qadam. Adminga xabar bering va ID + Token olib botga kiriting",
            [
                "Taklif yuborilgach, 2-sahifadagi qizil tugma orqali @Yahyobek_U ga IG sahifangizni yozib yuboring.",
                "Admin 2-5 daqiqada sizga IG Business ID va Long-Lived Tokenni beradi. Ularni 'Instagram Ulash'ga kiriting.",
            ],
            False,
        ),
    ]

    y = 612.0
    for title, lines, highlight in detailed_steps:
        p1.append(_text(46, y, 10.0, title, bold=True, rgb=(0.06, 0.09, 0.16)))
        y -= 14.5
        for idx, line in enumerate(lines):
            is_emph = highlight and idx == 1
            color = (0.72, 0.11, 0.11) if is_emph else (0.24, 0.30, 0.40)
            p1.append(_text(58, y, 9.1, line, bold=is_emph, rgb=color))
            y -= 13.5
        y -= 9.0

    # Security reassurance box at bottom of Page 1
    p1.append(_rect(42, 82, 511, 58, (0.95, 0.98, 0.97), (0.06, 0.46, 0.43)))
    p1.append(_text(56, 122, 9.8, "NIMA UCHUN INSTAGRAM PAROLINGIZ SO'RALMAYDI?", bold=True, rgb=(0.06, 0.38, 0.35)))
    p1.append(_text(56, 107, 9.0, "Reels2Lead rasmiy Meta Graph API v21.0 orqali ishlaydi. Siz Instagram parolingizni hech kimga bermaysiz", rgb=(0.18, 0.25, 0.32)))
    p1.append(_text(56, 93, 9.0, "va istalgan vaqtda Facebook Page Access bo'limidan ruxsatni o'zingiz o'chirib qo'yishingiz mumkin.", rgb=(0.18, 0.25, 0.32)))

    p1.append(_text(42, 42, 8.5, "Reels2Lead CRM - Rasmiy Akkaunt Ulash Yo'riqnomasi", rgb=(0.45, 0.50, 0.58)))
    p1.append(_text(500, 42, 8.5, "Page 1 of 2", rgb=(0.45, 0.50, 0.58)))

    # ================= PAGE 2 =================
    p2: List[str] = []
    p2.append(_rect(42, 774, 511, 30, (0.06, 0.09, 0.16)))
    p2.append(_text(56, 785, 10.0, "REELS2LEAD CRM  |  TEKSHIRUV JADVALI VA ADMIN BILAN BOG'LANISH", bold=True, rgb=(1.0, 1.0, 1.0)))

    p2.append(_text(42, 748, 11.5, "2. Tezkor Tekshiruv Jadvali (Ulanishdan oldin solishtiring):", bold=True, rgb=(0.06, 0.09, 0.16)))

    # Table Header
    p2.append(_rect(42, 714, 511, 24, (0.12, 0.16, 0.24)))
    p2.append(_text(52, 722, 9.3, "Bo'lim", bold=True, rgb=(1.0, 1.0, 1.0)))
    p2.append(_text(185, 722, 9.3, "Tanlanadigan qiymat", bold=True, rgb=(1.0, 1.0, 1.0)))
    p2.append(_text(365, 722, 9.3, "Nima uchun muhim?", bold=True, rgb=(1.0, 1.0, 1.0)))

    table_rows = [
        ("Instagram turi", "Creator yoki Business", "Meta API faqat professional profilga ochiladi"),
        ("Inbox ruxsati", "Allow IG messages (ON)", "Bot Direct'ga avtomatik xabar yozishi uchun"),
        ("Taklif Gmail", "participantpartic@gmail.com", "Webhook va tokenni rasmiy ulash uchun"),
        ("Huquq darajasi", "Full control (Yoqilgan)", "Token muddatini yangilash va sozlash uchun"),
    ]
    ty = 688.0
    for idx, (c1, c2, c3) in enumerate(table_rows):
        row_bg = (0.98, 0.98, 0.99) if idx % 2 == 0 else (0.94, 0.96, 0.98)
        p2.append(_rect(42, ty, 511, 26, row_bg, (0.82, 0.86, 0.91)))
        p2.append(_text(52, ty + 9, 9.0, c1, bold=True, rgb=(0.06, 0.09, 0.16)))
        p2.append(_text(185, ty + 9, 9.0, c2, bold=True, rgb=(0.72, 0.11, 0.11) if idx >= 1 else (0.06, 0.09, 0.16)))
        p2.append(_text(365, ty + 9, 8.8, c3, rgb=(0.24, 0.30, 0.40)))
        ty -= 26.0

    # Troubleshooting Section
    p2.append(_text(42, 576, 11.5, "3. Ko'p uchraydigan 3 ta xato va ularning tezkor yechimi:", bold=True, rgb=(0.06, 0.09, 0.16)))
    issues = [
        (
            "1) 'Instagram ulanmadi' xatosi chiqsa:",
            "Instagram profil shaxsiy (Personal) holatda qolib ketgan. Uni Creator yoki Business turiga o'tkazing.",
        ),
        (
            "2) Izohga javob beryapti, lekin Direct (DM) bormayapti:",
            "Facebook Page -> Settings -> Linked accounts -> Instagram bo'limida Inbox xabarlar ruxsati (ON) o'chiq qolgan.",
        ),
        (
            "3) Manage tugmasi bosilganda Meta Business Suite ochilsa:",
            "Business Suite ichida Settings -> People -> Invite people tugmasi orqali Gmail'ga Full control taklifini yuboring.",
        ),
    ]
    iy = 552.0
    for ititle, idesc in issues:
        p2.append(_text(48, iy, 9.6, ititle, bold=True, rgb=(0.06, 0.09, 0.16)))
        p2.append(_text(60, iy - 14, 9.0, idesc, rgb=(0.24, 0.30, 0.40)))
        iy -= 38.0

    # URGENT RED CTA BOX AT BOTTOM OF PAGE 2
    p2.append(_rect(42, 165, 511, 245, (0.99, 0.94, 0.94), (0.86, 0.15, 0.15)))
    p2.append(_rect(42, 165, 9, 245, (0.86, 0.15, 0.15)))
    p2.append(_text(64, 384, 11.8, "URGENT / MUHIM: TAKLIF YUBORGANDAN SO'NG ADMINGA YOZING!", bold=True, rgb=(0.72, 0.11, 0.11)))
    p2.append(_text(64, 362, 10.2, "Taklif yuborilganidan so'ng admin: @Yahyobek_U ga xabar yozishingiz shart.", bold=True, rgb=(0.45, 0.08, 0.08)))
    p2.append(_text(64, 342, 9.4, "Pastdagi qizil tugmani bossangiz @Yahyobek_U oynasi tayyor shablon bilan ochiladi:", rgb=(0.25, 0.10, 0.10)))
    p2.append(_text(64, 326, 9.6, "Matn oxiridagi @ belgisidan keyin IG sahifangizni yozib JONATISH ni bosing!", bold=True, rgb=(0.72, 0.11, 0.11)))

    # Clickable Red CTA Button
    p2.append(_rect(64, 280, 356, 32, (0.86, 0.15, 0.15)))
    p2.append(_text(78, 292, 10.5, ">> ADMINGA TAYYOR XABAR YUBORISH: @Yahyobek_U", bold=True, rgb=(1.0, 1.0, 1.0)))

    p2.append(_text(64, 256, 8.8, "Tayyor shablon matni:", bold=True, rgb=(0.35, 0.15, 0.15)))
    p2.append(_text(64, 242, 8.8, '"Assalomu alaykum! Reels2Lead CRM uchun Facebook sahifamga adminlik', rgb=(0.30, 0.15, 0.15)))
    p2.append(_text(64, 229, 8.8, 'taklifini yubordim. Instagram sahifam: @"', rgb=(0.30, 0.15, 0.15)))

    p2.append(_text(64, 202, 10.0, "KEYINGI QADAM (ADMIN JAVOBI):", bold=True, rgb=(0.72, 0.11, 0.11)))
    p2.append(_text(64, 186, 9.4, "Admin sizga o'zi tayyor IG Business ID va Long-Lived Tokenni yuboradi.", rgb=(0.15, 0.15, 0.15)))
    p2.append(_text(64, 172, 9.4, "Siz ularni botdagi 'Instagram Ulash' bo'limiga kiritib ulanishni davom ettirasiz!", bold=True, rgb=(0.06, 0.09, 0.16)))

    p2.append(_text(42, 42, 8.5, "Reels2Lead CRM - Rasmiy Akkaunt Ulash Yo'riqnomasi", rgb=(0.45, 0.50, 0.58)))
    p2.append(_text(500, 42, 8.5, "Page 2 of 2", rgb=(0.45, 0.50, 0.58)))

    tg_url = (
        "https://t.me/Yahyobek_U?text=Assalomu%20alaykum!%20Reels2Lead%20CRM%20uchun%20"
        "Facebook%20sahifamga%20adminlik%20taklifini%20yubordim.%20Instagram%20sahifam%3A%20%40"
    )
    pdf_bytes = _build_multi_page_pdf([p1, p2], [None, (64, 280, 420, 312, tg_url)])
    return BufferedInputFile(pdf_bytes, filename="Reels2Lead_Akkaunt_Ulash_Yoriqnomasi.pdf")


def get_user_guide_pdf() -> InputFile:
    custom_path = os.path.join("docs", "qollanma.pdf")
    if os.path.exists(custom_path):
        return FSInputFile(custom_path, filename="Reels2Lead_CRM_Qollanma.pdf")

    # ================= PAGE 1 =================
    p1: List[str] = []
    p1.append(_rect(42, 748, 511, 56, (0.06, 0.46, 0.43)))
    p1.append(_text(58, 783, 9.8, "REELS2LEAD CRM  |  MIJOZLAR UCHUN TO'LIQ QO'LLANMA", bold=True, rgb=(0.80, 0.98, 0.94)))
    p1.append(_text(58, 761, 14.5, "Instagram Reels va Karusellardan Avtomatik Mijoz Yig'ish", bold=True, rgb=(1.0, 1.0, 1.0)))
    p1.append(_text(42, 728, 9.5, "10 soniyali Anti-Ban himoya bilan izohlarga javob berish va telefon raqamlarni Google Sheets'ga yig'ish tartibi", rgb=(0.25, 0.32, 0.42)))

    # 5-Step Pipeline Visual Diagram
    pipe_boxes = [
        ("1. /start", "Gmail -> Sheets"),
        ("2. IG Ulash", "ID va Token"),
        ("3. Reels", "Video / Karusel"),
        ("4. Skriptlar", "DM + Kalit so'z"),
        ("5. CRM Jadval", "Lid + Zaxira"),
    ]
    px = 42.0
    for idx, (t_lbl, s_lbl) in enumerate(pipe_boxes):
        is_last = idx == len(pipe_boxes) - 1
        bg = (0.93, 0.99, 0.97) if is_last else (0.96, 0.97, 0.99)
        bd = (0.06, 0.46, 0.43) if is_last else (0.75, 0.80, 0.88)
        tc = (0.06, 0.38, 0.35) if is_last else (0.06, 0.09, 0.16)
        p1.append(_rect(px, 668, 92, 44, bg, bd))
        p1.append(_text(px + 9, 694, 9.0, t_lbl, bold=True, rgb=tc))
        p1.append(_text(px + 9, 679, 8.2, s_lbl, rgb=(0.28, 0.35, 0.44)))
        if not is_last:
            p1.append(_text(px + 95.0, 686, 9.5, "->", bold=True, rgb=(0.06, 0.46, 0.43)))
        px += 104.5

    p1.append(_text(42, 638, 11.5, "1. Botni 3 daqiqada sozlash va ishga tushirish (Batafsil 5 qadam):", bold=True, rgb=(0.06, 0.09, 0.16)))

    steps = [
        (
            "1-qadam. /start, Gmail kiritish va Bonus yo'nalishini tanlash",
            [
                "Botga /start bosing, biznesingiz nomini va Gmail manzilingizni kiriting. Tizim avtomatik tarzda",
                "sizning Gmail'ingizga ulangan View-Only Google Sheets CRM jadvalini ochib beradi.",
                "So'ng boshlang'ich bonusni tanlang: C+P (100 ta bonus DM) yoki C+P+L (15 ta bonus tayyor lid).",
            ],
        ),
        (
            "2-qadam. Instagram sahifani ulash ('Instagram Ulash' menyusi)",
            [
                "Avval 'Akkaunt Ulash Yo'riqnomasi' bo'yicha Facebook Page adminlik taklifini yuboring va adminga yozing.",
                "Admin bergan IG Business ID va Long-Lived Tokenni 'Instagram Ulash'ga kiriting -> IG: @sahifangiz yonadi.",
            ],
        ),
        (
            "3-qadam. Reels video yoki Karusel postni ulash ('Reels Ulash' menyusi)",
            [
                "'Oxirgi Reels'lardan tanlash' tugmasi orqali kerakli videoni bitta bosishda ulang yoki havolasini yuboring.",
                "Bir vaqtning o'zida cheksiz sondagi Reels videolarni kuzatuvga ulab qo'yishingiz mumkin.",
            ],
        ),
        (
            "4-qadam. Skriptlar va Kalit so'zlarni sozlash ('Skriptlar' menyusi)",
            [
                "C+P rejimida: Izoh javobi, Direct xabari va 'C+P Link'ni kiriting (havola avtomatik xabar oxiriga qo'shiladi).",
                "C+P+L rejimida: DM 1-xabar (raqam so'rovi) va DM 2-xabar (qo'shimcha savol - 1 tugma bilan Yoqish/O'chirish).",
                "'Kalit so'zlar (Komment)' bo'limida Reels'ni tanlab, 'Izoh kiritish (+)' (masalan: +, narx) yoki 'Barcha komentlar'ni tanlang.",
            ],
        ),
        (
            "5-qadam. Tayyor mijozlarni qabul qilish ('Holat' va 'Zaxira Lidlar')",
            [
                "Raqam qoldirgan mijozlar soniyasida Telegram xabarnoma va Google Sheets jadvalingizda paydo bo'ladi.",
                "Limit tugagandan keyin kelgan murojaatlar esa yo'qolmaydi - 'Zaxira Lidlar' bo'limida alohida saqlanadi.",
            ],
        ),
    ]

    y = 612.0
    for title, lines in steps:
        p1.append(_text(46, y, 10.0, title, bold=True, rgb=(0.06, 0.38, 0.35)))
        y -= 14.5
        for line in lines:
            p1.append(_text(58, y, 9.1, line, rgb=(0.22, 0.28, 0.38)))
            y -= 13.5
        y -= 10.0

    # Key Value Callout Box at Bottom of Page 1
    p1.append(_rect(42, 110, 511, 76, (0.94, 0.99, 0.98), (0.06, 0.46, 0.43)))
    p1.append(_text(56, 168, 10.0, "ASOSIY AFZALLIK: FAQAT NATIJA UCHUN TO'LOV (C+P+L)", bold=True, rgb=(0.06, 0.38, 0.35)))
    p1.append(_text(56, 152, 9.1, "C+P+L tariflarida izoh yozgan, lekin Direct'da telefon raqam qoldirmagan odamlar uchun limit kamaymaydi.", rgb=(0.18, 0.25, 0.32)))
    p1.append(_text(56, 137, 9.1, "Faqat Google Sheets jadvalingizga tushgan haqiqiy, takrorlanmagan +998 telefon raqamlar sanaladi!", bold=True, rgb=(0.06, 0.09, 0.16)))
    p1.append(_text(56, 122, 9.1, "Bitta mijoz raqamini ikki marta yozsa ham dublikat sifatida filtrlanadi va limitdan yechilmaydi.", rgb=(0.18, 0.25, 0.32)))

    p1.append(_text(42, 42, 8.5, "Reels2Lead CRM - Mijozlar Uchun To'liq Qo'llanma", rgb=(0.45, 0.50, 0.58)))
    p1.append(_text(500, 42, 8.5, "Page 1 of 2", rgb=(0.45, 0.50, 0.58)))

    # ================= PAGE 2 =================
    p2: List[str] = []
    p2.append(_rect(42, 774, 511, 30, (0.06, 0.46, 0.43)))
    p2.append(_text(56, 785, 10.0, "REELS2LEAD CRM  |  REJIMLAR TAQQOSLAMASI VA XAVFSIZLIK KAFOLATI", bold=True, rgb=(1.0, 1.0, 1.0)))

    p2.append(_text(42, 748, 11.5, "2. Ikki Rejim Taqqoslamasi (O'zingizga mos yo'nalishni tanlang):", bold=True, rgb=(0.06, 0.09, 0.16)))

    # Table Header
    p2.append(_rect(42, 714, 511, 24, (0.06, 0.46, 0.43)))
    p2.append(_text(52, 722, 9.3, "Xususiyat", bold=True, rgb=(1.0, 1.0, 1.0)))
    p2.append(_text(165, 722, 9.3, "C+P Rejimi (Bloger / Kanal)", bold=True, rgb=(1.0, 1.0, 1.0)))
    p2.append(_text(365, 722, 9.3, "C+P+L Rejimi (Biznes CRM)", bold=True, rgb=(1.0, 1.0, 1.0)))

    comp_rows = [
        ("Kimlar uchun?", "Bloger, ekspert, Telegram/YouTube kanal", "Xizmatlar, o'quv markaz, klinika, do'kon"),
        ("Boshlang'ich bonus", "100 ta noyob DM kontakt (bepul sinov)", "15 ta tayyor telefon raqam (bepul sinov)"),
        ("Asosiy vazifasi", "Izohga javob + Direct'ga tayyor link", "Izohga javob + Direct'da +998 raqam"),
        ("Direct suhbat", "1 ta havolali xabar (link avtomatik)", "1 qadam (Faqat tel) yoki 2 qadam (Tel+Izoh)"),
        ("CRM va Zaxira", "Shart emas (to'g'ri linkka o'tadi)", "Avtomatik Google Sheets + Zaxira Lidlar"),
    ]
    cy = 686.0
    for idx, (r1, r2, r3) in enumerate(comp_rows):
        bg = (0.98, 0.99, 0.99) if idx % 2 == 0 else (0.94, 0.97, 0.97)
        p2.append(_rect(42, cy, 511, 28, bg, (0.80, 0.86, 0.85)))
        p2.append(_text(52, cy + 10, 9.0, r1, bold=True, rgb=(0.06, 0.09, 0.16)))
        p2.append(_text(165, cy + 10, 8.8, r2, rgb=(0.20, 0.26, 0.34)))
        p2.append(_text(365, cy + 10, 8.8, r3, bold=(idx in (1, 2)), rgb=(0.06, 0.38, 0.35) if idx in (1, 2) else (0.20, 0.26, 0.34)))
        cy -= 28.0

    # Security Section
    p2.append(_text(42, 540, 11.5, "3. Xavfsizlik va Anti-Ban Kafolati (Akkauntingiz qanday himoyalangan?):", bold=True, rgb=(0.06, 0.09, 0.16)))
    sec_items = [
        (
            "1) 100% Rasmiy Meta Graph API v21.0:",
            "Instagram parolingiz hech qachon so'ralmaydi - ulanish faqat rasmiy Facebook Page ruxsati va token orqali bo'ladi.",
        ),
        (
            "2) 6-12 soniyali Anti-Ban navbat (Queue Worker):",
            "Video ostiga bir daqiqada 200 ta izoh tushsa ham, bot ularni navbatga qo'yib har 6-12 soniyada xavfsiz javob beradi.",
        ),
        (
            "3) 1 odam = 1 javob himoyasi (Anti-Spam):",
            "Bitta foydalanuvchi bitta videoga 5 marta ketma-ket izoh yozsa ham, bot unga faqat 1 marta javob qaytaradi.",
        ),
        (
            "4) Zaxira Lidlar (Overage) himoya tizimi:",
            "Paketingiz tugab qolsa ham, avval Direct'ga kirgan mijozlar raqami yo'qolmaydi - Zaxira bazada saqlanib turadi.",
        ),
    ]
    sy = 514.0
    for stitle, sdesc in sec_items:
        p2.append(_text(48, sy, 9.6, stitle, bold=True, rgb=(0.06, 0.38, 0.35)))
        p2.append(_text(60, sy - 14, 9.0, sdesc, rgb=(0.22, 0.28, 0.36)))
        sy -= 39.0

    # Tariffs, Promo & Support Box
    p2.append(_rect(42, 185, 511, 145, (0.96, 0.97, 0.99), (0.75, 0.80, 0.88)))
    p2.append(_text(56, 310, 10.5, "4. Tariflar, 1 Martalik Promo-Kodlar va Texnik Yordam:", bold=True, rgb=(0.06, 0.09, 0.16)))
    p2.append(_text(56, 290, 9.2, "* 'Tariflar' bo'limidan o'zingizga mos paketni tanlang va to'lov chekini yuboring (1-5 daqiqada ochiladi).", rgb=(0.20, 0.26, 0.34)))
    p2.append(_text(56, 273, 9.2, "* Agar sizda 1 martalik Promo-kod bo'lsa, chek o'rniga kodni yozing - tarif darhol avtomatik ochiladi.", rgb=(0.20, 0.26, 0.34)))
    p2.append(_text(56, 256, 9.2, "* 'Holat / Statistika' menyusi orqali botni istalgan vaqtda Pauza qilish yoki qayta Yoqish mumkin.", rgb=(0.20, 0.26, 0.34)))
    p2.append(_text(56, 232, 9.8, "Texnik yordam va ulanish bo'yicha admin: @Yahyobek_U (Telegram)", bold=True, rgb=(0.72, 0.11, 0.11)))
    p2.append(_text(56, 214, 9.0, "Savollar yoki yangi token olish uchun istalgan vaqtda adminga murojaat qilishingiz mumkin.", rgb=(0.24, 0.30, 0.40)))

    p2.append(_text(42, 42, 8.5, "Reels2Lead CRM - Mijozlar Uchun To'liq Qo'llanma", rgb=(0.45, 0.50, 0.58)))
    p2.append(_text(500, 42, 8.5, "Page 2 of 2", rgb=(0.45, 0.50, 0.58)))

    pdf_bytes = _build_multi_page_pdf([p1, p2])
    return BufferedInputFile(pdf_bytes, filename="Reels2Lead_CRM_Qollanma.pdf")