from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    BOT_TOKEN: str
    ADMIN_IDS: str  # comma-separated telegram user IDs

    # Group & Topics
    GROUP_ID: int = 0
    TOPIC_RAW_ID: int = 0
    TOPIC_MINIMAL_ID: int = 0

    # Database
    DATABASE_URL: str

    # Bank / Payment
    BANK_ACCOUNT_NUMBER: str = ""
    BANK_ACCOUNT_NAME: str = ""
    BANK_NAME: str = ""

    # Sieuthicode
    SIEUTHICODE_API_URL: str = ""
    SIEUTHICODE_COOKIE: str = ""

    # VietQR (for QR payment image generation)
    # Bank ID list: https://api.vietqr.io/v2/banks
    # Common: VCB=970436, MB=970422, TCB=970407, ACB=970416
    SIEUTHICODE_BANK_ID: str = ""
    VIETQR_IMAGE_TEMPLATE: str = "https://img.vietqr.io/image/{bank_id}-{account_no}-compact2.jpg"

    # Payment monitoring
    PAYMENT_WATCH_SECONDS: int = 300   # 5 minutes
    PAYMENT_POLL_INTERVAL_SECONDS: int = 15

    # Group invite link after successful payment
    INVITE_LINK_TTL_SECONDS: int = 300  # 5 minutes, member_limit=1

    # App
    TIMEZONE: str = "Asia/Ho_Chi_Minh"
    ORDER_EXPIRY_HOURS: int = 24
    DEBUG: bool = False

    @property
    def admin_id_list(self) -> List[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip()]


settings = Settings()

# ---------------------------------------------------------------------------
# Plan definitions
# ---------------------------------------------------------------------------
PLANS: dict[str, dict] = {
    "basic": {
        "code": "basic",
        "name": "Basic",
        "days": 30,
        "price": 2_000,
        "emoji": "⭐",
    },
    "standard": {
        "code": "standard",
        "name": "Standard",
        "days": 60,
        "price": 900_000,
        "emoji": "🔥",
    },
    "premium": {
        "code": "premium",
        "name": "Premium",
        "days": 90,
        "price": 1_200_000,
        "emoji": "💎",
    },
    "ultimate": {
        "code": "ultimate",
        "name": "Ultimate",
        "days": 365,
        "price": 4_200_000,
        "emoji": "👑",
    },
}
