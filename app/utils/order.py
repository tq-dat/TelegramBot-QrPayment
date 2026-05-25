import uuid
from html import escape


def generate_order_code() -> str:
    """Generate a unique 11-char order code, e.g. VIPA1B2C3D4."""
    return "VIP" + uuid.uuid4().hex[:8].upper()


def build_transfer_description(
    telegram_id: int,
    username: str | None,
) -> str:
    """
    Build the exact string the user must put in the bank transfer note.
    Format: {telegram_id} {username_or_id} {order_code}

    Matching rule (Day 2): look for order_code in transaction description
    AND verify amount == order.amount.
    """
    name_part = username if username else str(telegram_id)
    # Bank transfer descriptions typically have a 50-70 char limit;
    # truncate username to stay safe.
    if len(name_part) > 20:
        name_part = name_part[:20]
    return f"{telegram_id} {name_part}"


def format_vnd(amount: int) -> str:
    """Format a VND amount with dot-separated thousands, e.g. 1.200.000đ."""
    return f"{amount:,}".replace(",", ".") + "đ"


def safe_html(text: str | None) -> str:
    """Escape user-supplied text for use inside HTML-formatted Telegram messages."""
    return escape(text or "")
