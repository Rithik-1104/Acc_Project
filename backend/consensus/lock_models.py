from typing import Any, Optional
from pydantic import BaseModel, Field

class SeatLockInfo(BaseModel):
    seat_id: str
    booking_id: str
    owner_id: str
    fencing_token: int
    status: str = Field(default="RESERVED", description="RESERVED | BOOKED")
    created_at_utc: int = Field(..., description="Unix microseconds")
    expires_at_utc: int = Field(..., description="Unix microseconds, created + 60s (initial)")
    max_expiry_ceiling_utc: int = Field(..., description="Unix microseconds, created + 120s (max)")

class BookingInfo(BaseModel):
    booking_id: str
    show_id: str
    seat_ids: list[str]
    owner_id: str
    fencing_token: int
    status: str = Field(default="PENDING", description="PENDING | CONFIRMED | CANCELLED | EXPIRED")
    idempotency_key: Optional[str] = None
    created_at_utc: int
    expires_at_utc: int
    max_expiry_ceiling_utc: int
    confirmed_at_utc: Optional[int] = None
    cancelled_at_utc: Optional[int] = None

class ReserveSeatsPayload(BaseModel):
    booking_id: str
    show_id: str
    seat_ids: list[str]
    owner_id: str
    idempotency_key: str

class RenewReservationPayload(BaseModel):
    booking_id: str
    owner_id: str
    current_token: int

class ReleaseReservationPayload(BaseModel):
    booking_id: str
    owner_id: str
    current_token: int

class ConfirmBookingPayload(BaseModel):
    booking_id: str
    owner_id: str
    current_token: int
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    total_amount: Optional[float] = None

class CancelBookingPayload(BaseModel):
    booking_id: str
    owner_id: str
    current_token: int
    reason: Optional[str] = None

class ExpireLeasesPayload(BaseModel):
    booking_ids: list[str]
