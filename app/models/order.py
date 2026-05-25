from sqlalchemy import BigInteger, String, DateTime, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.subscription import Subscription


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, index=True
    )
    plan_code: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # VND
    # pending | paid | expired | refunded | cancelled
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )
    # Nội dung chuyển khoản mà user cần ghi vào khi chuyển tiền
    transfer_description: Mapped[str] = mapped_column(String(255), nullable=False)
    # Transaction ID trả về từ bank (sau khi match thành công)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # admin notes
    invite_link: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # single-use group invite
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Đơn hàng hết hạn sau ORDER_EXPIRY_HOURS nếu không được thanh toán
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="orders")
    subscription: Mapped[Optional["Subscription"]] = relationship(
        "Subscription", back_populates="order", uselist=False
    )
