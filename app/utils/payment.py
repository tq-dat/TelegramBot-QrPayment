"""
Payment utilities:
- VietQR image generation via vietqr.io
- Transaction matching (ported from qr_example.py)
- Async background payment monitor
"""
import asyncio
import logging
import unicodedata
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from urllib.parse import quote_plus

import httpx
from sqlalchemy import select

from app.config import settings, PLANS
from app.database import AsyncSessionLocal
from app.models.order import Order
from app.models.subscription import Subscription
from app.utils.invite import create_single_use_invite

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
    return resp.json().get("transactions", [])


def snapshot_ids(transactions: list[dict[str, Any]]) -> set[str]:
    """Return the set of transactionID strings present in a transaction list."""
    return {
        str(tx.get("transactionID", "")).strip()
        for tx in transactions
        if tx.get("transactionID")
    }


def find_match(
    transactions: list[dict[str, Any]],
    *,
    memo: str,
    amount: int,
    baseline_ids: set[str],
) -> Optional[dict[str, Any]]:
    """
    Find the first transaction that:
    - is NOT in baseline (i.e. new since we started watching)
    - has type == "IN"
    - has amount matching the order amount
    - has description containing at least one memo candidate
    """
    candidates = _memo_candidates(memo)
    for tx in transactions:
        tx_id = str(tx.get("transactionID", "")).strip()
        if tx_id and tx_id in baseline_ids:
            continue
        if _to_int(tx.get("amount")) != amount:
            continue
        tx_type = _normalize_text(tx.get("type", ""))
        if tx_type and tx_type != "in":
            continue
        desc_raw = str(tx.get("description", "") or "")
        desc_strict = _collapse(_normalize_text(desc_raw))
        desc_loose = _to_loose(desc_raw)
        if any(c in desc_strict or c in desc_loose for c in candidates):
            return tx
    return None


# ---------------------------------------------------------------------------
# VietQR image
# ---------------------------------------------------------------------------

async def generate_vietqr_image(amount: int, memo: str) -> bytes:
    """
    Download a VietQR payment QR image from vietqr.io.
    Returns raw image bytes (JPEG).
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
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{url}?{query}")
        resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------------------
# Subscription activation (with stacking)
# ---------------------------------------------------------------------------

async def activate_subscription(order: Order, session) -> Subscription:
    """
    Mark the order as paid and create a Subscription.
    If the user already has an active subscription, the new one is stacked
    on top (starts when the current one expires).
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

    plan = PLANS[order.plan_code]
    started_at = current_sub.expires_at if current_sub else now
    expires_at = started_at + timedelta(days=plan["days"])

    sub = Subscription(
        user_id=order.user_id,
        plan_code=order.plan_code,
        started_at=started_at,
        expires_at=expires_at,
        is_active=True,
        order_id=order.id,
    )
    session.add(sub)
    order.status = "paid"
    order.paid_at = now

    logger.info(
        "subscription activated",
        extra={
            "user_id": order.user_id,
            "order_code": order.order_code,
            "plan": order.plan_code,
            "expires_at": expires_at.isoformat(),
            "stacked_on": current_sub.expires_at.isoformat() if current_sub else None,
        },
    )
    return sub


# ---------------------------------------------------------------------------
# Async background payment monitor
# ---------------------------------------------------------------------------

async def monitor_payment(
    *,
    order_id: int,
    user_id: int,
    memo: str,
    amount: int,
    bot,
    watch_seconds: int,
    poll_interval: int,
) -> None:
    """
    Runs as an asyncio Task. Polls sieuthicode every poll_interval seconds
    until a matching transaction is found or watch_seconds elapses.

    memo and amount are passed directly to avoid reading DB before
    the creating session is committed.
    """
    deadline = datetime.now(timezone.utc) + timedelta(seconds=watch_seconds)

    # Snapshot current transactions so we only look at NEW ones
    baseline_ids: set[str] = set()
    try:
        baseline_ids = snapshot_ids(await fetch_transactions())
        logger.info(
            "payment monitor started",
            extra={"order_id": order_id, "baseline_count": len(baseline_ids)},
        )
    except Exception as exc:
        logger.warning("baseline snapshot failed", extra={"error": str(exc)})

    while datetime.now(timezone.utc) < deadline:
        await asyncio.sleep(poll_interval)

        # Stop if the order has been cancelled or already paid externally
        async with AsyncSessionLocal() as session:
            order = await session.get(Order, order_id)
            if not order or order.status != "pending":
                logger.info(
                    "monitor stopping: status changed",
                    extra={"order_id": order_id, "status": getattr(order, "status", None)},
                )
                return

        try:
            transactions = await fetch_transactions()
        except Exception as exc:
            logger.warning("poll error", extra={"order_id": order_id, "error": str(exc)})
            continue

        matched = find_match(
            transactions,
            memo=memo,
            amount=amount,
            baseline_ids=baseline_ids,
        )

        if matched:
            async with AsyncSessionLocal() as session:
                order = await session.get(Order, order_id)
                if order and order.status == "pending":
                    sub = await activate_subscription(order, session)

                    # Generate single-use group invite link (1 use, 5 min TTL)
                    invite_link, invite_err = await create_single_use_invite(
                        bot, order.order_code
                    )
                    if invite_link:
                        order.invite_link = invite_link

                    await session.commit()

                    plan = PLANS.get(order.plan_code, {})
                    success_text = (
                        "✅ <b>Thanh toán thành công! / Payment successful!</b>\n\n"
                        f"{plan.get('emoji', '🎫')} Gói / Plan: <b>{plan.get('name', order.plan_code)}</b>\n"
                        f"📅 Hết hạn / Expires: <b>{sub.expires_at.strftime('%d/%m/%Y')}</b>\n\n"
                    )
                    if invite_link:
                        success_text += (
                            "🔗 <b>Link vào nhóm (1 lần dùng, hết hạn sau 5 phút):</b>\n"
                            f"{invite_link}\n\n"
                            "<i>⚠️ Link chỉ dùng được 1 lần và hết hạn sau 5 phút.</i>\n"
                            "<i>One-time link, expires in 5 minutes.</i>"
                        )
                    else:
                        success_text += (
                            f"⚠️ Không tạo được link mời: {invite_err}\n"
                            "<i>Could not generate invite link. Contact admin.</i>"
                        )

                    await bot.send_message(user_id, success_text, parse_mode="HTML")
                    logger.info(
                        "payment confirmed",
                        extra={
                            "order_id": order_id,
                            "transaction_id": matched.get("transactionID"),
                            "invite_link_ok": invite_link is not None,
                        },
                    )
            return

    # Deadline reached — mark order as expired
    async with AsyncSessionLocal() as session:
        order = await session.get(Order, order_id)
        if order and order.status == "pending":
            order.status = "expired"
            await session.commit()
            logger.info("order expired by monitor", extra={"order_id": order_id})

    minutes = watch_seconds // 60
    await bot.send_message(
        user_id,
        (
            f"⏰ <b>Đã hết {minutes} phút chờ thanh toán.</b>\n"
            "<i>Payment window expired.</i>\n\n"
            "Dùng /giahan để tạo đơn hàng mới.\n"
            "<i>Use /giahan to create a new order.</i>"
        ),
        parse_mode="HTML",
    )
