"""
Payment utilities:
- VietQR image generation via vietqr.io
- Transaction matching (ported from qr_example.py)
- Periodic payment check job (check_payments) + shared order confirmation
"""
import asyncio
import logging
import unicodedata
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import httpx
import resvg_py
from sqlalchemy import select, update

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.subscription import Subscription
from app.utils.plan_loader import get_plan
from app.utils.invite import create_single_use_invite
from app.utils.order import safe_html

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text normalization helpers (ported from qr_example.py)
# ---------------------------------------------------------------------------

def _normalize_text(value: Any) -> str:
    text = str(value or "").lower().replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _collapse(s: str) -> str:
    return " ".join((s or "").split())


def _to_loose(s: str) -> str:
    normalized = _normalize_text(s)
    converted = "".join(
        ch if (ch.isalnum() or ch in {"_", " "}) else " "
        for ch in normalized
    )
    return _collapse(converted)


def _memo_candidates(memo: str) -> set[str]:
    """
    Build a set of normalized match candidates from the transfer memo.
    Matches strict, loose, without-@ variants and the leading ID+username pair.
    """
    result: set[str] = set()
    strict = _collapse(_normalize_text(memo))
    if strict:
        result.add(strict)
    without_at = _collapse(strict.replace("@", " "))
    if without_at:
        result.add(without_at)
    loose = _to_loose(memo)
    if loose:
        result.add(loose)
    tokens = without_at.split()
    if len(tokens) >= 2 and tokens[0].isdigit():
        result.add(tokens[0])
        result.add(f"{tokens[0]} {tokens[1]}")
    return {c for c in result if c}


def _to_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Admin notification
# ---------------------------------------------------------------------------

async def _notify_admins_new_order(bot, order: Order, username: str | None) -> None:
    """Send a new-order alert to all configured admin IDs."""
    async with AsyncSessionLocal() as _s:
        plan = await get_plan(_s, order.plan_code) or {}
    name_str = f"@{username}" if username else f"id:{order.user_id}"
    text = (
        "🔔 <b>Đơn hàng mới / New order</b>\n\n"
        f"👤 User: {name_str} (<code>{order.user_id}</code>)\n"
        f"{plan.get('emoji','')} Gói / Plan: <b>{plan.get('name', order.plan_code)}</b>\n"
        f"💰 Số tiền: <b>{order.amount:,}đ</b>\n"
        f"🔖 Mã đơn: <code>{order.order_code}</code>\n"
        f"📝 Nội dung CK: <code>{order.transfer_description}</code>"
    )
    await _send_to_admins(bot, text)


async def _send_to_admins(bot, text: str) -> None:
    for admin_id in settings.admin_id_list:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as exc:
            logger.warning("admin alert failed", extra={"admin_id": admin_id, "error": str(exc)})


# ---------------------------------------------------------------------------
# Sieuthicode API
# ---------------------------------------------------------------------------

async def fetch_transactions() -> list[dict[str, Any]]:
    """Fetch the bank transaction history from sieuthicode API."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            settings.SIEUTHICODE_API_URL,
            headers={"Cookie": settings.SIEUTHICODE_COOKIE},
        )
        resp.raise_for_status()
    data = resp.json()
    # An expired cookie still answers 200, so trust only an explicit success payload.
    if data.get("status") != "success" or "transactions" not in data:
        raise RuntimeError(f"sieuthicode error: {str(data.get('message') or data)[:200]}")
    return data["transactions"]


def find_match(
    transactions: list[dict[str, Any]],
    *,
    order_code: str,
    amount: int,
    used_ids: set[str],
) -> Optional[dict[str, Any]]:
    """
    Find the first transaction that:
    - has not already paid another order (not in used_ids)
    - has type == "IN"
    - has amount matching the order amount
    - has description containing the order_code (unique per order)
    """
    order_code_lower = order_code.lower()
    for tx in transactions:
        tx_id = str(tx.get("transactionID", "")).strip()
        if tx_id and tx_id in used_ids:
            continue
        if _to_int(tx.get("amount")) != amount:
            continue
        tx_type = _normalize_text(tx.get("type", ""))
        if tx_type and tx_type != "in":
            continue
        desc_raw = str(tx.get("description", "") or "")
        if order_code_lower in desc_raw.lower():
            return tx
    return None


# ---------------------------------------------------------------------------
# VietQR image
# ---------------------------------------------------------------------------

async def generate_vietqr_image(amount: int, memo: str) -> bytes:
    """
    Download a VietQR payment QR image from vietqr.io.
    Returns raster image bytes (PNG when vietqr.io serves SVG).
    """
    url = settings.VIETQR_IMAGE_TEMPLATE.format(
        bank_id=settings.SIEUTHICODE_BANK_ID,
        account_no=settings.BANK_ACCOUNT_NUMBER,
    )
    query = (
        f"amount={amount}"
        f"&addInfo={quote_plus(memo)}"
        f"&accountName={quote_plus(settings.BANK_ACCOUNT_NAME)}"
    )
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(f"{url}?{query}")
        resp.raise_for_status()
    # Since ~2026-10 img.vietqr.io redirects .jpg/.png to .svg; Telegram photos need a raster image.
    if "svg" in resp.headers.get("content-type", ""):
        return await asyncio.to_thread(
            resvg_py.svg_to_bytes,
            svg_string=resp.text,
            zoom=2,
            # SVG hardcodes Arial; Linux servers usually only have DejaVu (apt: fonts-dejavu-core).
            style_sheet='text{font-family:Arial,"DejaVu Sans",sans-serif}',
        )
    return resp.content


# ---------------------------------------------------------------------------
# Subscription activation (with stacking)
# ---------------------------------------------------------------------------

async def activate_subscription(order: Order, session) -> Subscription:
    """
    Mark the order as paid and extend/create a Subscription.
    If the user already has an active subscription, extends expires_at in-place (no new row).
    Otherwise creates a new row.
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == order.user_id)
        .where(Subscription.is_active.is_(True))
        .where(Subscription.expires_at > now)
        .order_by(Subscription.expires_at.desc())
        .limit(1)
    )
    current_sub = result.scalar_one_or_none()

    plan = await get_plan(session, order.plan_code)
    if not plan:
        raise ValueError(f"Plan not found: {order.plan_code}")

    if current_sub:
        # Extend existing subscription in-place — no new row
        old_expires = current_sub.expires_at
        current_sub.expires_at = current_sub.expires_at + timedelta(days=plan["days"])
        current_sub.plan_code = order.plan_code
        sub = current_sub
        logger.info(
            "subscription extended",
            extra={
                "user_id": order.user_id,
                "order_code": order.order_code,
                "plan": order.plan_code,
                "old_expires_at": old_expires.isoformat(),
                "new_expires_at": sub.expires_at.isoformat(),
            },
        )
    else:
        # No active sub — create a new row
        sub = Subscription(
            user_id=order.user_id,
            plan_code=order.plan_code,
            started_at=now,
            expires_at=now + timedelta(days=plan["days"]),
            is_active=True,
            order_id=order.id,
        )
        session.add(sub)
        logger.info(
            "subscription created",
            extra={
                "user_id": order.user_id,
                "order_code": order.order_code,
                "plan": order.plan_code,
                "expires_at": sub.expires_at.isoformat(),
            },
        )

    order.status = "paid"
    order.paid_at = now
    return sub


# ---------------------------------------------------------------------------
# Order confirmation (shared by the payment job and admin "Confirm đơn")
# ---------------------------------------------------------------------------

# A user may pay an old QR after switching plan (cancelled) or after it lapsed (expired).
CONFIRMABLE_STATUSES = ("pending", "cancelled", "expired")


async def confirm_order_payment(
    bot,
    order_code: str,
    *,
    transaction_id: str | None = None,
    admin_id: int | None = None,
) -> tuple[Optional[Order], Optional[Subscription], Optional[str], Optional[str]]:
    """
    Activate an order exactly once and create its invite link.
    The row lock serializes the payment job and an admin confirming concurrently:
    whoever comes second sees status 'paid' and gets sub=None.

    Returns (order, sub, invite_link, invite_err). sub is None when the order
    does not exist or is not in a confirmable status.
    """
    async with AsyncSessionLocal() as session:
        order = (await session.execute(
            select(Order).where(Order.order_code == order_code).with_for_update()
        )).scalar_one_or_none()
        if not order or order.status not in CONFIRMABLE_STATUSES:
            return order, None, None, None

        sub = await activate_subscription(order, session)
        if transaction_id:
            order.transaction_id = transaction_id
        invite_link, invite_err = await create_single_use_invite(bot, order.order_code)
        if invite_link:
            order.invite_link = invite_link
        if admin_id:
            session.add(AuditLog(
                admin_id=admin_id,
                action="confirm_order",
                target_user_id=order.user_id,
                detail={"order_code": order_code},
            ))
        await session.commit()
    return order, sub, invite_link, invite_err


# ---------------------------------------------------------------------------
# Periodic payment check — APScheduler job "check_payments" (app/scheduler.py)
# ---------------------------------------------------------------------------

API_ALERT_AFTER = timedelta(minutes=3)
# Orders that lapsed longer ago than this (backlog after downtime/deploy) expire without a DM.
EXPIRY_NOTIFY_WINDOW = timedelta(hours=1)

_api_failing_since: Optional[datetime] = None
_api_alert_sent = False


def match_orders(
    orders: list[Order],
    transactions: list[dict[str, Any]],
    used_ids: set[str],
) -> list[tuple[Order, dict[str, Any]]]:
    """Pair each order with the first unused incoming transaction that pays it."""
    used = set(used_ids)
    matches = []
    for order in orders:
        tx = find_match(transactions, order_code=order.order_code, amount=order.amount, used_ids=used)
        if tx:
            used.add(str(tx.get("transactionID", "")).strip())
            matches.append((order, tx))
    return matches


async def check_payments(bot) -> None:
    """
    Runs every PAYMENT_POLL_INTERVAL_SECONDS. One sieuthicode call covers every
    open order, so payments are caught regardless of QR success, restarts, or
    how late (within ORDER_EXPIRY_HOURS) the user pays.
    """
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        open_orders = list((await session.execute(
            select(Order)
            .where(Order.status.in_(CONFIRMABLE_STATUSES))
            .where(Order.expires_at > now)
        )).scalars().all())

    # shortcut: API health is only probed while orders are open, so a dead cookie surfaces on the next order; add an idle probe if that is too late.
    if open_orders:
        try:
            transactions = await fetch_transactions()
        except Exception as exc:
            await _api_failed(bot, now, exc)
        else:
            await _api_recovered(bot)
            tx_ids = [str(t["transactionID"]).strip() for t in transactions if t.get("transactionID")]
            async with AsyncSessionLocal() as session:
                used = set((await session.execute(
                    select(Order.transaction_id).where(Order.transaction_id.in_(tx_ids))
                )).scalars().all())
            for order, tx in match_orders(open_orders, transactions, used):
                try:
                    await _confirm_and_notify(bot, order.order_code, tx)
                except Exception:
                    logger.exception("auto confirm failed", extra={"order_code": order.order_code})

    await _expire_overdue_orders(bot, now)


async def _confirm_and_notify(bot, order_code: str, tx: dict[str, Any]) -> None:
    tx_id = str(tx.get("transactionID", "")).strip() or None
    order, sub, invite_link, invite_err = await confirm_order_payment(
        bot, order_code, transaction_id=tx_id
    )
    if not sub:
        return  # confirmed by an admin in the meantime

    async with AsyncSessionLocal() as session:
        plan = await get_plan(session, order.plan_code) or {}
    ttl_min = settings.INVITE_LINK_TTL_SECONDS // 60
    text = (
        "✅ <b>Thanh toán thành công! / Payment successful!</b>\n\n"
        f"🔖 Mã đơn / Order: <code>{order.order_code}</code>\n"
        f"{plan.get('emoji', '🎫')} Gói / Plan: <b>{plan.get('name', order.plan_code)}</b>\n"
        f"📅 Hết hạn / Expires: <b>{sub.expires_at.strftime('%d/%m/%Y')}</b>\n\n"
    )
    if invite_link:
        text += (
            f"🔗 <b>Link vào nhóm (1 lần dùng, hết hạn sau {ttl_min} phút):</b>\n"
            f"{invite_link}\n\n"
            f"<i>One-time link, expires in {ttl_min} minutes.</i>"
        )
    else:
        text += (
            f"⚠️ Không tạo được link mời: {safe_html(invite_err)}\n"
            "<i>Could not generate invite link. Contact admin.</i>"
        )
    logger.info(
        "payment confirmed",
        extra={"order_code": order.order_code, "transaction_id": tx_id, "invite_link_ok": invite_link is not None},
    )
    await bot.send_message(order.user_id, text, parse_mode="HTML")


async def _expire_overdue_orders(bot, now: datetime) -> None:
    async with AsyncSessionLocal() as session:
        # Conditional UPDATE so an order an admin confirms concurrently is never flipped back.
        rows = (await session.execute(
            update(Order)
            .where(Order.status == "pending")
            .where(Order.expires_at <= now)
            .values(status="expired")
            .returning(Order.order_code, Order.user_id, Order.expires_at)
        )).all()
        await session.commit()

    for order_code, user_id, expires_at in rows:
        logger.info("order expired", extra={"order_code": order_code, "user_id": user_id})
        if now - expires_at > EXPIRY_NOTIFY_WINDOW:
            continue
        try:
            await bot.send_message(
                user_id,
                (
                    f"⏰ <b>Đơn <code>{order_code}</code> đã hết hạn thanh toán.</b>\n"
                    f"<i>Order <code>{order_code}</code> has expired.</i>\n\n"
                    "Dùng /giahan để tạo đơn hàng mới. Nếu bạn đã chuyển khoản, hãy liên hệ admin.\n"
                    "<i>Use /giahan to create a new order. If you already paid, contact the admin.</i>"
                ),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.warning("expiry notification failed", extra={"user_id": user_id, "error": str(exc)})


async def _api_failed(bot, now: datetime, exc: Exception) -> None:
    global _api_failing_since, _api_alert_sent
    logger.warning("sieuthicode fetch failed", extra={"error": str(exc)})
    if _api_failing_since is None:
        _api_failing_since = now
    if not _api_alert_sent and now - _api_failing_since >= API_ALERT_AFTER:
        _api_alert_sent = True
        local_time = _api_failing_since.astimezone(ZoneInfo(settings.TIMEZONE))
        await _send_to_admins(
            bot,
            "🚨 <b>Bot không kiểm tra được thanh toán!</b>\n\n"
            f"sieuthicode lỗi liên tục từ {local_time.strftime('%H:%M %d/%m')}.\n"
            f"Lỗi: <code>{safe_html(str(exc)[:200])}</code>\n\n"
            "Kiểm tra <code>SIEUTHICODE_COOKIE</code>. Trong lúc này dùng /admin → Confirm đơn.",
        )


async def _api_recovered(bot) -> None:
    global _api_failing_since, _api_alert_sent
    if _api_alert_sent:
        await _send_to_admins(bot, "✅ <b>sieuthicode hoạt động lại</b>, bot tiếp tục tự xác nhận thanh toán.")
    _api_failing_since = None
    _api_alert_sent = False
