import asyncio
import datetime
import logging
from dataclasses import dataclass
from typing import Dict

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from config import settings
from database import (
    AsyncSessionLocal,
    DMSession,
    MonthlyContact,
    ProcessedComment,
    ReelsTarget,
    get_tenant_by_ig,
)
from funnel_engine import _notify
from instagram_api import ig_api

logger = logging.getLogger("c2.queue")


@dataclass
class CommentJob:
    ig_business_id: str
    media_id: str
    comment_id: str
    commenter_id: str
    commenter_username: str
    comment_text: str


class PerTenantQueueManager:
    """
    Dedicated asyncio.Queue + background worker per Instagram Business Account.
    Guarantees 10-second Anti-Ban delay inside each account while running
    50+ businesses in parallel without blocking one another.
    """

    def __init__(self) -> None:
        self._queues: Dict[str, asyncio.Queue] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    def enqueue(self, job: CommentJob) -> None:
        key = str(job.ig_business_id)
        if key not in self._queues:
            self._queues[key] = asyncio.Queue()
            self._tasks[key] = asyncio.create_task(self._worker(key))
            logger.info("Started dedicated Anti-Ban worker for IG %s", key)
        self._queues[key].put_nowait(job)

    def active_workers_count(self) -> int:
        return len(self._tasks)

    async def shutdown(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        self._queues.clear()

    async def _worker(self, ig_business_id: str) -> None:
        queue = self._queues[ig_business_id]
        while True:
            job: CommentJob = await queue.get()
            delay = 0
            try:
                delay = await self._process_comment(job)
            except Exception:
                logger.exception("Error processing comment %s for IG %s", job.comment_id, ig_business_id)
                delay = settings.DEFAULT_QUEUE_DELAY
            finally:
                queue.task_done()
            # Sleep ONLY when a real Meta API reply/DM was actually sent
            if delay > 0:
                await asyncio.sleep(max(5, delay))

    async def _process_comment(self, job: CommentJob) -> int:
        async with AsyncSessionLocal() as db:
            tenant = await get_tenant_by_ig(db, job.ig_business_id)
            if not tenant or not tenant.page_access_token:
                return 0

            if str(job.commenter_id) == str(tenant.ig_user_id):
                return 0

            if not tenant.comment_active:
                logger.info("Tenant %s comment_active=False — skipping new comment", tenant.id)
                return 0

            res = await db.execute(
                select(ReelsTarget).where(
                    ReelsTarget.tenant_id == tenant.id,
                    ReelsTarget.media_id == str(job.media_id),
                    ReelsTarget.is_active == True,  # noqa: E712
                )
            )
            reel = res.scalar_one_or_none()
            if not reel:
                return 0

            if reel.keyword_mode == "KEYWORDS" and reel.keywords_csv:
                kws = [k.strip().lower() for k in reel.keywords_csv.split(",") if k.strip()]
                low_text = (job.comment_text or "").lower()
                if kws and not any(kw in low_text for kw in kws):
                    return 0

            existing_proc = await db.execute(
                select(ProcessedComment.id).where(
                    ProcessedComment.tenant_id == tenant.id,
                    ProcessedComment.media_id == str(job.media_id),
                    ProcessedComment.commenter_ig_id == str(job.commenter_id),
                )
            )
            if existing_proc.scalar_one_or_none() is not None:
                return 0

            if tenant.mode == "CP":
                ym = datetime.datetime.now().strftime("%Y-%m")
                mc_res = await db.execute(
                    select(MonthlyContact.id).where(
                        MonthlyContact.tenant_id == tenant.id,
                        MonthlyContact.customer_ig_id == str(job.commenter_id),
                        MonthlyContact.year_month == ym,
                    )
                )
                already_counted = mc_res.scalar_one_or_none() is not None

                if not already_counted:
                    is_unlimited = tenant.plan_code == "CP_UNLIM"
                    if not is_unlimited and tenant.contacts_used >= tenant.contacts_limit:
                        tenant.comment_active = False
                        await db.commit()
                        await _notify(
                            tenant.tg_user_id,
                            (
                                f"⚠️ <b>Oylik DM limitingiz ({tenant.contacts_limit} kontakt) tugadi!</b>\n"
                                f"Yangi izohlarga javob berish to'xtatildi. Davom ettirish uchun tarifni yangilang:"
                            ),
                            "open_tariffs",
                        )
                        return 0

                    db.add(
                        MonthlyContact(
                            tenant_id=tenant.id,
                            customer_ig_id=str(job.commenter_id),
                            year_month=ym,
                        )
                    )
                    tenant.contacts_used += 1

            db.add(
                ProcessedComment(
                    tenant_id=tenant.id,
                    media_id=str(job.media_id),
                    commenter_ig_id=str(job.commenter_id),
                    comment_id=str(job.comment_id),
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                return 0

            # 1. Public Comment Reply
            await ig_api.reply_to_comment(
                job.comment_id, tenant.comment_reply_text, tenant.page_access_token
            )

            # 2. Private Direct Message
            dm_text = tenant.dm_welcome_text.replace("{link}", tenant.dm_link_url or "")
            ok, _ = await ig_api.send_private_reply_to_comment(
                tenant.ig_user_id, job.comment_id, dm_text, tenant.page_access_token
            )

            # 3. If C+P+L mode, open/reset DM Funnel Session for this commenter
            if ok and tenant.mode == "CPL":
                sess_res = await db.execute(
                    select(DMSession).where(
                        DMSession.tenant_id == tenant.id,
                        DMSession.customer_ig_id == str(job.commenter_id),
                    )
                )
                sess = sess_res.scalar_one_or_none()
                if sess:
                    sess.step = "WAIT_CONFIRM"
                    sess.media_id = str(job.media_id)
                    sess.customer_username = job.commenter_username or sess.customer_username
                else:
                    db.add(
                        DMSession(
                            tenant_id=tenant.id,
                            customer_ig_id=str(job.commenter_id),
                            customer_username=job.commenter_username or "",
                            media_id=str(job.media_id),
                            step="WAIT_CONFIRM",
                        )
                    )
                await db.commit()

            return tenant.queue_delay_sec


queue_manager = PerTenantQueueManager()
