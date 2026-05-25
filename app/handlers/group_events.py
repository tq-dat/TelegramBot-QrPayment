"""
Group event handlers.
- Welcome new members when they join the VIP group.
"""
import logging

from aiogram import Router
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.types import ChatMemberUpdated

from app.config import settings
from app.messages.templates import Msg
from app.utils.order import safe_html

router = Router()
logger = logging.getLogger(__name__)


@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_user_join(event: ChatMemberUpdated) -> None:
    """Fires when a user joins (or is added to) the group."""
    # Only handle our configured group
    if settings.GROUP_ID and event.chat.id != settings.GROUP_ID:
        return

    user = event.new_chat_member.user
    if user.is_bot:
        return

    name = safe_html(user.first_name)

    # 1. Short post in group (or in RAW topic as default landing)
    try:
        post_kwargs = dict(
            chat_id=event.chat.id,
            text=Msg.GROUP_WELCOME_SHORT.format(name=name),
            parse_mode="HTML",
        )
        if settings.TOPIC_RAW_ID:
            post_kwargs["message_thread_id"] = settings.TOPIC_RAW_ID
        await event.bot.send_message(**post_kwargs)
    except Exception as exc:
        logger.warning("group welcome post failed", extra={"user_id": user.id, "error": str(exc)})

    # 2. DM the user with full orientation
    try:
        await event.bot.send_message(
            chat_id=user.id,
            text=Msg.GROUP_WELCOME_DM,
            parse_mode="HTML",
        )
    except Exception as exc:
        # User may have blocked the bot — not critical
        logger.info("welcome DM skipped", extra={"user_id": user.id, "error": str(exc)})
