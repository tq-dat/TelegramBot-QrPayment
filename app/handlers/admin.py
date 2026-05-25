"""
Admin panel handlers.

/admin          → show admin panel (inline buttons)
FSM flows via inline buttons:
  - Confirm order  : ask for "order_code transaction_id"
  - Give days      : ask for "user_id days"
  - Ban user       : ask for "user_id [reason]"
  - Refund note    : ask for "order_code note"

List views (callbacks):
  - adm_members   : active subscriptions
  - adm_pending   : pending orders
"""
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.keyboards.admin import admin_panel_kb, admin_cancel_kb, plans_list_kb
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.utils.invite import create_single_use_invite
from app.utils.payment import activate_subscription
from app.utils.plan_loader import get_plan, get_all_plans, slugify
from app.utils.report import generate_report
from app.scheduler import _kick_expired_users

router = Router()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FSM states
# ---------------------------------------------------------------------------

class AdminFSM(StatesGroup):
    confirm_order = State()   # waiting for "order_code"
    give_days = State()       # waiting for "user_id days"
    ban_user = State()        # waiting for "user_id [reason]"
    refund_note = State()     # waiting for "order_code note..."
    add_plan = State()        # waiting for "name|days|price|emoji"
    edit_plan = State()       # waiting for "name|days|price|emoji" (plan code stored in FSM data)


# ---------------------------------------------------------------------------
# Guard helper
# ---------------------------------------------------------------------------

def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_id_list


def _not_command(message: Message) -> bool:
    """Filter: True when the message is NOT a bot command (does not start with /)."""
    return not (message.text and message.text.startswith("/"))


async def _guard(message_or_cb) -> bool:
    """Return True if the sender is an admin, reply with error otherwise."""
    uid = (
        message_or_cb.from_user.id
        if hasattr(message_or_cb, "from_user")
        else message_or_cb.from_user.id
    )
    if _is_admin(uid):
        return True
    if hasattr(message_or_cb, "answer"):
        await message_or_cb.answer("🚫 Bạn không có quyền admin.")
    return False


# ---------------------------------------------------------------------------
# /admin entry point
# ---------------------------------------------------------------------------

@router.message(Command("admin"), StateFilter("*"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not await _guard(message):
        return
    await message.answer(
        "🛠 <b>Admin Panel</b>\n\nChọn thao tác:",
        reply_markup=admin_panel_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# List views
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "adm_members")
async def cb_adm_members(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    await callback.answer()

    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Subscription, User)
        .join(User, User.id == Subscription.user_id)
        .where(Subscription.is_active.is_(True))
        .where(Subscription.expires_at > now)
        .order_by(Subscription.expires_at.asc())
    )
    rows = result.all()

    if not rows:
        await callback.message.answer(
            "📭 Không có thành viên VIP nào đang hoạt động.",
            reply_markup=admin_panel_kb(),
        )
        return

    # Deduplicate: keep only the latest-expiring subscription per user
    latest: dict[int, tuple] = {}
    for sub, user in rows:
        existing = latest.get(user.id)
        if existing is None or sub.expires_at > existing[0].expires_at:
            latest[user.id] = (sub, user)

    # Sort by expires_at asc, cap at 30
    unique_rows = sorted(latest.values(), key=lambda t: t[0].expires_at)

    lines = ["👥 <b>Active members:</b>\n"]
    for sub, user in unique_rows:
        days_left = max(0, (sub.expires_at - now).days)
        name = f"@{user.username}" if user.username else user.first_name
        plan = await get_plan(session, sub.plan_code) or {}
        lines.append(
            f"• {name} (<code>{user.id}</code>) — "
            f"{plan.get('emoji','')}{plan.get('name', sub.plan_code)} "
            f"— hết hạn {sub.expires_at.strftime('%d/%m/%Y')} ({days_left}d)"
        )

    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.message.answer("🛠 <b>Admin Panel</b>", reply_markup=admin_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "adm_pending")
async def cb_adm_pending(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    await callback.answer()

    result = await session.execute(
        select(Order, User)
        .join(User, User.id == Order.user_id)
        .where(Order.status == "pending")
        .order_by(Order.created_at.desc())
        .limit(20)
    )
    rows = result.all()

    if not rows:
        await callback.message.answer(
            "✅ Không có đơn pending nào.",
            reply_markup=admin_panel_kb(),
        )
        return

    all_plans = await get_all_plans(session)
    plans_map = {p["code"]: p for p in all_plans}

    lines = ["📋 <b>Đơn pending (max 20):</b>\n"]
    for order, user in rows:
        name = f"@{user.username}" if user.username else user.first_name
        plan = plans_map.get(order.plan_code, {})
        age_min = int((datetime.now(timezone.utc) - order.created_at).total_seconds() / 60)
        lines.append(
            f"• <code>{order.order_code}</code> — {name} — "
            f"{plan.get('name', order.plan_code)} — "
            f"{order.amount:,}đ — {age_min}ph trước"
        )

    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.message.answer("🛠 <b>Admin Panel</b>", reply_markup=admin_panel_kb(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# FSM: Confirm order
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "adm_confirm_start")
async def cb_adm_confirm_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminFSM.confirm_order)
    await callback.message.answer(
        "✅ <b>Confirm đơn thủ công</b>\n\n"
        "Nhập: <code>order_code</code>\n"
        "Ví dụ: <code>VIPA1B2C3D4</code>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminFSM.confirm_order, _not_command)
async def fsm_confirm_order(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return

    order_code = message.text.strip().upper()
    if not order_code:
        await message.answer(
            "⚠️ Nhập mã đơn. Ví dụ: <code>VIPA1B2C3D4</code>",
            parse_mode="HTML",
            reply_markup=admin_cancel_kb(),
        )
        return

    await state.clear()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order).where(Order.order_code == order_code)
        )
        order = result.scalar_one_or_none()

        if not order:
            await message.answer(f"❌ Không tìm thấy đơn <code>{order_code}</code>.", parse_mode="HTML")
            return
        if order.status != "pending":
            await message.answer(
                f"⚠️ Đơn <code>{order_code}</code> có trạng thái <b>{order.status}</b>, không thể confirm.",
                parse_mode="HTML",
            )
            return

        sub = await activate_subscription(order, session)

        # Generate invite link
        invite_link, invite_err = await create_single_use_invite(message.bot, order_code)
        if invite_link:
            order.invite_link = invite_link

        # Audit log
        session.add(AuditLog(
            admin_id=message.from_user.id,
            action="confirm_order",
            target_user_id=order.user_id,
            detail={"order_code": order_code},
        ))
        await session.commit()

    # Notify user
    async with AsyncSessionLocal() as _s:
        plan = await get_plan(_s, order.plan_code) or {}
    user_text = (
        "✅ <b>Thanh toán đã được xác nhận bởi admin!</b>\n\n"
        f"{plan.get('emoji','🎫')} Gói: <b>{plan.get('name', order.plan_code)}</b>\n"
        f"📅 Hết hạn: <b>{sub.expires_at.strftime('%d/%m/%Y')}</b>\n\n"
    )
    if invite_link:
        user_text += (
            "🔗 <b>Link vào nhóm (1 lần, 5 phút):</b>\n"
            f"{invite_link}"
        )
    else:
        user_text += f"⚠️ Không tạo được link: {invite_err}"

    try:
        await message.bot.send_message(order.user_id, user_text, parse_mode="HTML")
    except Exception as exc:
        logger.warning("could not notify user", extra={"user_id": order.user_id, "error": str(exc)})

    await message.answer(
        f"✅ Đã confirm đơn <code>{order_code}</code> cho user <code>{order.user_id}</code>.",
        parse_mode="HTML",
    )
    logger.info("admin confirmed order", extra={"order_code": order_code, "admin": message.from_user.id})


# ---------------------------------------------------------------------------
# FSM: Give days
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "adm_givedays_start")
async def cb_adm_givedays_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminFSM.give_days)
    await callback.message.answer(
        "🎁 <b>Tặng ngày cho user</b>\n\n"
        "Nhập: <code>user_id số_ngày</code>\n"
        "Ví dụ: <code>6560945590 30</code>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminFSM.give_days, _not_command)
async def fsm_give_days(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer(
            "⚠️ Nhập: <code>user_id số_ngày</code>",
            parse_mode="HTML",
            reply_markup=admin_cancel_kb(),
        )
        return

    target_uid, days = int(parts[0]), int(parts[1])
    await state.clear()

    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)

        # Check if user exists
        user = await session.get(User, target_uid)
        if not user:
            await message.answer(f"❌ Không tìm thấy user <code>{target_uid}</code>.", parse_mode="HTML")
            return

        # Extend existing active sub or create new one
        result = await session.execute(
            select(Subscription)
            .where(Subscription.user_id == target_uid)
            .where(Subscription.is_active.is_(True))
            .where(Subscription.expires_at > now)
            .order_by(Subscription.expires_at.desc())
            .limit(1)
        )
        current_sub = result.scalar_one_or_none()

        if current_sub:
            current_sub.expires_at = current_sub.expires_at + timedelta(days=days)
            new_expires = current_sub.expires_at
        else:
            new_sub = Subscription(
                user_id=target_uid,
                plan_code="gift",
                started_at=now,
                expires_at=now + timedelta(days=days),
                is_active=True,
            )
            session.add(new_sub)
            new_expires = new_sub.expires_at

        session.add(AuditLog(
            admin_id=message.from_user.id,
            action="give_days",
            target_user_id=target_uid,
            detail={"days": days},
        ))
        await session.commit()

    try:
        await message.bot.send_message(
            target_uid,
            (
                f"🎁 <b>Admin đã tặng bạn {days} ngày!</b>\n\n"
                f"📅 Hết hạn mới: <b>{new_expires.strftime('%d/%m/%Y')}</b>"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await message.answer(
        f"✅ Đã tặng <b>{days} ngày</b> cho user <code>{target_uid}</code>.\n"
        f"📅 Hết hạn: <b>{new_expires.strftime('%d/%m/%Y')}</b>",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# FSM: Ban user
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "adm_ban_start")
async def cb_adm_ban_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminFSM.ban_user)
    await callback.message.answer(
        "🚫 <b>Ban user</b>\n\n"
        "Nhập: <code>user_id [lý do]</code>\n"
        "Ví dụ: <code>6560945590 spam</code>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminFSM.ban_user, _not_command)
async def fsm_ban_user(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.strip().split(maxsplit=1)
    if not parts[0].isdigit():
        await message.answer(
            "⚠️ Nhập: <code>user_id [lý do]</code>",
            parse_mode="HTML",
            reply_markup=admin_cancel_kb(),
        )
        return

    target_uid = int(parts[0])
    reason = parts[1] if len(parts) > 1 else "Admin ban"
    await state.clear()

    async with AsyncSessionLocal() as session:
        user = await session.get(User, target_uid)
        if not user:
            await message.answer(f"❌ Không tìm thấy user <code>{target_uid}</code>.", parse_mode="HTML")
            return

        user.is_banned = True
        user.banned_at = datetime.now(timezone.utc)
        user.banned_reason = reason

        session.add(AuditLog(
            admin_id=message.from_user.id,
            action="ban_user",
            target_user_id=target_uid,
            detail={"reason": reason},
        ))
        await session.commit()

    # Also kick from group if configured
    if settings.GROUP_ID:
        try:
            await message.bot.ban_chat_member(chat_id=settings.GROUP_ID, user_id=target_uid)
        except Exception as exc:
            logger.warning("group ban failed", extra={"user_id": target_uid, "error": str(exc)})

    await message.answer(
        f"✅ Đã ban user <code>{target_uid}</code>.\nLý do: {reason}",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# FSM: Refund note
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "adm_refund_start")
async def cb_adm_refund_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminFSM.refund_note)
    await callback.message.answer(
        "📝 <b>Refund note</b>\n\n"
        "Nhập: <code>order_code ghi chú</code>\n"
        "Ví dụ: <code>VIPA1B2C3D4 hoàn tiền theo yêu cầu</code>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminFSM.refund_note, _not_command)
async def fsm_refund_note(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "⚠️ Nhập: <code>order_code ghi chú</code>",
            parse_mode="HTML",
            reply_markup=admin_cancel_kb(),
        )
        return

    order_code, note = parts[0].upper(), parts[1]
    await state.clear()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order).where(Order.order_code == order_code)
        )
        order = result.scalar_one_or_none()
        if not order:
            await message.answer(f"❌ Không tìm thấy đơn <code>{order_code}</code>.", parse_mode="HTML")
            return

        order.status = "refunded"
        order.note = note

        session.add(AuditLog(
            admin_id=message.from_user.id,
            action="refund_order",
            target_user_id=order.user_id,
            detail={"order_code": order_code, "note": note},
        ))
        await session.commit()

    await message.answer(
        f"✅ Đơn <code>{order_code}</code> đã được đánh dấu <b>refunded</b>.\nGhi chú: {note}",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Report callbacks + /baocao command
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "adm_report_daily")
async def cb_adm_report_daily(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    await callback.answer()
    text = await generate_report("daily", session)
    await callback.message.answer(text, parse_mode="HTML")
    await callback.message.answer("🛠 <b>Admin Panel</b>", reply_markup=admin_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "adm_report_weekly")
async def cb_adm_report_weekly(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    await callback.answer()
    text = await generate_report("weekly", session)
    await callback.message.answer(text, parse_mode="HTML")
    await callback.message.answer("🛠 <b>Admin Panel</b>", reply_markup=admin_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "adm_report_monthly")
async def cb_adm_report_monthly(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    await callback.answer()
    text = await generate_report("monthly", session)
    await callback.message.answer(text, parse_mode="HTML")
    await callback.message.answer("🛠 <b>Admin Panel</b>", reply_markup=admin_panel_kb(), parse_mode="HTML")


@router.message(Command("baocao"), StateFilter("*"))
async def cmd_baocao(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    if not await _guard(message):
        return
    arg = (message.text or "").strip().split()[-1].lower() if len((message.text or "").split()) > 1 else "daily"
    if arg == "weekly":
        period = "weekly"
    elif arg in ("monthly", "thang", "tháng"):
        period = "monthly"
    else:
        period = "daily"
    text = await generate_report(period, session)
    await message.answer(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# FSM cancel
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "adm_cancel_fsm")
async def cb_adm_cancel_fsm(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("❌ Đã hủy thao tác.", reply_markup=None)
    await callback.message.answer(
        "🛠 <b>Admin Panel</b>\n\nChọn thao tác:",
        reply_markup=admin_panel_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "adm_back")
async def cb_adm_back(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "🛠 <b>Admin Panel</b>\n\nChọn thao tác:",
        reply_markup=admin_panel_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Test: manually trigger auto-kick (admin only)
# ---------------------------------------------------------------------------

# @router.message(Command("testkick"), StateFilter("*"))
# async def cmd_testkick(message: Message, state: FSMContext) -> None:
#     await state.clear()
#     if not await _guard(message):
#         return
#     await message.answer("⏳ Đang chạy auto-kick thủ công...")
#     await _kick_expired_users(message.bot)
#     await message.answer("✅ Hoàn tất. Kiểm tra log để xem kết quả.")


# ---------------------------------------------------------------------------
# Plan management
# ---------------------------------------------------------------------------

async def _show_plans_list(target, session: AsyncSession) -> None:
    """Send/edit the plans list with CRUD keyboard. target = Message or CallbackQuery."""
    plans = await get_all_plans(session)
    text = "📦 <b>Quản lý gói</b>\n\nDanh sách gói hiện tại:"
    kb = plans_list_kb(plans)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm_plans")
async def cb_adm_plans(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    await callback.answer()
    await _show_plans_list(callback, session)


@router.callback_query(F.data == "adm_plan_noop")
async def cb_adm_plan_noop(callback: CallbackQuery) -> None:
    await callback.answer()


# --- Add plan ---

@router.callback_query(F.data == "adm_plan_add")
async def cb_adm_plan_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminFSM.add_plan)
    await callback.message.answer(
        "➕ <b>Thêm gói mới</b>\n\n"
        "Nhập theo định dạng:\n"
        "<code>Tên gói|số ngày|giá VND|emoji|thứ tự</code>\n\n"
        "Ví dụ: <code>VIP 7 ngày|7|150000|🌟|5</code>\n"
        "<i>(thứ tự hiển thị là tùy chọn, mặc định = 0)</i>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminFSM.add_plan, _not_command)
async def fsm_add_plan(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return

    parts = [p.strip() for p in message.text.strip().split("|")]
    if len(parts) < 3:
        await message.answer(
            "⚠️ Sai định dạng. Nhập: <code>Tên|ngày|giá|emoji|thứ tự</code>",
            parse_mode="HTML",
            reply_markup=admin_cancel_kb(),
        )
        return

    name = parts[0]
    try:
        days = int(parts[1])
        price = int(parts[2])
    except ValueError:
        await message.answer(
            "⚠️ Số ngày và giá phải là số nguyên.",
            reply_markup=admin_cancel_kb(),
        )
        return

    emoji = parts[3] if len(parts) > 3 else "🎫"
    sort_order = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
    code = slugify(name)

    # Ensure code is unique
    existing = await session.execute(select(Plan).where(Plan.code == code))
    if existing.scalar_one_or_none():
        code = f"{code}_{days}"

    plan = Plan(
        code=code,
        name=name,
        days=days,
        price=price,
        emoji=emoji,
        sort_order=sort_order,
        is_visible=True,
    )
    session.add(plan)
    session.add(AuditLog(
        admin_id=message.from_user.id,
        action="add_plan",
        target_user_id=None,
        detail={"code": code, "name": name, "days": days, "price": price},
    ))
    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ Đã thêm gói <b>{emoji} {name}</b> (<code>{code}</code>) — "
        f"{days} ngày — {price:,}đ\n\nHiện trong danh sách gói.",
        parse_mode="HTML",
    )
    await _show_plans_list(message, session)
    logger.info("plan added", extra={"code": code, "admin": message.from_user.id})


# --- Edit plan ---

@router.callback_query(F.data.startswith("adm_plan_edit_"))
async def cb_adm_plan_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    code = callback.data.removeprefix("adm_plan_edit_")
    await callback.answer()
    await state.set_state(AdminFSM.edit_plan)
    await state.update_data(edit_plan_code=code)
    await callback.message.answer(
        f"✏️ <b>Sửa gói</b> <code>{code}</code>\n\n"
        "Nhập giá trị mới:\n"
        "<code>Tên gói|số ngày|giá VND|emoji|thứ tự</code>\n\n"
        "Ví dụ: <code>Basic Plus|30|550000|⭐|1</code>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminFSM.edit_plan, _not_command)
async def fsm_edit_plan(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return

    data = await state.get_data()
    code = data.get("edit_plan_code")
    await state.clear()

    parts = [p.strip() for p in message.text.strip().split("|")]
    if len(parts) < 3:
        await message.answer(
            "⚠️ Sai định dạng. Nhập: <code>Tên|ngày|giá|emoji|thứ tự</code>",
            parse_mode="HTML",
        )
        return

    result = await session.execute(select(Plan).where(Plan.code == code))
    plan = result.scalar_one_or_none()
    if not plan:
        await message.answer(f"❌ Không tìm thấy gói <code>{code}</code>.", parse_mode="HTML")
        return

    try:
        plan.name = parts[0]
        plan.days = int(parts[1])
        plan.price = int(parts[2])
        if len(parts) > 3:
            plan.emoji = parts[3]
        if len(parts) > 4 and parts[4].isdigit():
            plan.sort_order = int(parts[4])
    except ValueError:
        await message.answer("⚠️ Số ngày và giá phải là số nguyên.")
        return

    session.add(AuditLog(
        admin_id=message.from_user.id,
        action="edit_plan",
        target_user_id=None,
        detail={"code": code, "name": plan.name, "days": plan.days, "price": plan.price},
    ))
    await session.commit()
    await message.answer(
        f"✅ Đã cập nhật gói <b>{plan.emoji} {plan.name}</b> (<code>{code}</code>).",
        parse_mode="HTML",
    )
    await _show_plans_list(message, session)
    logger.info("plan edited", extra={"code": code, "admin": message.from_user.id})


# --- Toggle visibility ---

@router.callback_query(F.data.startswith("adm_plan_toggle_"))
async def cb_adm_plan_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    code = callback.data.removeprefix("adm_plan_toggle_")
    await callback.answer()

    result = await session.execute(select(Plan).where(Plan.code == code))
    plan = result.scalar_one_or_none()
    if not plan:
        await callback.message.answer(f"❌ Không tìm thấy gói <code>{code}</code>.", parse_mode="HTML")
        return

    plan.is_visible = not plan.is_visible
    action = "hiện" if plan.is_visible else "ẩn"
    session.add(AuditLog(
        admin_id=callback.from_user.id,
        action=f"toggle_plan_{action}",
        target_user_id=None,
        detail={"code": code},
    ))
    await session.commit()
    await _show_plans_list(callback, session)
    logger.info("plan toggled", extra={"code": code, "is_visible": plan.is_visible, "admin": callback.from_user.id})


# --- Delete plan ---

@router.callback_query(F.data.startswith("adm_plan_del_"))
async def cb_adm_plan_del(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("🚫 Không có quyền.", show_alert=True)
        return
    code = callback.data.removeprefix("adm_plan_del_")
    await callback.answer()

    # Check for active subscriptions with this plan
    now = datetime.now(timezone.utc)
    active_count_result = await session.execute(
        select(Subscription)
        .where(Subscription.plan_code == code)
        .where(Subscription.is_active.is_(True))
        .where(Subscription.expires_at > now)
    )
    active_subs = active_count_result.scalars().all()

    if active_subs:
        await callback.message.answer(
            f"⚠️ Không thể xóa gói <code>{code}</code> vì có "
            f"<b>{len(active_subs)} subscription đang active</b>.\n\n"
            "💡 Hãy dùng nút <b>\ud83d\udc41 Ẩn</b> thay vì xóa.",
            parse_mode="HTML",
        )
        return

    result = await session.execute(select(Plan).where(Plan.code == code))
    plan = result.scalar_one_or_none()
    if not plan:
        await callback.message.answer(f"❌ Không tìm thấy gói <code>{code}</code>.", parse_mode="HTML")
        return

    await session.delete(plan)
    session.add(AuditLog(
        admin_id=callback.from_user.id,
        action="delete_plan",
        target_user_id=None,
        detail={"code": code, "name": plan.name},
    ))
    await session.commit()
    await callback.message.answer(
        f"✅ Đã xóa gói <b>{plan.name}</b> (<code>{code}</code>).",
        parse_mode="HTML",
    )
    await _show_plans_list(callback, session)
    logger.info("plan deleted", extra={"code": code, "admin": callback.from_user.id})
