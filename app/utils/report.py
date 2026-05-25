"""
Report generation utilities.

generate_report(period, session) → HTML string
  period: 'daily' | 'weekly'
"""
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import PLANS
from app.models.order import Order
from app.models.subscription import Subscription


def _day_start(now: datetime) -> datetime:
    """Today 00:00:00 UTC."""
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _week_start(now: datetime) -> datetime:
    """Most recent Monday 00:00:00 UTC."""
    return (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


async def generate_report(period: str, session: AsyncSession) -> str:
    """
    Build an HTML-formatted revenue report.

    Args:
        period: 'daily' for today, 'weekly' for Mon–now.
        session: active AsyncSession.

    Returns:
        HTML string ready to send via Telegram (parse_mode=HTML).
    """
    now = datetime.now(timezone.utc)

    if period == "weekly":
        since = _week_start(now)
        label = f"Tuần này ({since.strftime('%d/%m')} — {now.strftime('%d/%m/%Y')})"
    else:  # daily
        since = _day_start(now)
        label = f"Hôm nay ({now.strftime('%d/%m/%Y')})"

    # --- Paid orders breakdown by plan ---
    paid_result = await session.execute(
        select(Order.plan_code, func.count(Order.id), func.sum(Order.amount))
        .where(Order.status == "paid")
        .where(Order.paid_at >= since)
        .group_by(Order.plan_code)
        .order_by(func.sum(Order.amount).desc())
    )
    paid_rows = paid_result.all()

    total_orders = sum(r[1] for r in paid_rows)
    total_revenue = sum(r[2] or 0 for r in paid_rows)

    # --- Expired orders in period (by created_at) ---
    expired_count = (await session.execute(
        select(func.count(Order.id))
        .where(Order.status == "expired")
        .where(Order.created_at >= since)
    )).scalar() or 0

    # --- Refunded orders in period ---
    refunded_count = (await session.execute(
        select(func.count(Order.id))
        .where(Order.status == "refunded")
        .where(Order.created_at >= since)
    )).scalar() or 0

    # --- Active members right now ---
    active_count = (await session.execute(
        select(func.count(Subscription.id))
        .where(Subscription.is_active.is_(True))
        .where(Subscription.expires_at > now)
    )).scalar() or 0

    # --- Build message ---
    lines = [
        f"📊 <b>Báo cáo doanh thu</b> — {label}\n",
        f"💰 <b>Tổng doanh thu:</b> <b>{total_revenue:,}đ</b>",
        f"✅ <b>Đơn thành công:</b> {total_orders}",
        f"↩️ <b>Đơn refund:</b> {refunded_count}",
        f"⌛ <b>Đơn hết hạn (không trả tiền):</b> {expired_count}",
        f"👥 <b>Member VIP hiện tại:</b> {active_count}",
    ]

    if paid_rows:
        lines.append("\n<b>Chi tiết theo gói:</b>")
        for plan_code, count, revenue in paid_rows:
            plan = PLANS.get(plan_code, {})
            emoji = plan.get("emoji", "🎫")
            name = plan.get("name", plan_code)
            lines.append(
                f"  {emoji} <b>{name}</b>: {count} đơn — {(revenue or 0):,}đ"
            )

    return "\n".join(lines)
