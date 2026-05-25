"""
Telegram group invite link helpers.
Creates single-use, time-limited invite links for the VIP group.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


async def create_single_use_invite(
    bot,
    label: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Create a single-use invite link for GROUP_ID.
    - member_limit = 1  (auto-revoked after 1 use)
    - expire_date  = now + INVITE_LINK_TTL_SECONDS  (auto-revoked after TTL)

    Returns (invite_link_url, error_message).
    On success: (url, None). On failure: (None, error_str).
    """
    if not settings.GROUP_ID:
        return None, "GROUP_ID chưa cấu hình trong .env"

    expire_at = datetime.now() + timedelta(seconds=settings.INVITE_LINK_TTL_SECONDS)
    try:
        invite = await bot.create_chat_invite_link(
            chat_id=settings.GROUP_ID,
            expire_date=int(expire_at.timestamp()),
            member_limit=1,
            name=f"pay-{label}",
        )
        link = getattr(invite, "invite_link", None)
        if not link:
            return None, "Telegram không trả về invite_link"
        logger.info("invite link created", extra={"label": label, "expire_at": expire_at.isoformat()})
        return str(link), None
    except Exception as exc:
        logger.error("invite link creation failed", extra={"label": label, "error": str(exc)})
        return None, str(exc)
