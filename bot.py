import logging
import re
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, select

from config import PLANS, SCRIPT_TEMPLATES, format_uzs, settings
from database import (
    AsyncSessionLocal,
    Lead,
    PaymentRequest,
    ReelsTarget,
    Tenant,
    UsedTrial,
    apply_plan_to_tenant,
    count_main_leads,
    get_pending_reserve_leads,
    get_tenant_by_id,
    get_tenant_by_tg,
)
from funnel_engine import set_notify_callback
from instagram_api import ig_api
from queue_worker import queue_manager
from sheets_manager import provision_tenant_sheets, transfer_reserve_to_main

logger = logging.getLogger("c2.bot")

bot = Bot(
    token=settings.BOT_TOKEN or "123456:DUMMY_TOKEN_FOR_IMPORT",
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


class OnboardingFSM(StatesGroup):
    business_name = State()
    owner_gmail = State()


class IGConnectFSM(StatesGroup):
    ig_user_id = State()
    access_token = State()


class ReelLinkFSM(StatesGroup):
    reel_url = State()
    keywords = State()


class ScriptEditFSM(StatesGroup):
    waiting_value = State()


class PaymentFSM(StatesGroup):
    waiting_receipt = State()


def main_menu_kb(tenant: Tenant) -> InlineKeyboardMarkup:
    ig_label = f"✅ IG: @{tenant.ig_username}" if tenant.ig_user_id else "🔗 Instagram Ulash"
    status_emoji = "🟢" if tenant.comment_active else "🔴"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ig_label, callback_data="menu:ig")],
            [
                InlineKeyboardButton(text="🎬 Reels Ulash", callback_data="menu:reels"),
                InlineKeyboardButton(text="✍️ Skriptlar", callback_data="menu:scripts"),
            ],
            [
                InlineKeyboardButton(text="💎 Tariflar", callback_data="menu:tariffs"),
                InlineKeyboardButton(text="🔥 Zaxira Lidlar", callback_data="menu:reserve"),
            ],
            [
                InlineKeyboardButton(
                    text=f"{status_emoji} Holat / Statistika", callback_data="menu:stats"
                ),
            ],
        ]
    )


async def send_telegram_alert(
    tg_user_id: int, text: str, button_action: Optional[str] = None
) -> None:
    kb = None
    if button_action == "open_tariffs":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💎 Yangi paket tanlash", callback_data="menu:tariffs")]
            ]
        )
    elif button_action == "buy_reserve":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔓 Zaxira lidlarni ochish", callback_data="menu:reserve")],
                [InlineKeyboardButton(text="💎 Yangi paket olish", callback_data="menu:tariffs")],
            ]
        )
    await bot.send_message(chat_id=tg_user_id, text=text, reply_markup=kb)


set_notify_callback(send_telegram_alert)


# --- /start & Onboarding ---

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, message.from_user.id)
        if tenant:
            await message.answer(
                f"👋 Xush kelibsiz, <b>{tenant.business_name}</b>!\n"
                f"C2 — Insta-Lid CRM boshqaruv paneli:",
                reply_markup=main_menu_kb(tenant),
            )
            return

    await state.set_state(OnboardingFSM.business_name)
    await message.answer(
        "🚀 <b>C2 — Insta-Lid CRM</b> platformasiga xush kelibsiz!\n\n"
        "Reels izohlaridan 10 soniyali Anti-Ban navbat bilan tayyor telefon raqamlar yig'uvchi tizim.\n\n"
        "Boshlash uchun <b>biznesingiz yoki blogingiz nomini</b> yozing:"
    )


@router.message(OnboardingFSM.business_name)
async def on_business_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Iltimos, biznes nomini to'g'ri kiriting:")
        return
    await state.update_data(business_name=name[:180])
    await state.set_state(OnboardingFSM.owner_gmail)
    await message.answer(
        "📧 Endi <b>Gmail manzilingizni</b> yozing (masalan: <code>biznes@gmail.com</code>).\n"
        "Tizim sizga avtomatik tarzda <b>View-Only Google Sheets CRM</b> jadvalini yaratib beradi:"
    )


@router.message(OnboardingFSM.owner_gmail)
async def on_owner_gmail(message: Message, state: FSMContext) -> None:
    gmail = (message.text or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", gmail):
        await message.answer("Email formati noto'g'ri. Iltimos, to'g'ri Gmail kiriting:")
        return

    data = await state.get_data()
    bname = data["business_name"]
    wait_msg = await message.answer("⏳ Shaxsiy Google Sheets CRM jadvalingiz yaratilmoqda...")

    main_id, main_url, res_id, res_url = await provision_tenant_sheets(bname, gmail)

    async with AsyncSessionLocal() as db:
        tenant = Tenant(
            tg_user_id=message.from_user.id,
            business_name=bname,
            owner_gmail=gmail,
            main_sheet_id=main_id,
            main_sheet_url=main_url,
            reserve_sheet_id=res_id,
            reserve_sheet_url=res_url,
        )
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)

    await state.clear()
    sheet_info = (
        f"📊 <b>CRM Jadvalingiz (Faqat ko'rish):</b>\n{main_url}\n\n"
        if main_url
        else "ℹ️ Google Sheets kaliti hali ulanmagan (sozlangach Statistika bo'limidan yaratishingiz mumkin).\n\n"
    )
    await wait_msg.edit_text(
        f"✅ <b>{bname}</b> muvaffaqiyatli ro'yxatdan o'tdi!\n\n"
        f"{sheet_info}"
        f"Endi <b>🔗 Instagram Ulash</b> tugmasini bosib sahifangizni ulang va <b>15 ta bepul lid</b>ni sinab ko'ring:",
        reply_markup=main_menu_kb(tenant),
    )


# --- Home / Stats ---

@router.callback_query(F.data == "menu:home")
async def cb_home(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)
        if not tenant:
            await call.answer("Avval /start bosing", show_alert=True)
            return
        await call.message.edit_text(
            f"🏠 <b>{tenant.business_name}</b> — Bosh menyu:",
            reply_markup=main_menu_kb(tenant),
        )


@router.callback_query(F.data == "menu:stats")
async def cb_stats(call: CallbackQuery) -> None:
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)
        if not tenant:
            return
        pending_res = await get_pending_reserve_leads(db, tenant.id)
        reels_cnt = (
            await db.execute(
                select(func.count(ReelsTarget.id)).where(
                    ReelsTarget.tenant_id == tenant.id, ReelsTarget.is_active == True  # noqa: E712
                )
            )
        ).scalar() or 0

        plan = PLANS.get(tenant.plan_code)
        plan_name = plan.name if plan else tenant.plan_code
        state_str = "🟢 FAOL" if tenant.comment_active else "🔴 TO'XTATILGAN"

        if tenant.mode == "CPL":
            quota_text = (
                f"🎯 Lidlar: <b>{tenant.leads_used} / {tenant.leads_limit}</b> "
                f"(+<b>{tenant.bonus_limit}</b> bonus)\n"
                f"🔥 Zaxirada kutayotgan lidlar: <b>{len(pending_res)} ta</b>"
            )
        else:
            lim = "Cheksiz" if tenant.plan_code == "CP_UNLIM" else str(tenant.contacts_limit)
            quota_text = f"💬 Oylik DM kontaktlar: <b>{tenant.contacts_used} / {lim}</b>"

        sheet_line = f"📊 CRM Jadval: {tenant.main_sheet_url}" if tenant.main_sheet_url else "📊 CRM Jadval: Ulanmagan"

        rows = [
            [
                InlineKeyboardButton(
                    text="⏸ Pauza qilish" if tenant.comment_active else "▶️ Yoqish",
                    callback_data="stats:toggle",
                )
            ]
        ]
        if not tenant.main_sheet_id:
            rows.append([InlineKeyboardButton(text="📊 Google Sheets yaratish", callback_data="stats:makesheet")])
        rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="menu:home")])

        await call.message.edit_text(
            f"📊 <b>{tenant.business_name} — Statistika</b>\n\n"
            f"📌 Rejim: <b>{tenant.mode}</b> | Tarif: <b>{plan_name}</b>\n"
            f"⚙️ Izohlarni ovlash: <b>{state_str}</b>\n"
            f"⏱ Anti-Ban oraliq: <b>{tenant.queue_delay_sec} soniya</b>\n"
            f"🎬 Ulangan faol Reels: <b>{reels_cnt} ta</b>\n"
            f"{quota_text}\n\n"
            f"{sheet_line}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )


@router.callback_query(F.data == "stats:makesheet")
async def cb_make_sheet(call: CallbackQuery) -> None:
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)
        if not tenant:
            return
        main_id, main_url, res_id, res_url = await provision_tenant_sheets(
            tenant.business_name, tenant.owner_gmail
        )
        if not main_id:
            await call.answer("Google Service Account sozlanmagan.", show_alert=True)
            return
        tenant.main_sheet_id = main_id
        tenant.main_sheet_url = main_url
        tenant.reserve_sheet_id = res_id
        tenant.reserve_sheet_url = res_url
        await db.commit()
    await call.answer("✅ Google Sheets yaratildi!", show_alert=True)
    await cb_stats(call)


@router.callback_query(F.data == "stats:toggle")
async def cb_toggle_active(call: CallbackQuery) -> None:
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)
        if not tenant:
            return
        if not tenant.comment_active and tenant.mode == "CPL":
            if tenant.leads_used >= (tenant.leads_limit + tenant.bonus_limit):
                await call.answer(
                    "Paket limiti tugagan! Avval yangi tarif sotib oling.", show_alert=True
                )
                return
        tenant.comment_active = not tenant.comment_active
        await db.commit()
    await cb_stats(call)


# --- Instagram Connect (with Anti-Fraud Free Trial check) ---

@router.callback_query(F.data == "menu:ig")
async def cb_ig_menu(call: CallbackQuery, state: FSMContext) -> None:
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)
        if not tenant:
            return
        if tenant.ig_user_id:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Tokenni yangilash", callback_data="ig:connect")],
                    [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="menu:home")],
                ]
            )
            await call.message.edit_text(
                f"✅ <b>Instagram ulangan!</b>\n\n"
                f"👤 Sahifa: <b>@{tenant.ig_username}</b>\n"
                f"🆔 IG Business ID: <code>{tenant.ig_user_id}</code>",
                reply_markup=kb,
            )
            return

    await state.set_state(IGConnectFSM.ig_user_id)
    await call.message.edit_text(
        "🔗 <b>Instagram Business Akkauntni Ulash</b>\n\n"
        "1-qadam: <b>Instagram Business Account ID</b> raqamini yuboring:\n"
        "<i>(Meta Business Suite / Graph API Explorer'dan olinadi)</i>"
    )


@router.callback_query(F.data == "ig:connect")
async def cb_ig_reconnect(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(IGConnectFSM.ig_user_id)
    await call.message.edit_text("1-qadam: <b>Instagram Business Account ID</b> raqamini yuboring:")


@router.message(IGConnectFSM.ig_user_id)
async def on_ig_id(message: Message, state: FSMContext) -> None:
    ig_id = (message.text or "").strip()
    if not ig_id.isdigit():
        await message.answer("IG Business ID faqat raqamlardan iborat bo'lishi kerak. Qayta yuboring:")
        return
    await state.update_data(ig_user_id=ig_id)
    await state.set_state(IGConnectFSM.access_token)
    await message.answer("2-qadam: <b>Long-Lived Page Access Token</b>ni yuboring:")


@router.message(IGConnectFSM.access_token)
async def on_ig_token(message: Message, state: FSMContext) -> None:
    token = (message.text or "").strip()
    data = await state.get_data()
    ig_id = data["ig_user_id"]

    ok, username, err = await ig_api.validate_account(ig_id, token)
    if not ok:
        await message.answer(
            f"❌ Instagram ulanishida xato:\n<code>{err}</code>\n\n"
            f"ID va Tokenni tekshirib qayta urinib ko'ring (/start)."
        )
        await state.clear()
        return

    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, message.from_user.id)
        other = (
            await db.execute(
                select(Tenant).where(Tenant.ig_user_id == ig_id, Tenant.id != tenant.id)
            )
        ).scalar_one_or_none()
        if other:
            await message.answer(
                "⛔️ Bu Instagram sahifa allaqachon boshqa obunaga ulangan (1 obuna = 1 sahifa)."
            )
            await state.clear()
            return

        trial_used = (
            await db.execute(select(UsedTrial).where(UsedTrial.ig_user_id == ig_id))
        ).scalar_one_or_none()

        tenant.ig_user_id = ig_id
        tenant.ig_username = username
        tenant.page_access_token = token

        trial_note = ""
        if not trial_used:
            db.add(UsedTrial(ig_user_id=ig_id, tg_user_id=tenant.tg_user_id))
            trial_note = "🎁 <b>15 ta bepul sinov lidi</b> faollashtirildi!"
        elif tenant.plan_code.startswith("FREE"):
            tenant.leads_limit = 0
            tenant.contacts_limit = 0
            tenant.comment_active = False
            trial_note = (
                "⚠️ Bu Instagram sahifa avval bepul sinovdan foydalangan.\n"
                "Ishga tushirish uchun <b>💎 Tariflar</b> bo'limidan paket tanlang."
            )

        await db.commit()

    await state.clear()
    await message.answer(
        f"✅ <b>@{username}</b> sahifasi muvaffaqiyatli ulandi!\n\n{trial_note}",
        reply_markup=main_menu_kb(tenant),
    )


# --- Reels Management (1-Click Recent Fetch + URL Link) ---

@router.callback_query(F.data == "menu:reels")
async def cb_reels_menu(call: CallbackQuery) -> None:
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)
        if not tenant or not tenant.ig_user_id:
            await call.answer("Avval Instagram sahifangizni ulang!", show_alert=True)
            return

        reels = list(
            (
                await db.execute(
                    select(ReelsTarget)
                    .where(ReelsTarget.tenant_id == tenant.id)
                    .order_by(ReelsTarget.id.desc())
                )
            )
            .scalars()
            .all()
        )

    lines = ["🎬 <b>Ulangan Reels videolaringiz:</b>\n"]
    buttons = []
    if not reels:
        lines.append("<i>Hozircha Reels ulanmagan. Pastdagi tugmalardan birini tanlang:</i>")
    else:
        for r in reels[:10]:
            st = "🟢" if r.is_active else "⚪️"
            mode_txt = "Barcha izohlar" if r.keyword_mode == "ALL" else f"So'zlar: {r.keywords_csv}"
            cap = (r.caption_preview or r.media_id)[:32]
            lines.append(f"{st} <b>{cap}</b> — <i>{mode_txt}</i>")
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"🗑 O'chirish: {cap[:20]}", callback_data=f"reel:del:{r.id}"
                    )
                ]
            )

    buttons.append([InlineKeyboardButton(text="📋 Oxirgi Reels'lardan tanlash", callback_data="reel:fetch")])
    buttons.append([InlineKeyboardButton(text="🔗 Reels link tashlash", callback_data="reel:url")])
    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="menu:home")])

    await call.message.edit_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data == "reel:fetch")
async def cb_reel_fetch(call: CallbackQuery) -> None:
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)
        media_list = await ig_api.get_recent_media(
            tenant.ig_user_id, tenant.page_access_token, limit=10
        )

    if not media_list:
        await call.answer("Media topilmadi yoki token muddati tugagan.", show_alert=True)
        return

    btns = []
    for m in media_list:
        mid = m["id"]
        cap = (m.get("caption") or "Sarlavhasiz Reels").replace("\n", " ")[:36]
        btns.append([InlineKeyboardButton(text=f"🎬 {cap}", callback_data=f"reel:add:{mid}")])
    btns.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="menu:reels")])

    await call.message.edit_text(
        "Ulash uchun Reels videoni tanlang (avtomatik <b>barcha izohlarga</b> ulanadi):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
    )


@router.callback_query(F.data.startswith("reel:add:"))
async def cb_reel_add_pick(call: CallbackQuery) -> None:
    media_id = call.data.split(":", 2)[2]
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)
        existing = (
            await db.execute(
                select(ReelsTarget).where(
                    ReelsTarget.tenant_id == tenant.id, ReelsTarget.media_id == media_id
                )
            )
        ).scalar_one_or_none()
        if not existing:
            db.add(
                ReelsTarget(
                    tenant_id=tenant.id,
                    media_id=media_id,
                    caption_preview=f"Reels #{media_id[-6:]}",
                    keyword_mode="ALL",
                )
            )
            await db.commit()
    await call.answer("✅ Reels ulandi (barcha izohlarga ishlaydi)!", show_alert=True)
    await cb_reels_menu(call)


@router.callback_query(F.data == "reel:url")
async def cb_reel_url_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ReelLinkFSM.reel_url)
    await call.message.edit_text(
        "🔗 Reels havolasini yuboring (masalan: <code>https://www.instagram.com/reel/Cxyz123/</code>):"
    )


@router.message(ReelLinkFSM.reel_url)
async def on_reel_url(message: Message, state: FSMContext) -> None:
    url = (message.text or "").strip()
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, message.from_user.id)
        item = await ig_api.find_media_by_url(tenant.ig_user_id, tenant.page_access_token, url)

    if not item:
        await message.answer(
            "❌ Bu havola sahifangizdagi oxirgi 50 ta media ichidan topilmadi. "
            "Havolani tekshirib qayta yuboring yoki /start bosing."
        )
        return

    await state.update_data(
        media_id=item["id"],
        permalink=item.get("permalink", url),
        caption=(item.get("caption") or f"Reels #{item['id'][-6:]}")[:100],
    )
    await state.set_state(ReelLinkFSM.keywords)
    await message.answer(
        "✅ Reels topildi!\n\n"
        "Barcha izohlarga javob bersinmi yoki faqat aniq kalit so'zlarga?\n"
        "• <b>BARCHASI</b> deb yozsangiz — hamma izohga javob beradi.\n"
        "• Yoki kalit so'zlarni vergul bilan yozing (masalan: <code>narx, +, kurs</code>):"
    )


@router.message(ReelLinkFSM.keywords)
async def on_reel_keywords(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    data = await state.get_data()
    is_all = raw.upper() in {"BARCHASI", "ALL", "HAMMASI", "*"}

    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, message.from_user.id)
        existing = (
            await db.execute(
                select(ReelsTarget).where(
                    ReelsTarget.tenant_id == tenant.id, ReelsTarget.media_id == data["media_id"]
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.keyword_mode = "ALL" if is_all else "KEYWORDS"
            existing.keywords_csv = "" if is_all else raw
            existing.is_active = True
        else:
            db.add(
                ReelsTarget(
                    tenant_id=tenant.id,
                    media_id=data["media_id"],
                    permalink=data["permalink"],
                    caption_preview=data["caption"],
                    keyword_mode="ALL" if is_all else "KEYWORDS",
                    keywords_csv="" if is_all else raw,
                )
            )
        await db.commit()

    await state.clear()
    await message.answer(
        "✅ Reels muvaffaqiyatli ulandi va kuzatuvga olindi!",
        reply_markup=main_menu_kb(tenant),
    )


@router.callback_query(F.data.startswith("reel:del:"))
async def cb_reel_delete(call: CallbackQuery) -> None:
    rid = int(call.data.split(":")[2])
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)
        target = (
            await db.execute(
                select(ReelsTarget).where(
                    ReelsTarget.id == rid, ReelsTarget.tenant_id == tenant.id
                )
            )
        ).scalar_one_or_none()
        if target:
            await db.delete(target)
            await db.commit()
    await call.answer("🗑 Reels o'chirildi.")
    await cb_reels_menu(call)


# --- Scripts & 1-Click Templates ---

@router.callback_query(F.data == "menu:scripts")
async def cb_scripts_menu(call: CallbackQuery) -> None:
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🛍 Shablon: Do'kon", callback_data="tpl:shop"),
                InlineKeyboardButton(text="🎓 Shablon: Kurs", callback_data="tpl:edu"),
            ],
            [
                InlineKeyboardButton(text="🏥 Shablon: Klinika", callback_data="tpl:clinic"),
                InlineKeyboardButton(text="🎬 Shablon: Bloger C+P", callback_data="tpl:creator"),
            ],
            [
                InlineKeyboardButton(text="✏️ Izoh javobi", callback_data="edit:comment_reply_text"),
                InlineKeyboardButton(text="✏️ 1-DM matni", callback_data="edit:dm_welcome_text"),
            ],
            [
                InlineKeyboardButton(text="🔗 C+P Havola (Link)", callback_data="edit:dm_link_url"),
                InlineKeyboardButton(text="✏️ Miqdor savoli", callback_data="edit:ask_qty_text"),
            ],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="menu:home")],
        ]
    )
    await call.message.edit_text(
        f"✍️ <b>Sotuv Skriptlari ({tenant.mode} rejim)</b>\n\n"
        f"💬 <b>Izoh javobi:</b> {tenant.comment_reply_text}\n\n"
        f"📩 <b>1-DM matni:</b>\n{tenant.dm_welcome_text}\n\n"
        f"🔗 <b>Link (C+P uchun):</b> {tenant.dm_link_url}\n\n"
        f"Tayyor shablon tanlang yoki matnlarni tahrirlang:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("tpl:"))
async def cb_apply_template(call: CallbackQuery) -> None:
    key = call.data.split(":")[1]
    tpl = SCRIPT_TEMPLATES[key]
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)
        tenant.comment_reply_text = tpl["comment_reply"]
        tenant.dm_welcome_text = tpl["dm_welcome"]
        tenant.ask_name_text = tpl["ask_name"]
        tenant.ask_phone_text = tpl["ask_phone"]
        tenant.ask_qty_text = tpl["ask_qty"]
        tenant.done_text = tpl["done"]
        await db.commit()
    await call.answer(f"✅ '{tpl['title']}' shabloni qo'llandi!", show_alert=True)
    await cb_scripts_menu(call)


@router.callback_query(F.data.startswith("edit:"))
async def cb_edit_field(call: CallbackQuery, state: FSMContext) -> None:
    field = call.data.split(":")[1]
    await state.set_state(ScriptEditFSM.waiting_value)
    await state.update_data(field=field)
    await call.message.edit_text("✏️ Yangi matnni yuboring:")


@router.message(ScriptEditFSM.waiting_value)
async def on_edit_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data["field"]
    val = (message.text or "").strip()
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, message.from_user.id)
        setattr(tenant, field, val)
        await db.commit()
    await state.clear()
    await message.answer("✅ Matn saqlandi!", reply_markup=main_menu_kb(tenant))


# --- Tariffs & Reserve Leads Buyout ---

@router.callback_query(F.data == "menu:tariffs")
async def cb_tariffs(call: CallbackQuery) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Lead 250 (+15 Bonus) — 490 000 UZS", callback_data="buy:plan:CPL_250")],
            [InlineKeyboardButton(text="🔥 Lead 500 (+30 Bonus) — 890 000 UZS", callback_data="buy:plan:CPL_500")],
            [InlineKeyboardButton(text="🚀 Lead 1,000 (+50 Bonus) — 1 590 000 UZS", callback_data="buy:plan:CPL_1000")],
            [InlineKeyboardButton(text="👑 Lead 2,500 (+100 Bonus) — 3 490 000 UZS", callback_data="buy:plan:CPL_2500")],
            [InlineKeyboardButton(text="🎬 Creator 1K (C+P) — 89 000 UZS", callback_data="buy:plan:CP_1K")],
            [InlineKeyboardButton(text="🎬 Creator 5K (C+P) — 179 000 UZS", callback_data="buy:plan:CP_5K")],
            [InlineKeyboardButton(text="🎬 Creator Unlim (C+P) — 290 000 UZS", callback_data="buy:plan:CP_UNLIM")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="menu:home")],
        ]
    )
    await call.message.edit_text(
        "💎 <b>C2 — Insta-Lid CRM Tariflari</b>\n\n"
        "<b>BIZNES CRM (C+P+L — Kafolatlangan Lidlar):</b>\n"
        "• Faqat Google Sheets'ga tushgan tayyor raqamlar sanaladi!\n"
        "• Cheksiz Reels & Cheksiz DM | +15/+30/+50/+100 Bonus lidlar.\n\n"
        "<b>CREATOR (C+P — Faqat Link yuborish):</b>\n"
        "• Blogerlar va kanal adminlari uchun arzon DM paketlar.\n\n"
        "Kerakli paketni tanlang:",
        reply_markup=kb,
    )


@router.callback_query(F.data == "menu:reserve")
async def cb_reserve_menu(call: CallbackQuery) -> None:
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)
        pending = await get_pending_reserve_leads(db, tenant.id)

    cnt = len(pending)
    if cnt == 0:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="menu:home")]]
        )
        await call.message.edit_text(
            "🔥 <b>Zaxira Baza hozircha bo'sh.</b>\n\n"
            "Paketingiz (asosiy + bonus) tugagandan keyin avval Direct'ga kirgan mijozlar "
            "raqam qoldirsa, ular shu yerga yig'iladi va siz ularni donalab sotib olishingiz mumkin.",
            reply_markup=kb,
        )
        return

    total = cnt * tenant.overage_price
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔓 {cnt} ta lidni ochish ({format_uzs(total)})",
                    callback_data="buy:reserve",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="menu:home")],
        ]
    )
    await call.message.edit_text(
        f"🔥 <b>Zaxira Bazada {cnt} ta tayyor lid kutmoqda!</b>\n\n"
        f"💵 1 ta lid narxi: <b>{format_uzs(tenant.overage_price)}</b>\n"
        f"💳 Jami to'lov: <b>{format_uzs(total)}</b>\n\n"
        f"To'lov qilingan soniyada barcha {cnt} ta lid asosiy Google Sheets jadvalingizga "
        f"<b>➕ QO'SHIMCHA LID</b> qatori ostiga ko'chiriladi!",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("buy:plan:"))
async def cb_buy_plan(call: CallbackQuery, state: FSMContext) -> None:
    plan_code = call.data.split(":")[2]
    spec = PLANS[plan_code]
    await state.set_state(PaymentFSM.waiting_receipt)
    await state.update_data(req_type="PLAN", plan_code=plan_code, amount_uzs=spec.price_uzs, reserve_count=0)

    pay_link = f"\n🔗 Click/Payme havola: {settings.CLICK_PAY_LINK}" if settings.CLICK_PAY_LINK else ""
    await call.message.edit_text(
        f"💳 <b>To'lov — {spec.name}</b>\n"
        f"Summa: <b>{format_uzs(spec.price_uzs)}</b>\n\n"
        f"Karta raqami: <code>{settings.PAYMENT_CARD_NUMBER}</code>\n"
        f"Egasi: <b>{settings.PAYMENT_CARD_HOLDER}</b>{pay_link}\n\n"
        f"📸 To'lovni amalga oshirib, <b>chek rasmini (skrinshotini)</b> shu yerga yuboring:"
    )


@router.callback_query(F.data == "buy:reserve")
async def cb_buy_reserve(call: CallbackQuery, state: FSMContext) -> None:
    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, call.from_user.id)
        pending = await get_pending_reserve_leads(db, tenant.id)
    if not pending:
        await call.answer("Zaxirada lid qolmagan.", show_alert=True)
        return
    cnt = len(pending)
    total = cnt * tenant.overage_price
    await state.set_state(PaymentFSM.waiting_receipt)
    await state.update_data(req_type="RESERVE", plan_code=None, amount_uzs=total, reserve_count=cnt)

    await call.message.edit_text(
        f"💳 <b>Zaxira Lidlarni Ochish ({cnt} ta)</b>\n"
        f"Summa: <b>{format_uzs(total)}</b>\n\n"
        f"Karta raqami: <code>{settings.PAYMENT_CARD_NUMBER}</code>\n"
        f"Egasi: <b>{settings.PAYMENT_CARD_HOLDER}</b>\n\n"
        f"📸 To'lov chekini (rasm) shu yerga yuboring:"
    )


@router.message(PaymentFSM.waiting_receipt, F.photo | F.document)
async def on_payment_receipt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id

    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_tg(db, message.from_user.id)
        pr = PaymentRequest(
            tenant_id=tenant.id,
            tg_user_id=message.from_user.id,
            req_type=data["req_type"],
            plan_code=data.get("plan_code"),
            reserve_count=data.get("reserve_count", 0),
            amount_uzs=data["amount_uzs"],
            receipt_file_id=file_id,
            status="PENDING",
        )
        db.add(pr)
        await db.commit()
        await db.refresh(pr)

    await state.clear()
    await message.answer(
        "✅ Chekingiz qabul qilindi! Admin tasdiqlashi bilan tizim avtomatik ochiladi (odatda 1-5 daqiqa).",
        reply_markup=main_menu_kb(tenant),
    )

    if settings.ADMIN_TG_ID:
        desc = (
            f"Paket: {data.get('plan_code')}"
            if data["req_type"] == "PLAN"
            else f"Zaxira Lidlar: {data.get('reserve_count')} ta"
        )
        admin_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"adm:ok:{pr.id}"),
                    InlineKeyboardButton(text="❌ Rad etish", callback_data=f"adm:no:{pr.id}"),
                ]
            ]
        )
        caption = (
            f"💰 <b>YANGI TO'LOV #{pr.id}</b>\n"
            f"🏢 Biznes: <b>{tenant.business_name}</b> (@{tenant.ig_username or '-'})\n"
            f"📦 Turi: <b>{desc}</b>\n"
            f"💵 Summa: <b>{format_uzs(pr.amount_uzs)}</b>"
        )
        if message.photo:
            await bot.send_photo(settings.ADMIN_TG_ID, file_id, caption=caption, reply_markup=admin_kb)
        else:
            await bot.send_document(settings.ADMIN_TG_ID, file_id, caption=caption, reply_markup=admin_kb)


# --- Admin 1-Click Payment Approval & /admin Dashboard ---

@router.callback_query(F.data.startswith("adm:"))
async def cb_admin_payment(call: CallbackQuery) -> None:
    if call.from_user.id != settings.ADMIN_TG_ID:
        await call.answer("Ruxsat yo'q", show_alert=True)
        return

    _, action, pr_id_str = call.data.split(":")
    pr_id = int(pr_id_str)

    async with AsyncSessionLocal() as db:
        pr = (await db.execute(select(PaymentRequest).where(PaymentRequest.id == pr_id))).scalar_one_or_none()
        if not pr or pr.status != "PENDING":
            await call.answer("Bu so'rov allaqachon ko'rib chiqilgan.", show_alert=True)
            return

        tenant = await get_tenant_by_id(db, pr.tenant_id)
        if action == "no":
            pr.status = "REJECTED"
            await db.commit()
            await bot.send_message(pr.tg_user_id, "❌ To'lov chekingiz tasdiqlanmadi. Admin bilan bog'laning.")
            try:
                await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n❌ RAD ETILDI")
            except Exception:
                pass
            return

        pr.status = "APPROVED"
        if pr.req_type == "PLAN" and pr.plan_code:
            await apply_plan_to_tenant(db, tenant, pr.plan_code)
            spec = PLANS[pr.plan_code]
            await bot.send_message(
                pr.tg_user_id,
                f"🎉 <b>To'lov tasdiqlandi!</b>\n"
                f"<b>{spec.name}</b> faollashtirildi va Reels izohlarini ovlash yoqildi!",
                reply_markup=main_menu_kb(tenant),
            )
        elif pr.req_type == "RESERVE":
            pending = await get_pending_reserve_leads(db, tenant.id)
            if pending:
                start_row = (await count_main_leads(db, tenant.id)) + 1
                payload = [
                    {
                        "created_at": l.created_at.strftime("%Y-%m-%d %H:%M"),
                        "username": l.customer_username,
                        "name": l.customer_name,
                        "phone": l.phone,
                        "qty": l.qty,
                        "media_id": l.media_id,
                    }
                    for l in pending
                ]
                if tenant.main_sheet_id:
                    await transfer_reserve_to_main(
                        tenant.main_sheet_id, tenant.reserve_sheet_id, start_row, payload
                    )
                for l in pending:
                    l.lead_type = "EXTRA_PAID"
                    l.is_transferred_to_main = True
                await db.commit()

                await bot.send_message(
                    pr.tg_user_id,
                    f"🎉 <b>{len(pending)} ta Zaxira Lid asosiy Google Sheets jadvalingizga ko'chirildi!</b>\n\n"
                    f"📊 Jadval: {tenant.main_sheet_url or ''}",
                    reply_markup=main_menu_kb(tenant),
                )
        await db.commit()

    try:
        await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ TASDIQLANDI")
    except Exception:
        pass


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if message.from_user.id != settings.ADMIN_TG_ID:
        return
    async with AsyncSessionLocal() as db:
        t_cnt = (await db.execute(select(func.count(Tenant.id)))).scalar() or 0
        l_cnt = (await db.execute(select(func.count(Lead.id)))).scalar() or 0
        p_cnt = (
            await db.execute(
                select(func.count(PaymentRequest.id)).where(PaymentRequest.status == "PENDING")
            )
        ).scalar() or 0

    await message.answer(
        f"🛡 <b>C2 SaaS — Admin Panel</b>\n\n"
        f"🏢 Jami bizneslar: <b>{t_cnt}</b>\n"
        f"🎯 Jami yig'ilgan lidlar: <b>{l_cnt}</b>\n"
        f"⚙️ Faol 10s navbatlar: <b>{queue_manager.active_workers_count()}</b>\n"
        f"💳 Kutilayotgan to'lovlar: <b>{p_cnt}</b>"
    )
