import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.consensus.models import LogEntry
from backend.db.models import (
    Movie, Show, Seat, Booking, BookingSeat,
    IdempotencyRecord, RaftAppliedProgress, FencingAuditLog
)

logger = logging.getLogger("coordinator")

def micros_to_datetime(micros: int) -> datetime:
    return datetime.fromtimestamp(micros / 1_000_000.0, tz=timezone.utc)

class BookingCoordinator:
    """
    Coordinates durable, transactional reconciliation between committed Raft operations
    and PostgreSQL 16. Ensures that only the current Leader applies business writes,
    verifies monotonic fencing tokens, prevents duplicate execution via raft_applied_progress,
    and caches responses in idempotency_records.
    """
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def get_last_applied_index(self) -> int:
        async with self.session_factory() as session:
            stmt = select(RaftAppliedProgress).where(RaftAppliedProgress.cluster_id == "cluster")
            res = await session.execute(stmt)
            row = res.scalar_one_or_none()
            return row.last_applied_index if row else 0

    async def reconcile_unapplied_entries(self, raft_node) -> list[dict[str, Any]]:
        """
        Invoked when a node becomes Leader:
        Queries raft_applied_progress.last_applied_index and applies any committed entries
        from (last_applied_index + 1) up to commit_index.
        """
        results = []
        last_applied = await self.get_last_applied_index()
        while last_applied < raft_node.commit_index:
            target_idx = last_applied + 1
            entry = raft_node.get_entry(target_idx)
            if not entry:
                break
            res = await self.reconcile_entry(entry)
            results.append(res)
            last_applied = await self.get_last_applied_index()
        return results

    async def reconcile_entry(self, entry: LogEntry) -> dict[str, Any]:
        """
        Atomically applies a committed Raft entry to PostgreSQL inside an ACID transaction.
        Updates raft_applied_progress.last_applied_index in the same transaction.
        """
        async with self.session_factory() as session:
            async with session.begin():
                # 1. Check if this entry has already been applied in Postgres
                stmt = select(RaftAppliedProgress).where(RaftAppliedProgress.cluster_id == "cluster").with_for_update()
                res = await session.execute(stmt)
                progress = res.scalar_one_or_none()

                if not progress:
                    progress = RaftAppliedProgress(cluster_id="cluster", last_applied_index=0, last_applied_term=0)
                    session.add(progress)
                    await session.flush()

                if entry.index <= progress.last_applied_index:
                    # Already applied: idempotent skip
                    return {"status": "ALREADY_APPLIED", "index": entry.index}

                # 2. Interpret command
                result: dict[str, Any] = {}
                cmd = entry.command
                p = entry.payload

                if cmd == "NOOP":
                    result = {"status": "OK", "command": "NOOP"}

                elif cmd == "RESERVE_SEATS":
                    result = await self._reconcile_reserve(session, entry)

                elif cmd == "RENEW_RESERVATION":
                    result = await self._reconcile_renew(session, entry)

                elif cmd == "RELEASE_RESERVATION":
                    result = await self._reconcile_release(session, entry)

                elif cmd == "CONFIRM_BOOKING":
                    result = await self._reconcile_confirm(session, entry)

                elif cmd == "CANCEL_BOOKING":
                    result = await self._reconcile_cancel(session, entry)

                elif cmd == "EXPIRE_LEASES":
                    result = await self._reconcile_expire(session, entry)

                # 3. Cache response in idempotency_records if key is present
                if entry.idempotency_key:
                    stmt_idemp = select(IdempotencyRecord).where(
                        IdempotencyRecord.idempotency_key == entry.idempotency_key
                    ).with_for_update()
                    res_idemp = await session.execute(stmt_idemp)
                    idemp_rec = res_idemp.scalar_one_or_none()
                    if idemp_rec:
                        idemp_rec.status = "COMMITTED"
                        idemp_rec.response_payload = json.dumps(result)

                # 4. Advance progress index atomically
                progress.last_applied_index = entry.index
                progress.last_applied_term = entry.term

                return result

    # -------------------------------------------------------------------------
    # Transactional Command Handlers
    # -------------------------------------------------------------------------
    async def _reconcile_reserve(self, session: AsyncSession, entry: LogEntry) -> dict[str, Any]:
        p = entry.payload
        booking_id = p["booking_id"]
        show_id = p["show_id"]
        seat_ids = p["seat_ids"]
        owner_id = p["owner_id"]
        token = entry.fencing_token or 1000

        # Fetch seats with row lock
        stmt = select(Seat).where(Seat.id.in_(seat_ids)).with_for_update()
        res = await session.execute(stmt)
        seats = res.scalars().all()

        if len(seats) != len(seat_ids):
            return {"status": "ERROR_SEATS_NOT_FOUND"}

        # Validate that no seat has a higher fencing token
        for s in seats:
            if s.last_fencing_token > token:
                # Log stale attempt
                audit = FencingAuditLog(
                    resource_id=s.id,
                    proposed_token=token,
                    accepted_token=s.last_fencing_token,
                    decision="REJECTED_STALE"
                )
                session.add(audit)
                return {"status": "REJECTED_STALE_TOKEN", "seat_id": s.id}

        # Update seat statuses & tokens
        now_dt = micros_to_datetime(entry.created_at_utc)
        expires_dt = micros_to_datetime(entry.created_at_utc + 60 * 1_000_000)
        ceiling_dt = micros_to_datetime(entry.created_at_utc + 120 * 1_000_000)

        total_price = sum(300.00 if s.seat_tier == "VIP" else 180.00 for s in seats)
        for s in seats:
            s.current_status = "RESERVED"
            s.last_fencing_token = token
            audit = FencingAuditLog(
                resource_id=s.id,
                proposed_token=token,
                accepted_token=token,
                decision="ACCEPTED_RESERVE"
            )
            session.add(audit)

        # Create booking record
        booking = Booking(
            id=booking_id,
            show_id=show_id,
            booking_reference=f"BK-{booking_id[:8].upper()}",
            owner_id=owner_id,
            total_amount=total_price,
            status="PENDING",
            fencing_token=token,
            idempotency_key=entry.idempotency_key,
            created_at=now_dt,
            expires_at=expires_dt,
            max_expiry_ceiling=ceiling_dt
        )
        session.add(booking)

        for s in seats:
            seat_price = 300.00 if s.seat_tier == "VIP" else 180.00
            bs = BookingSeat(
                booking_id=booking_id,
                seat_id=s.id,
                seat_price=seat_price,
                fencing_token=token
            )
            session.add(bs)

        return {
            "status": "RESERVED",
            "booking_id": booking_id,
            "fencing_token": token,
            "seat_ids": seat_ids,
            "total_amount": float(total_price),
            "expires_at": expires_dt.isoformat()
        }

    async def _reconcile_renew(self, session: AsyncSession, entry: LogEntry) -> dict[str, Any]:
        p = entry.payload
        booking_id = p["booking_id"]
        token = entry.fencing_token

        stmt = select(Booking).where(Booking.id == booking_id).with_for_update()
        res = await session.execute(stmt)
        booking = res.scalar_one_or_none()

        if not booking:
            return {"status": "REJECTED_NOT_FOUND"}

        # Calculate new expiry by extending existing lease by 30 seconds (up to max ceiling)
        from datetime import timedelta
        base_exp = booking.expires_at if booking.expires_at else micros_to_datetime(entry.created_at_utc)
        new_expires_dt = base_exp + timedelta(seconds=30)
        if new_expires_dt > booking.max_expiry_ceiling:
            new_expires_dt = booking.max_expiry_ceiling

        booking.fencing_token = token
        booking.expires_at = new_expires_dt

        # Update seat tokens
        stmt_bs = select(BookingSeat).where(BookingSeat.booking_id == booking_id)
        res_bs = await session.execute(stmt_bs)
        b_seats = res_bs.scalars().all()
        for bs in b_seats:
            bs.fencing_token = token
            stmt_s = select(Seat).where(Seat.id == bs.seat_id).with_for_update()
            res_s = await session.execute(stmt_s)
            seat = res_s.scalar_one_or_none()
            if seat:
                seat.last_fencing_token = token

        return {
            "status": "RENEWED",
            "booking_id": booking_id,
            "fencing_token": token,
            "expires_at": new_expires_dt.isoformat()
        }

    async def _reconcile_release(self, session: AsyncSession, entry: LogEntry) -> dict[str, Any]:
        p = entry.payload
        booking_id = p["booking_id"]

        stmt = select(Booking).where(Booking.id == booking_id).with_for_update()
        res = await session.execute(stmt)
        booking = res.scalar_one_or_none()
        if not booking:
            return {"status": "REJECTED_NOT_FOUND"}

        booking.status = "CANCELLED"
        booking.cancelled_at = micros_to_datetime(entry.created_at_utc)

        # Release seats
        stmt_bs = select(BookingSeat).where(BookingSeat.booking_id == booking_id)
        res_bs = await session.execute(stmt_bs)
        for bs in res_bs.scalars().all():
            stmt_s = select(Seat).where(Seat.id == bs.seat_id).with_for_update()
            res_s = await session.execute(stmt_s)
            seat = res_s.scalar_one_or_none()
            if seat:
                seat.current_status = "AVAILABLE"

        return {"status": "RELEASED", "booking_id": booking_id}

    async def _reconcile_confirm(self, session: AsyncSession, entry: LogEntry) -> dict[str, Any]:
        p = entry.payload
        booking_id = p["booking_id"]
        current_token = p["current_token"]

        stmt = select(Booking).where(Booking.id == booking_id).with_for_update()
        res = await session.execute(stmt)
        booking = res.scalar_one_or_none()
        if not booking:
            return {"status": "REJECTED_NOT_FOUND"}

        # Stale token validation
        if booking.fencing_token != current_token:
            audit = FencingAuditLog(
                resource_id=booking_id,
                proposed_token=current_token,
                accepted_token=booking.fencing_token,
                decision="REJECTED_STALE"
            )
            session.add(audit)
            return {"status": "REJECTED_STALE_TOKEN"}

        booking.status = "CONFIRMED"
        booking.confirmed_at = micros_to_datetime(entry.created_at_utc)
        if p.get("customer_name"):
            booking.customer_name = p["customer_name"]
        if p.get("customer_email"):
            booking.customer_email = p["customer_email"]

        # Confirm seats
        stmt_bs = select(BookingSeat).where(BookingSeat.booking_id == booking_id)
        res_bs = await session.execute(stmt_bs)
        for bs in res_bs.scalars().all():
            stmt_s = select(Seat).where(Seat.id == bs.seat_id).with_for_update()
            res_s = await session.execute(stmt_s)
            seat = res_s.scalar_one_or_none()
            if seat:
                seat.current_status = "BOOKED"

        # Collect confirmed seats details
        seats_summary = []
        stmt_bs_info = select(BookingSeat, Seat).join(Seat, BookingSeat.seat_id == Seat.id).where(BookingSeat.booking_id == booking_id)
        res_bs_info = await session.execute(stmt_bs_info)
        for bs, s in res_bs_info.all():
            seats_summary.append({
                "seat_id": s.id,
                "seat_code": s.seat_code,
                "seat_tier": s.seat_tier,
                "seat_price": float(bs.seat_price) if bs.seat_price else (300.0 if s.seat_tier == "VIP" else 180.0)
            })

        return {
            "status": "CONFIRMED",
            "booking_id": booking_id,
            "fencing_token": current_token,
            "owner_id": booking.owner_id,
            "customer_name": booking.customer_name,
            "customer_email": booking.customer_email,
            "total_amount": float(booking.total_amount) if booking.total_amount else 0.0,
            "seats": seats_summary,
            "confirmed_at": booking.confirmed_at.isoformat() if booking.confirmed_at else None
        }

    async def _reconcile_cancel(self, session: AsyncSession, entry: LogEntry) -> dict[str, Any]:
        p = entry.payload
        booking_id = p["booking_id"]

        stmt = select(Booking).where(Booking.id == booking_id).with_for_update()
        res = await session.execute(stmt)
        booking = res.scalar_one_or_none()
        if not booking:
            return {"status": "REJECTED_NOT_FOUND"}

        booking.status = "CANCELLED"
        booking.cancelled_at = micros_to_datetime(entry.created_at_utc)

        stmt_bs = select(BookingSeat).where(BookingSeat.booking_id == booking_id)
        res_bs = await session.execute(stmt_bs)
        for bs in res_bs.scalars().all():
            stmt_s = select(Seat).where(Seat.id == bs.seat_id).with_for_update()
            res_s = await session.execute(stmt_s)
            seat = res_s.scalar_one_or_none()
            if seat:
                seat.current_status = "AVAILABLE"

        return {"status": "CANCELLED", "booking_id": booking_id}

    async def _reconcile_expire(self, session: AsyncSession, entry: LogEntry) -> dict[str, Any]:
        p = entry.payload
        booking_ids = p.get("booking_ids", [])
        for bid in booking_ids:
            stmt = select(Booking).where(Booking.id == bid).with_for_update()
            res = await session.execute(stmt)
            b = res.scalar_one_or_none()
            if b and b.status == "PENDING":
                b.status = "EXPIRED"
                stmt_bs = select(BookingSeat).where(BookingSeat.booking_id == bid)
                res_bs = await session.execute(stmt_bs)
                for bs in res_bs.scalars().all():
                    stmt_s = select(Seat).where(Seat.id == bs.seat_id).with_for_update()
                    res_s = await session.execute(stmt_s)
                    seat = res_s.scalar_one_or_none()
                    if seat:
                        seat.current_status = "AVAILABLE"

        return {"status": "EXPIRED", "count": len(booking_ids)}
