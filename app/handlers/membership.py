import logging
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.messages.templates import Msg
from app.keyboards.menus import main_menu_kb
from app.models.subscription import Subscription
from app.utils.plan_loader import get_plan

router = Router()
logger = logging.getLogger(__name__)


async def _get_active_subscription(user_id: int, session: AsyncSession) -> Subscription | None:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .where(Subscription.is_active.is_(True))
        .where(Subscription.expires_at > now)
        .order_by(Subscription.expires_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _render_plan_status(user_id: int, session: AsyncSession) -> str:
    sub = await _get_active_subscription(user_id, session)
    if sub is None:
        return Msg.NO_PLAN

    plan = await get_plan(session, sub.plan_code) or {}
    now = datetime.now(timezone.utc)
    days_left = max(0, (sub.expires_at - now).days)
    return Msg.PLAN_STATUS.format(
        emoji=plan.get("emoji", "🎫"),
        plan_name=plan.get("name", sub.plan_code),
        expires_at=sub.expires_at.strftime("%d/%m/%Y %H:%M"),
        days_left=days_left,
    )


@router.message(Command("mygoi"), StateFilter("*"))
async def cmd_mygoi(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    text = await _render_plan_status(message.from_user.id, session)
    await message.answer(text, reply_markup=main_menu_kb())


@router.callback_query(F.data == "my_plan")
async def cb_my_plan(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    text = await _render_plan_status(callback.from_user.id, session)
    try:
        await callback.message.edit_text(text, reply_markup=main_menu_kb())
    except TelegramBadRequest:
        pass  # content unchanged, nothing to update
