import asyncio
import logging
import sys

from pythonjsonlogger import jsonlogger
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from app.config import settings
from app.middleware import DbSessionMiddleware
from app.handlers import start, membership, renewal
from app.handlers import admin as admin_handler
from app.scheduler import create_scheduler


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    root.addHandler(handler)


async def set_bot_commands(bot: Bot) -> None:
    """Register bot commands for menu suggestions."""
    user_commands = [
        BotCommand(command="start", description="Khởi động bot / Trang chủ"),
        BotCommand(command="help", description="Hướng dẫn sử dụng"),
        BotCommand(command="mygoi", description="Xem gói dịch vụ của tôi"),
        BotCommand(command="giahan", description="Gia hạn gói dịch vụ"),
    ]
    admin_commands = user_commands + [
        BotCommand(command="admin", description="Bảng quản trị admin"),
        BotCommand(command="baocao", description="Xem báo cáo doanh thu"),
    ]

    # Set default commands for all users
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

    # Set extended commands for each admin
    for admin_id in settings.admin_id_list:
        try:
            await bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            pass  # admin may not have started the bot yet


async def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("bot starting", extra={"debug": settings.DEBUG})

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Middleware — inject DB session into every handler
    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())

    # Routers
    dp.include_router(start.router)
    dp.include_router(membership.router)
    dp.include_router(renewal.router)
    dp.include_router(admin_handler.router)

    # Scheduler (D-3/D-1 reminders + auto-kick)
    scheduler = create_scheduler(bot)
    scheduler.start()
    logger.info("scheduler started")

    logger.info("bot started (long polling)")
    try:
        await set_bot_commands(bot)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        logger.info("bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
