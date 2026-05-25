import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from aiogram.types import User as TelegramUser

from app.models.user import User

logger = logging.getLogger(__name__)


async def get_or_create_user(tg_user: TelegramUser, session: AsyncSession) -> User:
    """Upsert a Telegram user in the DB and return the ORM object."""
    stmt = (
        insert(User)
        .values(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "username": tg_user.username,
                "first_name": tg_user.first_name,
                "last_name": tg_user.last_name,
            },
        )
    )
    await session.execute(stmt)
    await session.flush()

    result = await session.execute(select(User).where(User.id == tg_user.id))
    user = result.scalar_one()
    logger.info("user upserted", extra={"user_id": tg_user.id, "username": tg_user.username})
    return user
