from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.plan_loader import get_visible_plans


# ---------------------------------------------------------------------------
# Callback data factories (type-safe, avoids string parsing)
# ---------------------------------------------------------------------------

class PlanSelectCb(CallbackData, prefix="plan_select"):
    plan_code: str


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Gói của tôi / My Plan", callback_data="my_plan"),
        InlineKeyboardButton(text="🔄 Gia hạn / Renew", callback_data="renew_start"),
    )
    builder.row(
        InlineKeyboardButton(text="❓ Trợ giúp / Help", callback_data="help_cb"),
    )
    return builder.as_markup()


async def plan_selection_kb(session: AsyncSession) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    plans = await get_visible_plans(session)
    for plan in plans:
        price_str = f"{plan['price']:,}".replace(",", ".")
        label = (
            f"{plan['emoji']} {plan['name']} — "
            f"{plan['days']} ngày — {price_str}đ"
        )
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=PlanSelectCb(plan_code=plan["code"]).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(text="❌ Hủy / Cancel", callback_data="cancel")
    )
    return builder.as_markup()


def after_order_kb() -> InlineKeyboardMarkup:
    """Keyboard shown after an order is created (payment instructions screen)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔄 Chọn gói khác / Change Plan", callback_data="renew_start"
        )
    )
    builder.row(
        InlineKeyboardButton(text="📋 Xem gói / My Plan", callback_data="my_plan")
    )
    return builder.as_markup()
