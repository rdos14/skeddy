"""ORM models: users and their reminders."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # chat_id
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tashkent")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message: Mapped[str] = mapped_column(Text)
    original_text: Mapped[str] = mapped_column(Text)
    human_readable: Mapped[str] = mapped_column(String(256))

    # Serialized app.nlp.recurrence.Schedule
    schedule_kind: Mapped[str] = mapped_column(String(16))
    schedule_spec: Mapped[str] = mapped_column(Text)

    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PendingDraft(Base):
    """Owner-scoped date awaiting an explicit clock; never a reminder row."""

    __tablename__ = "pending_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    original_text: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    target_date: Mapped[date] = mapped_column(Date)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PendingBatch(Base):
    """Owner-scoped preview awaiting an explicit confirmation action."""

    __tablename__ = "pending_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    original_text: Mapped[str] = mapped_column(Text)
    items_json: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MenuInputReceipt(Base):
    """Durable replay fence for successfully consumed Telegram menu replies."""

    __tablename__ = "menu_input_receipts"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ItemState(Base):
    """Additive, explicit UI state for a reminder.

    Legacy rows intentionally have no state row. Their ``active`` flag keeps
    its old scheduler meaning and is never inferred to mean completed.
    """

    __tablename__ = "item_states"

    reminder_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="reminder")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AdditionalEvent(Base):
    """One extra notification belonging to an existing reminder item."""

    __tablename__ = "additional_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reminder_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MenuDraft(Base):
    """Owner/item-scoped add-time date waiting for a clock, with a TTL."""

    __tablename__ = "menu_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    reminder_id: Mapped[int] = mapped_column(Integer, index=True)
    original_text: Mapped[str] = mapped_column(Text)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
