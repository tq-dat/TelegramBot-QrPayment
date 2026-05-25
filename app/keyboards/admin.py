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
        InlineKeyboardButton(text="📊 Báo cáo tháng", callback_data="adm_report_monthly"),
    )
    builder.row(
        InlineKeyboardButton(text="📦 Quản lý gói", callback_data="adm_plans"),
    )
    return builder.as_markup()


def admin_cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Hủy", callback_data="adm_cancel_fsm"),
    )
    return builder.as_markup()


def plans_list_kb(plans: list[dict]) -> InlineKeyboardMarkup:
    """Inline keyboard listing all plans with Edit / Toggle / Delete buttons."""
    builder = InlineKeyboardBuilder()
    for plan in plans:
        visibility = "✅" if plan["is_visible"] else "🔒 Ẩn"
        builder.row(
            InlineKeyboardButton(
                text=f"{plan['emoji']} {plan['name']} ({plan['days']}d — {plan['price']:,}đ) {visibility}",
                callback_data=f"adm_plan_noop",
            )
        )
        builder.row(
            InlineKeyboardButton(text="✏️ Sửa", callback_data=f"adm_plan_edit_{plan['code']}"),
            InlineKeyboardButton(
                text="👁 Ẩn" if plan["is_visible"] else "👁 Hiện",
                callback_data=f"adm_plan_toggle_{plan['code']}",
            ),
            InlineKeyboardButton(text="🗑 Xóa", callback_data=f"adm_plan_del_{plan['code']}"),
        )
    builder.row(
        InlineKeyboardButton(text="➕ Thêm gói mới", callback_data="adm_plan_add"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Về menu", callback_data="adm_back"),
    )
    return builder.as_markup()
