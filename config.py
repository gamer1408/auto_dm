import os
from dataclasses import dataclass
from typing import Dict, List
from dotenv import load_dotenv

load_dotenv()


class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
    ADMIN_TG_ID: int = int(os.getenv("ADMIN_TG_ID", "0") or "0")
    ADMIN_ALERT_CHAT_ID: int = int(os.getenv("ADMIN_ALERT_CHAT_ID", "0") or "0")
    ADMIN_GMAIL: str = os.getenv("ADMIN_GMAIL", "urozaliyevyahyobek@gmail.com").strip()

    # Meta Instagram Graph API
    META_VERIFY_TOKEN: str = os.getenv("META_VERIFY_TOKEN", "c2_insta_lid_verify_2026").strip()
    META_APP_SECRET: str = os.getenv("META_APP_SECRET", "").strip()
    META_GRAPH_VERSION: str = os.getenv("META_GRAPH_VERSION", "v21.0").strip()

    # Database: PostgreSQL on Render/Neon/Supabase OR SQLite locally
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./c2_saas.db").strip()

    # Google Sheets Credentials (raw/base64 JSON in env OR local service_account.json)
    GOOGLE_CREDENTIALS_JSON: str = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
    GOOGLE_CREDENTIALS_FILE: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "service_account.json").strip()

    # Payment display details + Click/Payme Merchant Webhook secret
    PAYMENT_CARD_NUMBER: str = os.getenv("PAYMENT_CARD_NUMBER", "8600 0000 0000 0000").strip()
    PAYMENT_CARD_HOLDER: str = os.getenv("PAYMENT_CARD_HOLDER", "YAHYOBEK UROZALIYEV").strip()
    CLICK_PAY_LINK: str = os.getenv("CLICK_PAY_LINK", "").strip()
    PAYMENT_WEBHOOK_SECRET: str = os.getenv("PAYMENT_WEBHOOK_SECRET", "change_me_secret").strip()

    # Anti-ban default delay (seconds)
    DEFAULT_QUEUE_DELAY: int = int(os.getenv("DEFAULT_QUEUE_DELAY", "10") or "10")


settings = Settings()


@dataclass(frozen=True)
class PlanSpec:
    code: str
    name: str
    mode: str              # "CP" or "CPL"
    price_uzs: int
    leads_limit: int       # For CPL: guaranteed leads
    bonus_limit: int       # For CPL: +15 / +30 / +50 / +100
    overage_price: int     # For CPL: price per reserve lead
    contacts_limit: int    # For CP: monthly unique DM contacts (0 = unlimited for CP_UNLIM)
    queue_delay_sec: int   # Anti-ban delay per tenant
    description: str


PLANS: Dict[str, PlanSpec] = {
    # --- FREE TRIALS ---
    "FREE_CPL": PlanSpec(
        code="FREE_CPL",
        name="Sinov (15 ta Bepul Lid)",
        mode="CPL",
        price_uzs=0,
        leads_limit=15,
        bonus_limit=0,
        overage_price=2000,
        contacts_limit=0,
        queue_delay_sec=12,
        description="15 ta tayyor telefon raqam Google Sheets'ga tushguncha bepul sinov.",
    ),
    "FREE_CP": PlanSpec(
        code="FREE_CP",
        name="Sinov Creator (100 ta DM)",
        mode="CP",
        price_uzs=0,
        leads_limit=0,
        bonus_limit=0,
        overage_price=0,
        contacts_limit=100,
        queue_delay_sec=12,
        description="100 ta noyob odamga izoh javobi + Direct havola yuborish.",
    ),
    # --- CREATOR (C + P) ---
    "CP_1K": PlanSpec(
        code="CP_1K",
        name="Creator 1K (C+P)",
        mode="CP",
        price_uzs=89_000,
        leads_limit=0,
        bonus_limit=0,
        overage_price=0,
        contacts_limit=1_000,
        queue_delay_sec=10,
        description="Oyiga 1,000 ta noyob DM kontakt | Cheksiz Reels | 10s Anti-Ban.",
    ),
    "CP_5K": PlanSpec(
        code="CP_5K",
        name="Creator 5K (C+P)",
        mode="CP",
        price_uzs=179_000,
        leads_limit=0,
        bonus_limit=0,
        overage_price=0,
        contacts_limit=5_000,
        queue_delay_sec=10,
        description="Oyiga 5,000 ta noyob DM kontakt | Cheksiz Reels | 10s Anti-Ban.",
    ),
    "CP_UNLIM": PlanSpec(
        code="CP_UNLIM",
        name="Creator Unlim (C+P)",
        mode="CP",
        price_uzs=290_000,
        leads_limit=0,
        bonus_limit=0,
        overage_price=0,
        contacts_limit=0,
        queue_delay_sec=8,
        description="Cheksiz DM kontaktlar | Cheksiz Reels | Tezkor 8s navbat.",
    ),
    # --- BIZNES CRM (C + P + L — GUARANTEED LEADS) ---
    "CPL_250": PlanSpec(
        code="CPL_250",
        name="Lead 250 (+15 Bonus)",
        mode="CPL",
        price_uzs=490_000,
        leads_limit=250,
        bonus_limit=15,
        overage_price=2_000,
        contacts_limit=0,
        queue_delay_sec=10,
        description="250 asosiy + 15 BONUS = 265 ta tayyor lid | Zaxira lid: 2,000 UZS.",
    ),
    "CPL_500": PlanSpec(
        code="CPL_500",
        name="Lead 500 (+30 Bonus)",
        mode="CPL",
        price_uzs=890_000,
        leads_limit=500,
        bonus_limit=30,
        overage_price=1_800,
        contacts_limit=0,
        queue_delay_sec=10,
        description="500 asosiy + 30 BONUS = 530 ta tayyor lid | Zaxira lid: 1,800 UZS.",
    ),
    "CPL_1000": PlanSpec(
        code="CPL_1000",
        name="Lead 1,000 (+50 Bonus)",
        mode="CPL",
        price_uzs=1_590_000,
        leads_limit=1_000,
        bonus_limit=50,
        overage_price=1_600,
        contacts_limit=0,
        queue_delay_sec=8,
        description="1,000 asosiy + 50 BONUS = 1,050 ta tayyor lid | Zaxira lid: 1,600 UZS.",
    ),
    "CPL_2500": PlanSpec(
        code="CPL_2500",
        name="Lead 2,500 (+100 Bonus)",
        mode="CPL",
        price_uzs=3_490_000,
        leads_limit=2_500,
        bonus_limit=100,
        overage_price=1_400,
        contacts_limit=0,
        queue_delay_sec=6,
        description="2,500 asosiy + 100 BONUS = 2,600 ta tayyor lid | Zaxira lid: 1,400 UZS.",
    ),
}

SCRIPT_TEMPLATES: Dict[str, Dict[str, str]] = {
    "shop": {
        "title": "Onlayn Do'kon (Tovar sotuv)",
        "mode": "CPL",
        "comment_reply": "Assalomu alaykum! Narx va batafsil ma'lumotni Direct'ingizga yubordik ✅",
        "dm_welcome": (
            "Assalomu alaykum! Qiziqishingiz uchun rahmat.\n"
            "Mahsulotimiz hozir mavjud va O'zbekiston bo'ylab yetkazib beramiz.\n\n"
            "Buyurtma berish yoki batafsil maslahat olishni xohlaysizmi? "
            "Davom etish uchun «Ha» deb yozing 👇"
        ),
        "ask_name": "Ajoyib! Sizga qanday murojaat qilsak bo'ladi? Ismingizni yozing:",
        "ask_phone": "Rahmat, {name}! Menejerimiz bog'lanishi uchun telefon raqamingizni qoldiring (masalan: +998901234567):",
        "ask_qty": "Nechta dona buyurtma bermoqchisiz? (yoki qaysi rang/o'lcham kerak?):",
        "done": "Rahmat, {name}! Buyurtmangiz qabul qilindi ✅ Tez orada menejerimiz {phone} raqamiga bog'lanadi.",
    },
    "edu": {
        "title": "O'quv Markaz / Kurslar",
        "mode": "CPL",
        "comment_reply": "Assalomu alaykum! Kurs dasturi va narxlarni Direct'ga yubordik ✅",
        "dm_welcome": (
            "Assalomu alaykum! Kurslarimizga qiziqqaningiz uchun rahmat.\n"
            "Bepul sinov darsiga yozilish va chegirma olishni xohlaysizmi?\n\n"
            "Ro'yxatdan o'tish uchun «Ha» deb yozing 👇"
        ),
        "ask_name": "Ajoyib! Ismingizni yozib qoldiring:",
        "ask_phone": "Rahmat, {name}! Bog'lanishimiz uchun telefon raqamingizni yozing (+998...):",
        "ask_qty": "Qaysi yo'nalish yoki vaqt (ertalab/kechqurun) sizga qulay?",
        "done": "Ajoyib, {name}! Siz ro'yxatga olindingiz ✅ Administratorimiz tez orada {phone} raqamiga qo'ng'iroq qiladi.",
    },
    "clinic": {
        "title": "Klinika / Go'zallik Saloni",
        "mode": "CPL",
        "comment_reply": "Assalomu alaykum! Narxlar va qabul vaqtini Direct'ingizga yubordik ✅",
        "dm_welcome": (
            "Assalomu alaykum! Xizmatlarimizga qiziqish bildirganingiz uchun rahmat.\n"
            "Bepul konsultatsiya yoki qabulga yozilishni istaysizmi?\n\n"
            "Yozilish uchun «Ha» deb javob bering 👇"
        ),
        "ask_name": "Marhamat, ismingizni yozing:",
        "ask_phone": "Rahmat, {name}! Qabul vaqtini tasdiqlash uchun telefon raqamingizni qoldiring (+998...):",
        "ask_qty": "Qaysi kun yoki qaysi xizmat turi sizni qiziqtirmoqda?",
        "done": "Rahmat, {name}! Arizangiz qabul qilindi ✅ Administratorimiz tez orada {phone} raqamiga bog'lanadi.",
    },
    "creator": {
        "title": "Bloger / Ekspert (C+P Link)",
        "mode": "CP",
        "comment_reply": "Direct'ingizga havolani yubordim, tekshirib ko'ring! ✅",
        "dm_welcome": (
            "Salom! So'ragan foydali materialingiz / havolangiz tayyor:\n\n"
            "{link}\n\n"
            "Foydali bo'lsa saqlab qo'ying!"
        ),
        "ask_name": "Ismingizni yozing:",
        "ask_phone": "Telefon raqamingizni yozing (+998...):",
        "ask_qty": "Miqdorini yozing:",
        "done": "Rahmat! Ma'lumotingiz saqlandi.",
    },
}

POSITIVE_WORDS: List[str] = [
    "ha", "xa", "da", "yes", "ok", "oke", "okey", "mayli", "albatta",
    "kerak", "xohlayman", "hohlayman", "olaman", "buyurtma", "yoziling",
    "yozilaman", "boshladik", "+", "1", "davom", "bering", "istayman",
]


def format_uzs(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " UZS"
