import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.messages.templates import Msg
from app.keyboards.menus import main_menu_kb
from app.utils.user import get_or_create_user
from app.utils.order import safe_html

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user, session)

    if user.is_banned:
        await message.answer(Msg.BANNED)
        return

    name = safe_html(message.from_user.first_name)
    await message.answer(
        Msg.WELCOME.format(name=name),
        reply_markup=main_menu_kb(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(Msg.HELP)


@router.callback_query(F.data == "help_cb")
async def cb_help(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(Msg.HELP)
