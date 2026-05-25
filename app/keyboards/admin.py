from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_panel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👥 Xem members", callback_data="adm_members"),
        InlineKeyboardButton(text="📋 Đơn pending", callback_data="adm_pending"),
    )
    builder.row(
        InlineKeyboardButton(text="✅ Confirm đơn", callback_data="adm_confirm_start"),
        InlineKeyboardButton(text="🎁 Tặng ngày", callback_data="adm_givedays_start"),
    )
    builder.row(
        InlineKeyboardButton(text="🚫 Ban user", callback_data="adm_ban_start"),
        InlineKeyboardButton(text="📝 Refund note", callback_data="adm_refund_start"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Báo cáo hôm nay", callback_data="adm_report_daily"),
        InlineKeyboardButton(text="📊 Báo cáo tuần", callback_data="adm_report_weekly"),
    )
    return builder.as_markup()


def admin_cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Hủy", callback_data="adm_cancel_fsm"),
    )
    return builder.as_markup()
