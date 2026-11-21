import datetime
from typing import Optional, List
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from config import settings, PLANS, SCRIPT_TEMPLATES


def _normalize_db_url(raw_url: str) -> str:
    """Convert Render/Neon/Supabase postgres:// URL into SQLAlchemy asyncpg URL."""
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if raw_url.startswith("postgresql://") and "+asyncpg" not in raw_url:
        raw_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "sslmode=" in raw_url:
        base, _, query = raw_url.partition("?")
        parts = [q for q in query.split("&") if q and not q.startswith(("sslmode=", "channel_binding="))]
        parts.append("ssl=require")
        raw_url = base + "?" + "&".join(parts)
    return raw_url


DATABASE_URL = _normalize_db_url(settings.DATABASE_URL)

engine_kwargs = {"echo": False, "future": True}
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

engine = create_async_engine(DATABASE_URL, **engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    business_name = Column(String(200), nullable=False)
    owner_gmail = Column(String(255), nullable=False)

    # Instagram connection (1 subscription = 1 IG Business ID)
    ig_user_id = Column(String(64), unique=True, nullable=True, index=True)
    ig_username = Column(String(120), nullable=True)
    page_access_token = Column(Text, nullable=True)

    # Plan & Quota
    mode = Column(String(10), default="CPL", nullable=False)  # "CP" or "CPL"
    plan_code = Column(String(32), default="FREE_CPL", nullable=False)
    leads_limit = Column(Integer, default=15, nullable=False)
    bonus_limit = Column(Integer, default=0, nullable=False)
    leads_used = Column(Integer, default=0, nullable=False)
    overage_price = Column(Integer, default=2000, nullable=False)

    contacts_limit = Column(Integer, default=100, nullable=False)
    contacts_used = Column(Integer, default=0, nullable=False)
    queue_delay_sec = Column(Integer, default=10, nullable=False)

    # Auto-stop switch: automatically turns False when leads_used >= leads_limit + bonus_limit
    comment_active = Column(Boolean, default=True, nullable=False)

    # Separate Google Sheets (Main = Viewer for client, Reserve = Private only for admin)
    main_sheet_id = Column(String(128), nullable=True)
    main_sheet_url = Column(Text, nullable=True)
    reserve_sheet_id = Column(String(128), nullable=True)
    reserve_sheet_url = Column(Text, nullable=True)

    # Customizable Scripts
    comment_reply_text = Column(Text, default=SCRIPT_TEMPLATES["shop"]["comment_reply"])
    dm_welcome_text = Column(Text, default=SCRIPT_TEMPLATES["shop"]["dm_welcome"])
    dm_link_url = Column(Text, default="https://t.me/")
    ask_name_text = Column(Text, default=SCRIPT_TEMPLATES["shop"]["ask_name"])
    ask_phone_text = Column(Text, default=SCRIPT_TEMPLATES["shop"]["ask_phone"])
    ask_qty_text = Column(Text, default=SCRIPT_TEMPLATES["shop"]["ask_qty"])
    done_text = Column(Text, default=SCRIPT_TEMPLATES["shop"]["done"])

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ReelsTarget(Base):
    __tablename__ = "reels_targets"
    __table_args__ = (UniqueConstraint("tenant_id", "media_id", name="uq_tenant_media"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    media_id = Column(String(128), nullable=False, index=True)
    permalink = Column(Text, nullable=True)
    caption_preview = Column(String(255), nullable=True)
    keyword_mode = Column(String(16), default="ALL", nullable=False)  # "ALL" or "KEYWORDS"
    keywords_csv = Column(Text, default="")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class UsedTrial(Base):
    """Anti-fraud lock: 1 IG Business Account can only ever claim Free Trial once."""
    __tablename__ = "used_trials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ig_user_id = Column(String(64), unique=True, nullable=False, index=True)
    tg_user_id = Column(BigInteger, nullable=False)
    claimed_at = Column(DateTime, default=utcnow)


class ProcessedComment(Base):
    """Anti-spam: 1 commenter per Reel only triggers 1 reply + 1 DM."""
    __tablename__ = "processed_comments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "media_id", "commenter_ig_id", name="uq_commenter_reel"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    media_id = Column(String(128), nullable=False)
    commenter_ig_id = Column(String(64), nullable=False)
    comment_id = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=utcnow)


class MonthlyContact(Base):
    """Unique active contact tracker per month for C+P mode."""
    __tablename__ = "monthly_contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_ig_id", "year_month", name="uq_monthly_contact"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_ig_id = Column(String(64), nullable=False)
    year_month = Column(String(7), nullable=False)  # YYYY-MM
    created_at = Column(DateTime, default=utcnow)


class DMSession(Base):
    """Persistent Instagram DM Funnel FSM state per customer."""
    __tablename__ = "dm_sessions"
    __table_args__ = (UniqueConstraint("tenant_id", "customer_ig_id", name="uq_dm_session"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_ig_id = Column(String(64), nullable=False, index=True)
    customer_username = Column(String(120), default="")
    media_id = Column(String(128), default="")
    step = Column(String(32), default="WAIT_CONFIRM", nullable=False)
    temp_name = Column(String(200), default="")
    temp_phone = Column(String(64), default="")
    temp_qty = Column(String(200), default="")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Lead(Base):
    """Captured leads: MAIN, BONUS, RESERVE (unpaid overage), EXTRA_PAID (transferred)."""
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_ig_id = Column(String(64), nullable=False)
    customer_username = Column(String(120), default="")
    customer_name = Column(String(200), nullable=False)
    phone = Column(String(32), nullable=False, index=True)
    qty = Column(String(200), default="")
    media_id = Column(String(128), default="")
    lead_type = Column(String(24), nullable=False)  # MAIN | BONUS | RESERVE | EXTRA_PAID
    is_transferred_to_main = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class PaymentRequest(Base):
    __tablename__ = "payment_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    tg_user_id = Column(BigInteger, nullable=False)
    req_type = Column(String(24), nullable=False)  # PLAN | RESERVE
    plan_code = Column(String(32), nullable=True)
    reserve_count = Column(Integer, default=0)
    amount_uzs = Column(Integer, nullable=False)
    receipt_file_id = Column(Text, nullable=True)
    status = Column(String(24), default="PENDING", nullable=False)  # PENDING | APPROVED | REJECTED
    created_at = Column(DateTime, default=utcnow)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_tenant_by_tg(session: AsyncSession, tg_user_id: int) -> Optional[Tenant]:
    res = await session.execute(select(Tenant).where(Tenant.tg_user_id == tg_user_id))
    return res.scalar_one_or_none()


async def get_tenant_by_ig(session: AsyncSession, ig_user_id: str) -> Optional[Tenant]:
    res = await session.execute(select(Tenant).where(Tenant.ig_user_id == str(ig_user_id)))
    return res.scalar_one_or_none()


async def get_tenant_by_id(session: AsyncSession, tenant_id: int) -> Optional[Tenant]:
    res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    return res.scalar_one_or_none()


async def get_pending_reserve_leads(session: AsyncSession, tenant_id: int) -> List[Lead]:
    res = await session.execute(
        select(Lead)
        .where(
            Lead.tenant_id == tenant_id,
            Lead.lead_type == "RESERVE",
            Lead.is_transferred_to_main == False,  # noqa: E712
        )
        .order_by(Lead.id.asc())
    )
    return list(res.scalars().all())


async def count_main_leads(session: AsyncSession, tenant_id: int) -> int:
    res = await session.execute(
        select(func.count(Lead.id)).where(
            Lead.tenant_id == tenant_id,
            Lead.is_transferred_to_main == True,  # noqa: E712
        )
    )
    return int(res.scalar() or 0)


async def is_duplicate_phone(session: AsyncSession, tenant_id: int, phone: str) -> bool:
    res = await session.execute(
        select(Lead.id).where(Lead.tenant_id == tenant_id, Lead.phone == phone).limit(1)
    )
    return res.scalar_one_or_none() is not None


async def apply_plan_to_tenant(session: AsyncSession, tenant: Tenant, plan_code: str) -> None:
    spec = PLANS[plan_code]
    tenant.plan_code = spec.code
    tenant.mode = spec.mode
    tenant.queue_delay_sec = spec.queue_delay_sec
    tenant.comment_active = True

    if spec.mode == "CPL":
        tenant.leads_limit = spec.leads_limit
        tenant.bonus_limit = spec.bonus_limit
        tenant.leads_used = 0
        tenant.overage_price = spec.overage_price
    else:
        tenant.contacts_limit = spec.contacts_limit
        tenant.contacts_used = 0

    await session.commit()
