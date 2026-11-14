import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, BigInteger, Numeric, DateTime, Text, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

def utcnow():
    return datetime.now(timezone.utc)

class Movie(Base):
    __tablename__ = "movies"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    poster_url = Column(String(512), nullable=True)
    duration_minutes = Column(Integer, nullable=False)
    genre = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    shows = relationship("Show", back_populates="movie", cascade="all, delete-orphan")

class Show(Base):
    __tablename__ = "shows"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    movie_id = Column(String(36), ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    screen_name = Column(String(100), nullable=False)
    base_price = Column(Numeric(10, 2), nullable=False, default=15.00)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    movie = relationship("Movie", back_populates="shows")
    seats = relationship("Seat", back_populates="show", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="show")

class Seat(Base):
    __tablename__ = "seats"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    show_id = Column(String(36), ForeignKey("shows.id", ondelete="CASCADE"), nullable=False)
    seat_code = Column(String(10), nullable=False)  # e.g. A1, B4
    row_label = Column(String(5), nullable=False)
    seat_index = Column(Integer, nullable=False)
    seat_tier = Column(String(20), nullable=False, default="STANDARD")  # STANDARD | VIP
    current_status = Column(String(20), nullable=False, default="AVAILABLE")  # AVAILABLE | RESERVED | BOOKED
    last_fencing_token = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    show = relationship("Show", back_populates="seats")
    booking_allocations = relationship("BookingSeat", back_populates="seat")

    __table_args__ = (
        UniqueConstraint("show_id", "seat_code", name="uq_show_seat_code"),
        Index("idx_show_status", "show_id", "current_status"),
    )

class Booking(Base):
    __tablename__ = "bookings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    show_id = Column(String(36), ForeignKey("shows.id"), nullable=False)
    booking_reference = Column(String(32), unique=True, nullable=False)  # e.g. BK-XXXX
    owner_id = Column(String(128), nullable=False)
    customer_name = Column(String(255), nullable=True)
    customer_email = Column(String(255), nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=False, default=0.00)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING | CONFIRMED | CANCELLED | EXPIRED
    fencing_token = Column(BigInteger, nullable=False)
    idempotency_key = Column(String(128), unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    max_expiry_ceiling = Column(DateTime(timezone=True), nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    show = relationship("Show", back_populates="bookings")
    seats = relationship("BookingSeat", back_populates="booking", cascade="all, delete-orphan")

class BookingSeat(Base):
    __tablename__ = "booking_seats"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    booking_id = Column(String(36), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    seat_id = Column(String(36), ForeignKey("seats.id"), nullable=False)
    seat_price = Column(Numeric(10, 2), nullable=False)
    fencing_token = Column(BigInteger, nullable=False)

    booking = relationship("Booking", back_populates="seats")
    seat = relationship("Seat", back_populates="booking_allocations")

    __table_args__ = (
        UniqueConstraint("booking_id", "seat_id", name="uq_booking_seat"),
        Index("idx_booking_seat_fencing", "seat_id", "fencing_token"),
    )

class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    idempotency_key = Column(String(128), primary_key=True)
    request_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="IN_PROGRESS")  # IN_PROGRESS | COMMITTED | REJECTED
    response_payload = Column(Text, nullable=True)  # Serialized JSON
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class RaftAppliedProgress(Base):
    __tablename__ = "raft_applied_progress"

    cluster_id = Column(String(64), primary_key=True, default="cluster")
    last_applied_index = Column(BigInteger, nullable=False, default=0)
    last_applied_term = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class FencingAuditLog(Base):
    __tablename__ = "fencing_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    resource_id = Column(String(128), nullable=False)
    proposed_token = Column(BigInteger, nullable=False)
    accepted_token = Column(BigInteger, nullable=False)
    decision = Column(String(32), nullable=False)  # ACCEPTED | REJECTED_STALE | REJECTED_EXPIRED
    logged_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("idx_audit_resource", "resource_id", "logged_at"),
    )
