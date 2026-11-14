import time
from datetime import datetime, timezone
from typing import Any, Optional

from backend.consensus.models import LogEntry
from backend.consensus.state_machine import StateMachine
from backend.consensus.lock_models import (
    SeatLockInfo, BookingInfo,
    ReserveSeatsPayload, RenewReservationPayload,
    ReleaseReservationPayload, ConfirmBookingPayload,
    CancelBookingPayload, ExpireLeasesPayload
)
from backend.services.event_bus import ClusterEvent, EventCategory, cluster_event_bus

# Agreed timing constants in microseconds
INITIAL_LEASE_MICROS = 60 * 1_000_000        # 60 seconds
RENEWAL_INCREMENT_MICROS = 30 * 1_000_000    # 30 seconds
MAX_DURATION_MICROS = 120 * 1_000_000        # 120 seconds ceiling

def current_utc_micros() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000)

class DistributedLockStateMachine(StateMachine):
    """
    Raft Replicated State Machine implementing distributed seat locks,
    monotonic 64-bit fencing tokens, atomic all-or-nothing multi-seat operations,
    and strict lease bounds (60s initial, +30s renewal, 120s ceiling).
    """
    def __init__(self):
        self.last_applied_index: int = 0
        self.fencing_counter: int = 1000  # Monotonic 64-bit sequence
        self.seat_locks: dict[str, SeatLockInfo] = {}  # seat_id -> SeatLockInfo
        self.bookings: dict[str, BookingInfo] = {}      # booking_id -> BookingInfo
        self.fencing_audit: list[dict[str, Any]] = []  # In-memory audit log

    def _next_token(self) -> int:
        self.fencing_counter += 1
        return self.fencing_counter

    def apply(self, entry: LogEntry) -> dict[str, Any]:
        """
        Deterministically apply committed Raft log entry.
        """
        self.last_applied_index = entry.index
        cmd = entry.command
        p = entry.payload

        result = {"status": "UNKNOWN_COMMAND", "command": cmd}
        if cmd == "NOOP":
            result = {"status": "OK", "command": "NOOP"}
        elif cmd == "RESERVE_SEATS":
            result = self._apply_reserve(entry)
        elif cmd == "RENEW_RESERVATION":
            result = self._apply_renew(entry)
        elif cmd == "RELEASE_RESERVATION":
            result = self._apply_release(entry)
        elif cmd == "CONFIRM_BOOKING":
            result = self._apply_confirm(entry)
        elif cmd == "CANCEL_BOOKING":
            result = self._apply_cancel(entry)
        elif cmd == "EXPIRE_LEASES":
            result = self._apply_expire(entry)

        # Emit telemetry event
        status_val = result.get("status", "UNKNOWN")
        canonical_map = {
            ("RESERVE_SEATS", "RESERVED"): "LOCK_ACQUIRED",
            ("RESERVE_SEATS", "REJECTED_SEAT_LOCKED"): "LOCK_REJECTED",
            ("RESERVE_SEATS", "REJECTED_SEAT_BOOKED"): "LOCK_REJECTED",
            ("RESERVE_SEATS", "REJECTED_BOOKING_EXISTS"): "LOCK_REJECTED",
            ("RENEW_RESERVATION", "RENEWED"): "RESERVATION_RENEWED",
            ("RELEASE_RESERVATION", "RELEASED"): "RESERVATION_RELEASED",
            ("CONFIRM_BOOKING", "CONFIRMED"): "BOOKING_CONFIRMED",
            ("CANCEL_BOOKING", "CANCELLED"): "BOOKING_CANCELLED",
            ("EXPIRE_LEASES", "EXPIRED"): "LEASE_EXPIRED",
        }
        canonical_action = canonical_map.get((cmd, status_val), f"{cmd}_{status_val}")

        # Emit exactly one event per state machine mutation
        cluster_event_bus.publish_nowait(
            ClusterEvent(
                node_id="cluster_sm",
                term=entry.term,
                category=EventCategory.LOCK,
                action=f"{cmd}_{status_val}",
                details={
                    "index": entry.index,
                    "command": cmd,
                    "status": status_val,
                    "canonical_action": canonical_action,
                    "fencing_token": result.get("fencing_token") or entry.fencing_token,
                    "booking_id": p.get("booking_id") if isinstance(p, dict) else None,
                    "seats": p.get("seat_ids") if isinstance(p, dict) else (p.get("booking_ids") if isinstance(p, dict) else None)
                }
            )
        )

        return result

    # -------------------------------------------------------------------------
    # Core Deterministic Command Interpreters
    # -------------------------------------------------------------------------
    def _apply_reserve(self, entry: LogEntry) -> dict[str, Any]:
        p = entry.payload
        booking_id = p["booking_id"]
        show_id = p["show_id"]
        seat_ids = p["seat_ids"]
        owner_id = p["owner_id"]
        now_utc = entry.created_at_utc

        # Atomic Multi-Seat Validation: check that EVERY seat is free
        for sid in seat_ids:
            existing = self.seat_locks.get(sid)
            if existing:
                # If currently reserved or booked
                if existing.status == "BOOKED":
                    return {"status": "REJECTED_SEAT_BOOKED", "conflict_seat": sid}
                elif existing.status == "RESERVED":
                    # Check if lease expired according to entry timestamp
                    if now_utc < existing.expires_at_utc:
                        return {"status": "REJECTED_SEAT_LOCKED", "conflict_seat": sid}

        # Check booking ID uniqueness
        if booking_id in self.bookings:
            existing_b = self.bookings[booking_id]
            if existing_b.status in ["PENDING", "CONFIRMED"]:
                return {"status": "REJECTED_BOOKING_EXISTS", "booking_id": booking_id}

        # All seats are free: allocate atomic lock
        token = self._next_token()
        created_at = now_utc
        expires_at = created_at + INITIAL_LEASE_MICROS
        max_ceiling = created_at + MAX_DURATION_MICROS

        for sid in seat_ids:
            self.seat_locks[sid] = SeatLockInfo(
                seat_id=sid,
                booking_id=booking_id,
                owner_id=owner_id,
                fencing_token=token,
                status="RESERVED",
                created_at_utc=created_at,
                expires_at_utc=expires_at,
                max_expiry_ceiling_utc=max_ceiling
            )

        booking_info = BookingInfo(
            booking_id=booking_id,
            show_id=show_id,
            seat_ids=seat_ids,
            owner_id=owner_id,
            fencing_token=token,
            status="PENDING",
            idempotency_key=entry.idempotency_key,
            created_at_utc=created_at,
            expires_at_utc=expires_at,
            max_expiry_ceiling_utc=max_ceiling
        )
        self.bookings[booking_id] = booking_info

        self.fencing_audit.append({
            "resource_id": booking_id,
            "proposed_token": token,
            "accepted_token": token,
            "decision": "ACCEPTED_RESERVE",
            "timestamp": now_utc
        })

        return {
            "status": "RESERVED",
            "booking_id": booking_id,
            "fencing_token": token,
            "seat_ids": seat_ids,
            "expires_at_utc": expires_at,
            "max_expiry_ceiling_utc": max_ceiling
        }

    def _apply_renew(self, entry: LogEntry) -> dict[str, Any]:
        p = entry.payload
        booking_id = p["booking_id"]
        owner_id = p["owner_id"]
        current_token = p["current_token"]
        now_utc = entry.created_at_utc

        booking = self.bookings.get(booking_id)
        if not booking:
            return {"status": "REJECTED_NOT_FOUND", "booking_id": booking_id}

        if booking.status != "PENDING":
            return {"status": "REJECTED_INVALID_STATUS", "current_status": booking.status}

        if booking.owner_id != owner_id:
            return {"status": "REJECTED_OWNER_MISMATCH"}

        # Validate token
        if booking.fencing_token != current_token:
            self.fencing_audit.append({
                "resource_id": booking_id,
                "proposed_token": current_token,
                "accepted_token": booking.fencing_token,
                "decision": "REJECTED_STALE",
                "timestamp": now_utc
            })
            return {"status": "REJECTED_STALE_TOKEN", "expected": booking.fencing_token, "provided": current_token}

        # Check if already expired
        if now_utc >= booking.expires_at_utc:
            return {"status": "REJECTED_EXPIRED"}

        # Enforce max ceiling (120s from original creation)
        new_expiry = booking.expires_at_utc + RENEWAL_INCREMENT_MICROS
        if new_expiry > booking.max_expiry_ceiling_utc:
            new_expiry = booking.max_expiry_ceiling_utc

        if new_expiry <= booking.expires_at_utc:
            return {"status": "REJECTED_MAX_CEILING_REACHED"}

        # Generate new fencing token on renewal (invalidates old token)
        new_token = self._next_token()
        booking.fencing_token = new_token
        booking.expires_at_utc = new_expiry

        for sid in booking.seat_ids:
            s_lock = self.seat_locks.get(sid)
            if s_lock and s_lock.booking_id == booking_id:
                s_lock.fencing_token = new_token
                s_lock.expires_at_utc = new_expiry

        self.fencing_audit.append({
            "resource_id": booking_id,
            "proposed_token": new_token,
            "accepted_token": new_token,
            "decision": "ACCEPTED_RENEW",
            "timestamp": now_utc
        })

        return {
            "status": "RENEWED",
            "booking_id": booking_id,
            "fencing_token": new_token,
            "expires_at_utc": new_expiry,
            "expires_at": datetime.fromtimestamp(new_expiry / 1_000_000.0, tz=timezone.utc).isoformat()
        }

    def _apply_release(self, entry: LogEntry) -> dict[str, Any]:
        p = entry.payload
        booking_id = p["booking_id"]
        owner_id = p["owner_id"]
        current_token = p["current_token"]
        now_utc = entry.created_at_utc

        booking = self.bookings.get(booking_id)
        if not booking:
            return {"status": "REJECTED_NOT_FOUND"}

        if booking.owner_id != owner_id:
            return {"status": "REJECTED_OWNER_MISMATCH"}

        if booking.fencing_token != current_token:
            return {"status": "REJECTED_STALE_TOKEN"}

        if booking.status != "PENDING":
            return {"status": "REJECTED_INVALID_STATUS"}

        # Release seats back to AVAILABLE
        for sid in booking.seat_ids:
            self.seat_locks.pop(sid, None)

        booking.status = "CANCELLED"
        booking.cancelled_at_utc = now_utc

        return {"status": "RELEASED", "booking_id": booking_id, "freed_seats": booking.seat_ids}

    def _apply_confirm(self, entry: LogEntry) -> dict[str, Any]:
        p = entry.payload
        booking_id = p["booking_id"]
        owner_id = p["owner_id"]
        current_token = p["current_token"]
        now_utc = entry.created_at_utc

        booking = self.bookings.get(booking_id)
        if not booking:
            return {"status": "REJECTED_NOT_FOUND"}

        if booking.status != "PENDING":
            return {"status": "REJECTED_NOT_PENDING", "current_status": booking.status}

        if booking.owner_id != owner_id:
            return {"status": "REJECTED_OWNER_MISMATCH"}

        # Strict token validation
        if booking.fencing_token != current_token:
            self.fencing_audit.append({
                "resource_id": booking_id,
                "proposed_token": current_token,
                "accepted_token": booking.fencing_token,
                "decision": "REJECTED_STALE",
                "timestamp": now_utc
            })
            return {"status": "REJECTED_STALE_TOKEN", "expected": booking.fencing_token}

        # Check lease expiry
        if now_utc >= booking.expires_at_utc:
            self.fencing_audit.append({
                "resource_id": booking_id,
                "proposed_token": current_token,
                "accepted_token": booking.fencing_token,
                "decision": "REJECTED_EXPIRED",
                "timestamp": now_utc
            })
            return {"status": "REJECTED_EXPIRED"}

        # Confirm booking and set seats to BOOKED permanently
        booking.status = "CONFIRMED"
        booking.confirmed_at_utc = now_utc

        for sid in booking.seat_ids:
            s_lock = self.seat_locks.get(sid)
            if s_lock and s_lock.booking_id == booking_id:
                s_lock.status = "BOOKED"

        self.fencing_audit.append({
            "resource_id": booking_id,
            "proposed_token": current_token,
            "accepted_token": current_token,
            "decision": "ACCEPTED_CONFIRM",
            "timestamp": now_utc
        })

        return {
            "status": "CONFIRMED",
            "booking_id": booking_id,
            "fencing_token": current_token,
            "confirmed_seats": booking.seat_ids
        }

    def _apply_cancel(self, entry: LogEntry) -> dict[str, Any]:
        p = entry.payload
        booking_id = p["booking_id"]
        owner_id = p["owner_id"]
        current_token = p["current_token"]
        now_utc = entry.created_at_utc

        booking = self.bookings.get(booking_id)
        if not booking:
            return {"status": "REJECTED_NOT_FOUND"}

        if booking.status != "CONFIRMED":
            return {"status": "REJECTED_NOT_CONFIRMED", "current_status": booking.status}

        if booking.owner_id != owner_id:
            return {"status": "REJECTED_OWNER_MISMATCH"}

        if booking.fencing_token != current_token:
            return {"status": "REJECTED_STALE_TOKEN"}

        # Mark cancelled and free seats
        booking.status = "CANCELLED"
        booking.cancelled_at_utc = now_utc

        for sid in booking.seat_ids:
            self.seat_locks.pop(sid, None)

        return {"status": "CANCELLED", "booking_id": booking_id, "freed_seats": booking.seat_ids}

    def _apply_expire(self, entry: LogEntry) -> dict[str, Any]:
        p = entry.payload
        booking_ids = p.get("booking_ids", [])
        now_utc = entry.created_at_utc
        expired_count = 0
        freed_seats: list[str] = []

        for bid in booking_ids:
            booking = self.bookings.get(bid)
            if booking and booking.status == "PENDING":
                # Ensure lease deadline has actually passed relative to commit time
                if now_utc >= booking.expires_at_utc:
                    booking.status = "EXPIRED"
                    expired_count += 1
                    for sid in booking.seat_ids:
                        self.seat_locks.pop(sid, None)
                        freed_seats.append(sid)

        return {
            "status": "EXPIRED",
            "expired_count": expired_count,
            "freed_seats": freed_seats
        }

    def get_state(self) -> dict[str, Any]:
        return {
            "last_applied_index": self.last_applied_index,
            "fencing_counter": self.fencing_counter,
            "active_locks_count": len(self.seat_locks),
            "bookings_count": len(self.bookings),
            "seat_locks": {k: v.model_dump() for k, v in self.seat_locks.items()},
            "bookings": {k: v.model_dump() for k, v in self.bookings.items()},
            "fencing_audit_sample": self.fencing_audit[-10:]
        }
