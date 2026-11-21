import logging
import re
from typing import Awaitable, Callable, Optional

from sqlalchemy import select

from config import POSITIVE_WORDS, format_uzs
from database import (
    AsyncSessionLocal,
    DMSession,
    Lead,
    Tenant,
    count_main_leads,
    get_pending_reserve_leads,
    get_tenant_by_ig,
    is_duplicate_phone,
)
from instagram_api import ig_api
from sheets_manager import append_main_lead, append_reserve_lead

logger = logging.getLogger("c2.funnel")

NotifyCallback = Callable[[int, str, Optional[str]], Awaitable[None]]
_notify_cb: Optional[NotifyCallback] = None


def set_notify_callback(cb: NotifyCallback) -> None:
    global _notify_cb
    _notify_cb = cb


async def _notify(tg_user_id: int, text: str, button_action: Optional[str] = None) -> None:
    if _notify_cb:
        try:
            await _notify_cb(tg_user_id, text, button_action)
        except Exception:
            logger.exception("Telegram notify failed for %s", tg_user_id)


def normalize_uz_phone(raw_text: str) -> Optional[str]:
    """
    Validate and normalize Uzbekistan phone numbers:
      +998901234567 / 998 90 123-45-67 / 90 123 45 67 -> +998901234567
    Returns None if invalid.
    """
    digits = re.sub(r"\D", "", raw_text or "")
    if len(digits) == 9 and digits[0] in {"9", "8", "7", "6", "5", "3", "2"}:
        digits = "998" + digits
    elif len(digits) == 12 and digits.startswith("998"):
        pass
    else:
        return None

    operator = digits[3:5]
    valid_prefixes = {
        "90", "91", "93", "94", "95", "97", "98", "99",
        "88", "77", "71", "70", "55", "50", "33", "20",
    }
    if operator not in valid_prefixes:
        return None
    return f"+{digits}"


def is_positive_reply(text: str) -> bool:
    clean = (text or "").strip().lower()
    if not clean:
        return False
    tokens = clean.split()
    for word in POSITIVE_WORDS:
        if clean == word or word in tokens:
            return True
    return False


async def handle_incoming_dm(
    ig_business_id: str, sender_id: str, message_text: str
) -> None:
    """
    Process incoming Direct Message for C+P+L funnel.
    Supports:
      - 1-step Quick Lead (DM 1 -> Phone -> Save to Google Sheets)
      - 2-step Full Order (DM 1 -> Phone -> DM 2 [Qty/Note] -> Save to Google Sheets)
    """
    if not sender_id or sender_id == ig_business_id:
        return

    text = (message_text or "").strip()
    if not text:
        return

    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_ig(db, ig_business_id)
        if not tenant or not tenant.page_access_token:
            return

        if tenant.mode != "CPL":
            return

        res = await db.execute(
            select(DMSession).where(
                DMSession.tenant_id == tenant.id,
                DMSession.customer_ig_id == str(sender_id),
            )
        )
        sess = res.scalar_one_or_none()
        if not sess or sess.step == "DONE":
            return

        # STEP 1 (WAIT_CONFIRM / WAIT_PHONE): Capture phone immediately or prompt for phone
        if sess.step in {"WAIT_CONFIRM", "WAIT_PHONE"}:
            phone = normalize_uz_phone(text)
            if not phone:
                sess.step = "WAIT_PHONE"
                await db.commit()
                prompt = (
                    tenant.ask_phone_text
                    if is_positive_reply(text)
                    else "Bog'lanishimiz uchun O'zbekiston telefon raqamingizni yozing (masalan: +998901234567):"
                )
                await ig_api.send_dm(tenant.ig_user_id, sender_id, prompt, tenant.page_access_token)
                return

            sess.temp_phone = phone
            if not sess.temp_name:
                sess.temp_name = f"@{sess.customer_username}" if sess.customer_username else "Instagram Mijoz"

            # If DM 2-xabar is enabled -> ask 2nd question; otherwise finish immediately!
            if tenant.ask_qty_enabled:
                sess.step = "WAIT_QTY"
                await db.commit()
                msg = tenant.ask_qty_text.replace("{name}", sess.temp_name).replace("{phone}", phone)
                await ig_api.send_dm(tenant.ig_user_id, sender_id, msg, tenant.page_access_token)
                return

            sess.temp_qty = "-"
            sess.step = "DONE"
            done_msg = (
                tenant.done_text.replace("{name}", sess.temp_name)
                .replace("{phone}", sess.temp_phone)
                .replace("{qty}", "-")
            )
            await ig_api.send_dm(tenant.ig_user_id, sender_id, done_msg, tenant.page_access_token)
            await _record_completed_lead(db, tenant, sess)
            return

        # STEP 2 (WAIT_QTY — DM 2-xabar): Capture note/quantity & finalize
        if sess.step == "WAIT_QTY":
            sess.temp_qty = text[:180]
            sess.step = "DONE"

            done_msg = (
                tenant.done_text.replace("{name}", sess.temp_name)
                .replace("{phone}", sess.temp_phone)
                .replace("{qty}", sess.temp_qty)
            )
            await ig_api.send_dm(tenant.ig_user_id, sender_id, done_msg, tenant.page_access_token)

            await _record_completed_lead(db, tenant, sess)


async def _record_completed_lead(db, tenant: Tenant, sess: DMSession) -> None:
    """
    Core C2 Guaranteed Lead Accounting Engine:
    1. Duplicate phone check (client is NEVER charged twice for same phone).
    2. leads_used < leads_limit -> MAIN lead -> Main Sheet.
    3. leads_used < leads_limit + bonus_limit -> BONUS lead -> Main Sheet.
    4. Already exhausted (late DM responder) -> RESERVE lead -> Private Reserve Sheet.
    """
    dup = await is_duplicate_phone(db, tenant.id, sess.temp_phone)
    if dup:
        await db.commit()
        logger.info("Duplicate phone %s for tenant %s — not double-charged", sess.temp_phone, tenant.id)
        return

    total_allowed = tenant.leads_limit + tenant.bonus_limit

    if tenant.leads_used < total_allowed:
        is_bonus = tenant.leads_used >= tenant.leads_limit
        lead_type = "BONUS" if is_bonus else "MAIN"

        lead = Lead(
            tenant_id=tenant.id,
            customer_ig_id=sess.customer_ig_id,
            customer_username=sess.customer_username,
            customer_name=sess.temp_name,
            phone=sess.temp_phone,
            qty=sess.temp_qty,
            media_id=sess.media_id,
            lead_type=lead_type,
            is_transferred_to_main=True,
        )
        db.add(lead)
        tenant.leads_used += 1

        just_hit_main_end = (tenant.leads_used == tenant.leads_limit) and (tenant.bonus_limit > 0)
        just_hit_total_end = tenant.leads_used >= total_allowed
        if just_hit_total_end:
            tenant.comment_active = False

        await db.commit()

        row_num = await count_main_leads(db, tenant.id)
        if tenant.main_sheet_id:
            await append_main_lead(
                main_sheet_id=tenant.main_sheet_id,
                row_number=row_num,
                username=sess.customer_username,
                name=sess.temp_name,
                phone=sess.temp_phone,
                qty=sess.temp_qty,
                media_id=sess.media_id,
                lead_type=lead_type,
            )

        badge = "🎁 BONUS LID" if is_bonus else "✅ YANGI LID"
        extra_line = f"\n📝 Izoh/Miqdor: {sess.temp_qty}" if sess.temp_qty and sess.temp_qty != "-" else ""
        await _notify(
            tenant.tg_user_id,
            (
                f"{badge} (#{tenant.leads_used}/{total_allowed})\n"
                f"📞 Tel: <b>{sess.temp_phone}</b>"
                f"{extra_line}\n"
                f"📱 IG: @{sess.customer_username or sess.customer_ig_id}"
            ),
            None,
        )

        if just_hit_main_end:
            await _notify(
                tenant.tg_user_id,
                (
                    f"🎉 <b>Tabriklaymiz! {tenant.leads_limit} ta asosiy lid to'liq yig'ildi!</b>\n\n"
                    f"Hamkorligimiz uchun sizga kompaniyamiz nomidan <b>+{tenant.bonus_limit} ta BONUS lid</b> "
                    f"taqdim etildi (jami {total_allowed} tagacha bonus davom etadi)!"
                ),
                None,
            )
        elif just_hit_total_end:
            await _notify(
                tenant.tg_user_id,
                (
                    f"🏁 <b>Paketingiz ({tenant.leads_limit} asosiy + {tenant.bonus_limit} bonus = {total_allowed} lid) "
                    f"to'liq yig'ildi!</b>\n\n"
                    f"⛔️ Yangi Reels izohlariga javob berish avtomatik to'xtatildi.\n"
                    f"💡 Avval Direct'ga kirgan eski mijozlar raqam qoldirsa, ular <b>Zaxira Baza</b>ga "
                    f"yig'ib boriladi va siz ularni donalab ({format_uzs(tenant.overage_price)}/lid) ochib olishingiz mumkin.\n\n"
                    f"Davom ettirish uchun yangi paket tanlang:"
                ),
                "open_tariffs",
            )
    else:
        lead = Lead(
            tenant_id=tenant.id,
            customer_ig_id=sess.customer_ig_id,
            customer_username=sess.customer_username,
            customer_name=sess.temp_name,
            phone=sess.temp_phone,
            qty=sess.temp_qty,
            media_id=sess.media_id,
            lead_type="RESERVE",
            is_transferred_to_main=False,
        )
        db.add(lead)
        await db.commit()

        if tenant.reserve_sheet_id:
            await append_reserve_lead(
                reserve_sheet_id=tenant.reserve_sheet_id,
                username=sess.customer_username,
                name=sess.temp_name,
                phone=sess.temp_phone,
                qty=sess.temp_qty,
                media_id=sess.media_id,
            )

        pending = await get_pending_reserve_leads(db, tenant.id)
        cnt = len(pending)
        total_price = cnt * tenant.overage_price
        await _notify(
            tenant.tg_user_id,
            (
                f"🔥 <b>Zaxira Bazaga yangi issiq lid tushdi!</b>\n\n"
                f"Eski Direct suhbatlardan jami <b>{cnt} ta tayyor mijoz</b> raqamini qoldirdi.\n"
                f"Yangi katta paket olmasdan turib, shu {cnt} ta lidni "
                f"<b>{cnt} × {format_uzs(tenant.overage_price)} = {format_uzs(total_price)}</b> evaziga "
                f"1 soniyada asosiy Google Sheets jadvalingizga ko'chirib olishingiz mumkin!"
            ),
            "buy_reserve",
        )