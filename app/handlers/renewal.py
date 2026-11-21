import asyncio
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from app.messages.templates import Msg
from app.keyboards.menus import plan_selection_kb, after_order_kb, PlanSelectCb
from app.models.order import Order
from app.config import settings
from app.utils.order import generate_order_code, build_transfer_description, format_vnd
from app.utils.user import get_or_create_user
from app.utils.payment import generate_vietqr_image, _notify_admins_new_order
from app.utils.plan_loader import get_plan, get_visible_plans


router = Router()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _cancel_pending_orders(user_id: int, session: AsyncSession) -> None:
    """Cancel all pending orders for a user. The check_payments job still honours
    a payment that arrives for a cancelled order within ORDER_EXPIRY_HOURS."""
    # Conditional UPDATE: never overwrite an order the payment job just marked paid.
    result = await session.execute(
        update(Order)
        .where(Order.user_id == user_id)
        .where(Order.status == "pending")
        .values(status="cancelled")
        .returning(Order.order_code)
    )
    for order_code in result.scalars().all():
        logger.info("order cancelled", extra={"order_code": order_code, "user_id": user_id})


# ---------------------------------------------------------------------------
# Entry points: /giahan command + "Gia hạn" button
# ---------------------------------------------------------------------------

@router.message(Command("giahan"), StateFilter("*"))
async def cmd_giahan(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await get_or_create_user(message.from_user, session)
    await message.answer(Msg.SELECT_PLAN, reply_markup=await plan_selection_kb(session))


@router.callback_query(F.data == "renew_start")
async def cb_renew_start(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    await get_or_create_user(callback.from_user, session)

    # 1. Cancel pending orders in DB
    await _cancel_pending_orders(user_id, session)

    # 2. If the current message is the QR photo → delete it, send new text message
    #    If it's already a text message → edit in-place
    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.bot.send_message(
            user_id,
            Msg.SELECT_PLAN,
            reply_markup=await plan_selection_kb(session),
            parse_mode="HTML",
        )
    else:
        try:
            await callback.message.edit_text(Msg.SELECT_PLAN, reply_markup=await plan_selection_kb(session))
        except TelegramBadRequest:
            pass


# ---------------------------------------------------------------------------
# Plan selected → create pending order → show payment instructions
# ---------------------------------------------------------------------------

@router.callback_query(PlanSelectCb.filter())
async def cb_plan_selected(
    callback: CallbackQuery,
    callback_data: PlanSelectCb,
    session: AsyncSession,
) -> None:
    plan_code = callback_data.plan_code
    plan = await get_plan(session, plan_code)
    if not plan:
        await callback.answer("Gói không hợp lệ / Invalid plan.", show_alert=True)
        return

    await callback.answer()

    user_id = callback.from_user.id
    username = callback.from_user.username

    # Cancel any existing pending orders for this user
    await _cancel_pending_orders(user_id, session)

    # Generate order
    order_code = generate_order_code()
    base_desc = build_transfer_description(user_id, username)
    transfer_description = f"{base_desc} {order_code}"

    order = Order(
        order_code=order_code,
        user_id=user_id,
        plan_code=plan_code,
        amount=plan["price"],
        status="pending",
        transfer_description=transfer_description,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.ORDER_EXPIRY_HOURS),
    )
    session.add(order)
    await session.flush()  # get order.id before commit

    # Notify admins about new order immediately (regardless of payment status)
    asyncio.create_task(
        _notify_admins_new_order(callback.bot, order, username)
    )

    logger.info(
        "order created",
        extra={
            "order_code": order_code,
            "user_id": user_id,
            "plan": plan_code,
            "amount": plan["price"],
        },
    )

    # Determine if we can generate a QR (requires bank + sieuthicode to be configured)
    can_generate_qr = bool(
        settings.SIEUTHICODE_API_URL
        and settings.SIEUTHICODE_BANK_ID
        and settings.BANK_ACCOUNT_NUMBER
    )

    if can_generate_qr:
        await callback.message.edit_text("⏳ Đang tạo mã QR... / Generating QR code...")

        try:
            qr_bytes = await generate_vietqr_image(plan["price"], transfer_description)
        except Exception as exc:
            logger.error("vietqr generation failed", extra={"error": str(exc)})
            await callback.message.edit_text(
                _text_instructions(plan, order_code, transfer_description),
                reply_markup=after_order_kb(),
            )
            return

        hours = settings.ORDER_EXPIRY_HOURS
        caption = (
            f"{plan['emoji']} <b>{plan['name']}</b> — {format_vnd(plan['price'])}\n\n"
            f"🔖 Mã đơn / Order: <code>{order_code}</code>\n\n"
            f"📝 <b>Nội dung chuyển khoản (bắt buộc):</b>\n"
            f"<i>Transfer description (required):</i>\n"
            f"<code>{transfer_description}</code>\n\n"
            f"⏱ Hệ thống tự xác nhận khoảng <b>1 phút</b> sau khi nhận tiền. Đơn có hiệu lực <b>{hours} giờ</b>.\n"
            f"<i>Auto-confirmed about 1 min after the transfer arrives. Order valid for {hours} hours.</i>"
        )

        # Send QR as a new photo message
        await callback.bot.send_photo(
            user_id,
            BufferedInputFile(qr_bytes, filename="payment_qr.png"),
            caption=caption,
            parse_mode="HTML",
            reply_markup=after_order_kb(),
        )

        # Remove the "Generating QR..." loading message
        try:
            await callback.message.delete()
        except Exception:
            pass
        # Payment detection is the check_payments scheduler job; nothing to start here.

    else:
        # Sieuthicode / bank not configured → fall back to text instructions
        await callback.message.edit_text(
            _text_instructions(plan, order_code, transfer_description),
            reply_markup=after_order_kb(),
        )


def _text_instructions(plan: dict, order_code: str, transfer_description: str) -> str:
    """Fallback text payment instructions when VietQR is not configured."""
    return Msg.PAYMENT_INSTRUCTIONS.format(
        emoji=plan["emoji"],
        plan_name=plan["name"],
        days=plan["days"],
        amount=format_vnd(plan["price"]),
        order_code=order_code,
        transfer_description=transfer_description,
        bank_name=settings.BANK_NAME or "Chưa cấu hình",
        account_number=settings.BANK_ACCOUNT_NUMBER or "Chưa cấu hình",
        account_name=settings.BANK_ACCOUNT_NAME or "Chưa cấu hình",
        expiry_hours=settings.ORDER_EXPIRY_HOURS,
    )


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user_id = callback.from_user.id

    await _cancel_pending_orders(user_id, session)

    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.bot.send_message(user_id, Msg.CANCELLED, parse_mode="HTML")
    else:
        try:
            await callback.message.edit_text(Msg.CANCELLED)
        except TelegramBadRequest:
            pass
