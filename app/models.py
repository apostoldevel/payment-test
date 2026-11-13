"""The request and response envelopes of the payment-service contract."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Op(str, Enum):
    pay = "pay"
    capture = "capture"
    cancel = "cancel"
    refund = "refund"
    status = "status"
    bind = "bind"
    unbind = "unbind"


class Outcome(str, Enum):
    success = "success"
    declined = "declined"
    unknown = "unknown"


class Role(str, Enum):
    pending = "pending"
    hold = "hold"
    paid = "paid"
    canceling = "canceling"
    refunding = "refunding"
    partial_refunded = "partial_refunded"
    refunded = "refunded"
    canceled = "canceled"
    failed = "failed"
    expired = "expired"


TEST_TOKENS = ("test_ok", "test_decline", "test_unknown", "test_drop")


class Request(BaseModel):
    """One envelope for every operation. Which fields an operation reads:

    - pay: payment, idempotency_key, amount, currency, payment_method; capture (default false)
    - capture: provider_id; amount (default: the held amount)
    - cancel, status: provider_id
    - refund: provider_id, amount
    - bind: payment_method (a test token)
    - unbind: payment_method (the id returned by bind)

    `payment_method` is a plain string: a test token (test_ok, test_decline,
    test_unknown, test_drop) or the id of a saved method from bind, which
    behaves as the token it was bound with. `metadata.notify_delay_ms` delays
    the notification of this operation (default 1000; 0 sends at once).
    `credentials` and `return_url` are accepted and ignored.
    """

    model_config = ConfigDict(extra="ignore")

    op: Optional[Op] = None
    payment: Optional[str] = None
    idempotency_key: str = Field(min_length=1)
    provider_id: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    capture: bool = False
    payment_method: Optional[str] = None
    credentials: Optional[Any] = None
    return_url: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, bool):
            raise ValueError("amount must be a decimal string")
        try:
            d = Decimal(str(v))
        except InvalidOperation as e:
            raise ValueError("amount must be a decimal string") from e
        if not d.is_finite() or d <= 0:
            raise ValueError("amount must be positive")
        return d

    def notify_delay_ms(self) -> int:
        raw = (self.metadata or {}).get("notify_delay_ms", 1000)
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 1000


class Error(BaseModel):
    code: str
    message: str


class Card(BaseModel):
    brand: str
    last4: str


class PaymentMethod(BaseModel):
    id: str
    card: Optional[Card] = None


class Response(BaseModel):
    """Always HTTP 200. Any other status, or a dropped connection, means the
    service itself is unavailable, not that the payment was refused."""

    outcome: Outcome
    role: Optional[Role] = None
    provider_id: Optional[str] = None
    provider_status: Optional[str] = None
    error: Optional[Error] = None
    payment_method: Optional[PaymentMethod] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Notification(BaseModel):
    """Posted to NOTIFY_URL/payment/notify/testpay with X-Service-Key."""

    event_id: str
    provider_id: str
    payment: Optional[str] = None
    role: Role
    provider_status: str
    raw: dict[str, Any] = Field(default_factory=dict)
