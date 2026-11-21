import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from bot import bot, dp
from config import PLANS, settings
from database import (
    AsyncSessionLocal,
    apply_plan_to_tenant,
    count_main_leads,
    get_pending_reserve_leads,
    get_tenant_by_id,
    init_db,
)
from funnel_engine import handle_incoming_dm
from instagram_api import ig_api
from queue_worker import CommentJob, queue_manager
from sheets_manager import transfer_reserve_to_main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("c2.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized.")

    bot_task = None
    if settings.BOT_TOKEN and "DUMMY" not in settings.BOT_TOKEN:
        async def _poll():
            try:
                await dp.start_polling(bot, handle_signals=False, drop_pending_updates=True)
            except Exception as e:
                logger.exception("TELEGRAM BOT XATOSI: %s", e)
        bot_task = asyncio.create_task(_poll())
        logger.info("Telegram SaaS Bot polling started.")
    else:
        logger.warning("BOT_TOKEN missing — running FastAPI webhook server only.")

    yield

    logger.info("Shutting down C2 Insta-Lid SaaS...")
    if bot_task:
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
    await queue_manager.shutdown()
    await ig_api.close()
    await bot.session.close()


app = FastAPI(
    title="C2 — Insta-Lid CRM SaaS",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/")
@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Keep-alive endpoint for Render.com + cron-job.org pings."""
    return {
        "status": "ok",
        "service": "c2-insta-lid-saas",
        "active_queues": queue_manager.active_workers_count(),
    }


@app.get("/webhook")
async def verify_meta_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    """Meta Instagram Graph API Webhook verification handshake."""
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Invalid verify token")


def _verify_signature(body: bytes, signature: str) -> bool:
    if not settings.META_APP_SECRET:
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        settings.META_APP_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/webhook")
async def receive_meta_webhook(
    request: Request,
    x_hub_signature_256: str = Header(default=""),
) -> Dict[str, str]:
    """
    Universal Multi-Tenant Meta Webhook endpoint.
    Routes every comment & Direct message by `entry.id` (ig_business_id).
    Returns instant 200 OK while background workers handle 10s queues & DM funnels.
    """
    raw_body = await request.body()
    if not _verify_signature(raw_body, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Invalid X-Hub-Signature-256")

    payload = await request.json()
    if payload.get("object") != "instagram":
        return {"status": "ignored"}

    for entry in payload.get("entry", []):
        ig_business_id = str(entry.get("id", ""))
        if not ig_business_id:
            continue

        # 1. Comment Events -> Per-Tenant 10-second Anti-Ban Queue
        for change in entry.get("changes", []):
            if change.get("field") == "comments":
                val = change.get("value", {})
                comment_id = str(val.get("id", ""))
                media_id = str(val.get("media", {}).get("id", ""))
                sender = val.get("from", {})
                commenter_id = str(sender.get("id", ""))
                commenter_username = str(sender.get("username", ""))
                text = str(val.get("text", ""))

                if comment_id and media_id and commenter_id:
                    queue_manager.enqueue(
                        CommentJob(
                            ig_business_id=ig_business_id,
                            media_id=media_id,
                            comment_id=comment_id,
                            commenter_id=commenter_id,
                            commenter_username=commenter_username,
                            comment_text=text,
                        )
                    )

        # 2. Direct Message Events -> C+P+L Lead Capture Funnel
        for msg_event in entry.get("messaging", []):
            sender_id = str(msg_event.get("sender", {}).get("id", ""))
            message_obj = msg_event.get("message", {})
            if message_obj.get("is_echo"):
                continue
            text = message_obj.get("text", "")
            if sender_id and text:
                asyncio.create_task(handle_incoming_dm(ig_business_id, sender_id, text))

    return {"status": "ok"}


@app.post("/api/payment/webhook")
async def payment_auto_billing_webhook(
    request: Request,
    x_webhook_secret: str = Header(default=""),
) -> Dict[str, Any]:
    """
    Auto-Billing endpoint for Click / Payme Merchant API integration.
    Supports both PLAN activation and RESERVE leads transfer:
      {"tenant_id": 1, "req_type": "PLAN", "plan_code": "CPL_250"}
      {"tenant_id": 1, "req_type": "RESERVE"}
    """
    if x_webhook_secret != settings.PAYMENT_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    data = await request.json()
    tenant_id = int(data.get("tenant_id", 0))
    req_type = str(data.get("req_type", "PLAN")).upper()
    plan_code = str(data.get("plan_code", ""))

    async with AsyncSessionLocal() as db:
        tenant = await get_tenant_by_id(db, tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        if req_type == "PLAN":
            if plan_code not in PLANS:
                raise HTTPException(status_code=400, detail="Unknown plan_code")
            await apply_plan_to_tenant(db, tenant, plan_code)
            return {"status": "activated", "plan": plan_code}

        if req_type == "RESERVE":
            pending = await get_pending_reserve_leads(db, tenant.id)
            if not pending:
                return {"status": "empty", "transferred": 0}
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
            return {"status": "transferred", "transferred": len(pending)}

    raise HTTPException(status_code=400, detail="Invalid req_type")
