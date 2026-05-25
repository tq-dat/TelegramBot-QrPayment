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
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, PLANS
from app.database import AsyncSessionLocal
from app.keyboards.admin import admin_panel_kb, admin_cancel_kb
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.subscription import Subscription
from app.models.user import User
from app.utils.invite import create_single_use_invite
from app.utils.payment import activate_subscription
from app.utils.report import generate_report

router = Router()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FSM states
# ---------------------------------------------------------------------------

class AdminFSM(StatesGroup):
    confirm_order = State()   # waiting for "order_code transaction_id"
    give_days = State()       # waiting for "user_id days"
    ban_user = State()        # waiting for "user_id [reason]"
    refund_note = State()     # waiting for "order_code note..."


# ---------------------------------------------------------------------------
# Guard helper
# ---------------------------------------------------------------------------

def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_id_list


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

@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
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
        .limit(30)
    )
    rows = result.all()

    if not rows:
        await callback.message.answer(
            "📭 Không có thành viên VIP nào đang hoạt động.",
            reply_markup=admin_panel_kb(),
        )
        return

    lines = ["👥 <b>Active members (max 30):</b>\n"]
    for sub, user in rows:
        days_left = max(0, (sub.expires_at - now).days)
        name = f"@{user.username}" if user.username else user.first_name
        plan = PLANS.get(sub.plan_code, {})
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

    lines = ["📋 <b>Đơn pending (max 20):</b>\n"]
    for order, user in rows:
        name = f"@{user.username}" if user.username else user.first_name
        plan = PLANS.get(order.plan_code, {})
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


@router.message(AdminFSM.confirm_order)
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
    plan = PLANS.get(order.plan_code, {})
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


@router.message(AdminFSM.give_days)
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


@router.message(AdminFSM.ban_user)
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


@router.message(AdminFSM.refund_note)
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


@router.message(Command("baocao"))
async def cmd_baocao(message: Message, session: AsyncSession) -> None:
    if not await _guard(message):
        return
    arg = (message.text or "").strip().split()[-1].lower() if len((message.text or "").split()) > 1 else "daily"
    period = "weekly" if arg == "weekly" else "daily"
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
