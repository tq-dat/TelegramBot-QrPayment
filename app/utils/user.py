import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from aiogram.types import User as TelegramUser

from app.models.user import User

logger = logging.getLogger(__name__)


async def get_or_create_user(tg_user: TelegramUser, session: AsyncSession) -> User:
    """Upsert a Telegram user in the DB and return the ORM object."""
    result = await session.execute(select(User).where(User.id == tg_user.id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
        session.add(user)
        await session.flush()
        logger.info("new_user registered", extra={"user_id": tg_user.id, "username": tg_user.username})
    else:
        user.username = tg_user.username
        user.first_name = tg_user.first_name
        user.last_name = tg_user.last_name

    return user
