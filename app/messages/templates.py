"""
Bilingual (Vietnamese / English) message templates.
All strings use HTML formatting (bot is configured with ParseMode.HTML).
"""


class Msg:
    # ------------------------------------------------------------------
    # /start  &  main menu
    # ------------------------------------------------------------------
    WELCOME = (
        "👋 <b>Xin chào {name}!</b>  <i>Hello {name}!</i>\n\n"
        "🎵 Chào mừng bạn đến với <b>VIP Music Group Bot</b>.\n"
        "<i>Welcome to <b>VIP Music Group Bot</b>.</i>\n\n"
        "📌 <b>Lệnh có sẵn / Available commands:</b>\n"
        "• /mygoi — Xem gói hiện tại / <i>View current plan</i>\n"
        "• /giahan — Mua hoặc gia hạn / <i>Buy or renew plan</i>\n"
        "• /help — Trợ giúp / <i>Help</i>"
    )

    BANNED = (
        "🚫 <b>Tài khoản của bạn đã bị khóa.</b>\n"
        "<i>Your account has been banned.</i>\n\n"
        "Liên hệ admin nếu có thắc mắc.\n"
        "<i>Contact group admin if you have questions.</i>"
    )

    # ------------------------------------------------------------------
    # /help
    # ------------------------------------------------------------------
    HELP = (
        "❓ <b>Trợ giúp / Help</b>\n\n"
        "<b>Các lệnh / Commands:</b>\n"
        "• /start — Khởi động / <i>Start</i>\n"
        "• /mygoi — Xem gói hiện tại / <i>View current plan</i>\n"
        "• /giahan — Mua hoặc gia hạn gói / <i>Buy or renew plan</i>\n"
        "• /help — Xem trợ giúp / <i>Show help</i>\n\n"
        "📞 <b>Hỗ trợ / Support:</b>\n"
        "Liên hệ admin nhóm nếu cần hỗ trợ thanh toán.\n"
        "<i>Contact the group admin for payment support.</i>"
    )

    # ------------------------------------------------------------------
    # /mygoi
    # ------------------------------------------------------------------
    NO_PLAN = (
        "📭 <b>Bạn chưa có gói thành viên nào.</b>\n"
        "<i>You don't have an active membership plan.</i>\n\n"
        "Nhấn <b>🔄 Gia hạn</b> bên dưới để mua gói ngay!\n"
        "<i>Tap <b>🔄 Renew</b> below to purchase a plan!</i>"
    )

    PLAN_STATUS = (
        "📋 <b>Gói thành viên hiện tại / Your current plan:</b>\n\n"
        "{emoji} Gói / Plan: <b>{plan_name}</b>\n"
        "📅 Hết hạn / Expires: <b>{expires_at}</b>\n"
        "⏳ Còn lại / Remaining: <b>{days_left} ngày / days</b>"
    )

    # ------------------------------------------------------------------
    # /giahan — plan selection
    # ------------------------------------------------------------------
    SELECT_PLAN = (
        "🎯 <b>Chọn gói muốn mua / Select a plan:</b>\n\n"
        "💡 Nếu đang có gói, thời gian sẽ được <b>cộng dồn</b>.\n"
        "<i>If you have an active plan, time will be <b>stacked on top</b>.</i>"
    )

    # ------------------------------------------------------------------
    # /giahan — payment instructions
    # ------------------------------------------------------------------
    PAYMENT_INSTRUCTIONS = (
        "✅ <b>Đơn hàng đã được tạo! / Order created!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "{emoji} Gói / Plan: <b>{plan_name}</b> ({days} ngày/days)\n"
        "💰 Số tiền / Amount: <b>{amount}</b>\n"
        "🔖 Mã đơn / Order code: <code>{order_code}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🏦 <b>Thông tin chuyển khoản / Bank transfer info:</b>\n"
        "• Ngân hàng / Bank: <b>{bank_name}</b>\n"
        "• Số tài khoản / Account no.: <code>{account_number}</code>\n"
        "• Tên TK / Account name: <b>{account_name}</b>\n"
        "• Số tiền / Amount: <b>{amount}</b>\n\n"
        "📝 <b>Nội dung chuyển khoản (bắt buộc ghi đúng):</b>\n"
        "<i>Transfer description (must be exact):</i>\n"
        "<code>{transfer_description}</code>\n\n"
        "⚠️ Đơn hàng hết hạn sau <b>{expiry_hours} giờ</b> nếu chưa thanh toán.\n"
        "<i>Order expires in <b>{expiry_hours} hours</b> if unpaid.</i>\n\n"
        "Sau khi chuyển, hệ thống tự động xác nhận trong vài phút.\n"
        "<i>After transfer, the system will auto-confirm within minutes.</i>"
    )

    CANCELLED = (
        "❌ <b>Đã hủy. / Cancelled.</b>\n\n"
        "Dùng /start để quay lại menu chính.\n"
        "<i>Use /start to return to the main menu.</i>"
    )

    ERROR_GENERIC = (
        "⚠️ Đã xảy ra lỗi. Vui lòng thử lại.\n"
        "<i>An error occurred. Please try again.</i>"
    )
