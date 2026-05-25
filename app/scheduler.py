"""
APScheduler jobs for:
- D-3 and D-1 expiry reminders (daily)
- Auto-kick expired users (every 30 min)
"""
import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import settings, PLANS
from app.database import AsyncSessionLocal
from app.models.subscription import Subscription
from app.models.user import User
from app.utils.report import generate_report

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reminder jobs
# ---------------------------------------------------------------------------

async def _send_expiry_reminders(bot) -> None:
    """
    Runs once a day. Sends D-3 and D-1 expiry reminders to users
    whose subscription is expiring soon.
    """
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        # D-3: expires between 2d12h and 3d12h from now (24h window centered on 3 days)
        d3_lo = now + timedelta(hours=60)   # 2.5 days
        d3_hi = now + timedelta(hours=84)   # 3.5 days

        result = await session.execute(
            select(Subscription)
            .where(Subscription.is_active.is_(True))
            .where(Subscription.expires_at.between(d3_lo, d3_hi))
            .where(Subscription.d3_reminder_sent.is_(False))
        )
        for sub in result.scalars().all():
            plan = PLANS.get(sub.plan_code, {})
            days_left = max(0, (sub.expires_at - now).days)
            try:
                await bot.send_message(
                    sub.user_id,
                    (
                        "⏰ <b>Gói của bạn sắp hết hạn!</b>\n\n"
                        f"{plan.get('emoji', '🎫')} Gói / Plan: <b>{plan.get('name', sub.plan_code)}</b>\n"
                        f"📅 Hết hạn / Expires: <b>{sub.expires_at.strftime('%d/%m/%Y')}</b>\n"
                        f"⏳ Còn lại / Remaining: <b>{days_left} ngày / days</b>\n\n"
                        "Dùng /giahan để gia hạn ngay!\n"
                        "<i>Use /giahan to renew now!</i>"
                    ),
                    parse_mode="HTML",
                )
                sub.d3_reminder_sent = True
                logger.info("d3 reminder sent", extra={"user_id": sub.user_id, "sub_id": sub.id})
            except Exception as exc:
                logger.warning(
                    "d3 reminder failed", extra={"user_id": sub.user_id, "error": str(exc)}
                )

        # D-1: expires between 12h and 36h from now (24h window centered on 1 day)
        d1_lo = now + timedelta(hours=12)
        d1_hi = now + timedelta(hours=36)

        result = await session.execute(
            select(Subscription)
            .where(Subscription.is_active.is_(True))
            .where(Subscription.expires_at.between(d1_lo, d1_hi))
            .where(Subscription.d1_reminder_sent.is_(False))
        )
        for sub in result.scalars().all():
            plan = PLANS.get(sub.plan_code, {})
            try:
                await bot.send_message(
                    sub.user_id,
                    (
                        "🚨 <b>Gói của bạn hết hạn trong 24 giờ!</b>\n\n"
                        f"{plan.get('emoji', '🎫')} Gói / Plan: <b>{plan.get('name', sub.plan_code)}</b>\n"
                        f"📅 Hết hạn / Expires: <b>{sub.expires_at.strftime('%d/%m/%Y %H:%M')}</b>\n\n"
                        "⚡ Gia hạn ngay để không bị mất quyền truy cập!\n"
                        "<i>Renew now to keep your VIP access!</i>\n\n"
                        "/giahan"
                    ),
                    parse_mode="HTML",
                )
                sub.d1_reminder_sent = True
                logger.info("d1 reminder sent", extra={"user_id": sub.user_id, "sub_id": sub.id})
            except Exception as exc:
                logger.warning(
                    "d1 reminder failed", extra={"user_id": sub.user_id, "error": str(exc)}
                )

        await session.commit()


# ---------------------------------------------------------------------------
# Auto-kick job
# ---------------------------------------------------------------------------

async def _kick_expired_users(bot) -> None:
    """
    Runs every 30 minutes. Finds expired active subscriptions,
    kicks users from the group (ban + immediate unban so they can rejoin later),
    and marks subscriptions as inactive.
    """
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Subscription)
            .where(Subscription.is_active.is_(True))
            .where(Subscription.expires_at <= now)
        )
        expired_subs = result.scalars().all()

        for sub in expired_subs:
            sub.is_active = False
            logger.info("subscription expired", extra={"user_id": sub.user_id, "sub_id": sub.id})

            if settings.GROUP_ID:
                try:
                    # Kick = ban then immediately unban (user can rejoin after buying)
                    await bot.ban_chat_member(
                        chat_id=settings.GROUP_ID,
                        user_id=sub.user_id,
                    )
                    await bot.unban_chat_member(
                        chat_id=settings.GROUP_ID,
                        user_id=sub.user_id,
                        only_if_banned=True,
                    )
                    logger.info(
                        "user kicked (expired)",
                        extra={"user_id": sub.user_id, "group_id": settings.GROUP_ID},
                    )
                except Exception as exc:
                    logger.warning(
                        "kick failed",
                        extra={"user_id": sub.user_id, "error": str(exc)},
                    )

            # Notify the user
            try:
                plan = PLANS.get(sub.plan_code, {})
                await bot.send_message(
                    sub.user_id,
                    (
                        "😔 <b>Gói thành viên của bạn đã hết hạn.</b>\n"
                        "<i>Your membership has expired.</i>\n\n"
                        f"{plan.get('emoji', '🎫')} Gói / Plan: <b>{plan.get('name', sub.plan_code)}</b>\n\n"
                        "Dùng /giahan để mua gói mới và được thêm lại vào nhóm.\n"
                        "<i>Use /giahan to purchase a new plan and rejoin the group.</i>"
                    ),
                    parse_mode="HTML",
                )
            except Exception as exc:
                logger.warning(
                    "expired notification failed",
                    extra={"user_id": sub.user_id, "error": str(exc)},
                )

        await session.commit()


# ---------------------------------------------------------------------------
# Report jobs
# ---------------------------------------------------------------------------

async def _send_report_to_admins(bot, period: str) -> None:
    """Generate a report and push it to all configured admins."""
    async with AsyncSessionLocal() as session:
        text = await generate_report(period, session)

    for admin_id in settings.admin_id_list:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as exc:
            logger.warning(
                "report send failed",
                extra={"admin_id": admin_id, "period": period, "error": str(exc)},
            )


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def create_scheduler(bot) -> AsyncIOScheduler:
    """
    Create and configure the AsyncIOScheduler.
    Call scheduler.start() in main() after the bot is running.
    """
    scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)

    # Expiry reminders — daily at 08:00 local time
    scheduler.add_job(
        _send_expiry_reminders,
        CronTrigger(hour=8, minute=0, timezone=settings.TIMEZONE),
        args=[bot],
        id="expiry_reminders",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Auto-kick expired users — every 30 minutes
    scheduler.add_job(
        _kick_expired_users,
        IntervalTrigger(minutes=30),
        args=[bot],
        id="kick_expired",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Daily revenue report — every day at 08:00 local time
    scheduler.add_job(
        _send_report_to_admins,
        CronTrigger(hour=8, minute=0, timezone=settings.TIMEZONE),
        args=[bot, "daily"],
        id="report_daily",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Weekly revenue report — every Monday at 08:00 local time
    scheduler.add_job(
        _send_report_to_admins,
        CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=settings.TIMEZONE),
        args=[bot, "weekly"],
        id="report_weekly",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    logger.info("scheduler configured")
    return scheduler
