import json
import uuid
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_db
from backend.db.models import Seat, Booking, IdempotencyRecord
from backend.services.idempotency import canonical_json_hash

router = APIRouter(prefix="/api/cinema", tags=["cinema"])

# Dependency to access global raft_node from main
def get_raft_node():
    from backend.main import raft_node
    if not raft_node:
        raise HTTPException(status_code=503, detail="Raft cluster node not initialized")
    return raft_node

def verify_leader(raft_node):
    if raft_node.role.value != "LEADER":
        leader_id = raft_node.current_leader
        leader_url = raft_node.peers.get(leader_id) if leader_id else None
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail=f"Not leader. Active leader is {leader_id}",
            headers={"X-Raft-Leader": leader_url or "UNKNOWN"}
        )

# -----------------------------------------------------------------------------
# Read Queries (Seat Availability & Booking History)
# -----------------------------------------------------------------------------
@router.get("/seats/{show_id}")
async def get_seats(show_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Seat).where(Seat.show_id == show_id).order_by(Seat.seat_code)
    res = await db.execute(stmt)
    seats = res.scalars().all()
    return [
        {
            "id": s.id,
            "seat_code": s.seat_code,
            "row_label": s.row_label,
            "seat_index": s.seat_index,
            "seat_tier": s.seat_tier,
            "status": s.current_status,
            "last_fencing_token": s.last_fencing_token
        }
        for s in seats
    ]

@router.get("/bookings/{booking_id}")
async def get_booking(booking_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Booking).where(Booking.id == booking_id)
    res = await db.execute(stmt)
    b = res.scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    return {
        "id": b.id,
        "booking_reference": b.booking_reference,
        "show_id": b.show_id,
        "owner_id": b.owner_id,
        "status": b.status,
        "fencing_token": b.fencing_token,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "expires_at": b.expires_at.isoformat() if b.expires_at else None,
        "max_expiry_ceiling": b.max_expiry_ceiling.isoformat() if b.max_expiry_ceiling else None,
        "confirmed_at": b.confirmed_at.isoformat() if b.confirmed_at else None,
        "cancelled_at": b.cancelled_at.isoformat() if b.cancelled_at else None,
    }

@router.get("/bookings/customer/{owner_id}")
async def get_customer_bookings(owner_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve all bookings for a given customer owner ID from PostgreSQL with seat allocations."""
    from backend.db.models import BookingSeat
    stmt = select(Booking).where(Booking.owner_id == owner_id).order_by(Booking.created_at.desc())
    res = await db.execute(stmt)
    bookings = res.scalars().all()

    results = []
    for b in bookings:
        stmt_bs = select(BookingSeat, Seat).join(Seat, BookingSeat.seat_id == Seat.id).where(BookingSeat.booking_id == b.id)
        res_bs = await db.execute(stmt_bs)
        seats_data = []
        for bs, seat in res_bs.all():
            seats_data.append({
                "seat_id": seat.id,
                "seat_code": seat.seat_code,
                "seat_tier": seat.seat_tier,
                "seat_price": float(bs.seat_price) if bs.seat_price else (300.00 if seat.seat_tier == "VIP" else 180.00)
            })

        results.append({
            "id": b.id,
            "booking_reference": b.booking_reference,
            "show_id": b.show_id,
            "owner_id": b.owner_id,
            "customer_name": b.customer_name,
            "customer_email": b.customer_email,
            "total_amount": float(b.total_amount) if b.total_amount else 0.0,
            "status": b.status,
            "fencing_token": b.fencing_token,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "expires_at": b.expires_at.isoformat() if b.expires_at else None,
            "confirmed_at": b.confirmed_at.isoformat() if b.confirmed_at else None,
            "cancelled_at": b.cancelled_at.isoformat() if b.cancelled_at else None,
            "seats": seats_data
        })

    return results
# -----------------------------------------------------------------------------
class ReserveRequest(BaseModel):
    show_id: str
    seat_ids: list[str] = Field(..., min_length=1)
    owner_id: str
    idempotency_key: str

class RenewRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    booking_id: str
    owner_id: str
    current_token: Optional[int] = Field(default=None, alias="fencing_token")
    idempotency_key: str

class ReleaseRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    booking_id: str
    owner_id: str
    current_token: Optional[int] = Field(default=None, alias="fencing_token")
    idempotency_key: str

class ConfirmRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    booking_id: str
    owner_id: str
    current_token: Optional[int] = Field(default=None, alias="fencing_token")
    customer_name: Optional[str] = "Customer"
    customer_email: Optional[str] = "customer@example.com"
    idempotency_key: str

class CancelRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    booking_id: str
    owner_id: str
    current_token: Optional[int] = Field(default=None, alias="fencing_token")
    idempotency_key: str

# -----------------------------------------------------------------------------
# Idempotency Helper
# -----------------------------------------------------------------------------
async def check_idempotency(db: AsyncSession, key: str, payload_dict: dict[str, Any]):
    req_hash = canonical_json_hash(payload_dict)
    stmt = select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key).with_for_update()
    res = await db.execute(stmt)
    record = res.scalar_one_or_none()

    if record:
        if record.request_hash != req_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key reused with different request payload"
            )
        if record.status == "COMMITTED" and record.response_payload:
            return json.loads(record.response_payload)
        if record.status == "IN_PROGRESS":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Request with this idempotency key is already in progress"
            )

    # Insert in-progress record
    new_rec = IdempotencyRecord(idempotency_key=key, request_hash=req_hash, status="IN_PROGRESS")
    db.add(new_rec)
    await db.flush()
    return None

# -----------------------------------------------------------------------------
# State-Changing Endpoints (Routed to Raft Leader)
# -----------------------------------------------------------------------------
@router.post("/reserve")
async def reserve_seats(
    req: ReserveRequest,
    db: AsyncSession = Depends(get_db),
    raft_node=Depends(get_raft_node)
):
    verify_leader(raft_node)

    # 1. Idempotency Check
    cached = await check_idempotency(db, req.idempotency_key, req.model_dump())
    if cached:
        return cached

    booking_id = str(uuid.uuid4())
    cmd_payload = {
        "booking_id": booking_id,
        "show_id": req.show_id,
        "seat_ids": req.seat_ids,
        "owner_id": req.owner_id,
        "idempotency_key": req.idempotency_key
    }

    # 2. Propose to Raft Cluster
    success, result, err = await raft_node.propose(
        command="RESERVE_SEATS",
        payload=cmd_payload,
        idempotency_key=req.idempotency_key
    )
    if not success:
        raise HTTPException(status_code=500, detail=err or "Raft quorum commit failed")

    # If state machine rejected (e.g. seat conflict)
    if result.get("status", "").startswith("REJECTED"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)

    # 3. Leader Reconciles to PostgreSQL
    from backend.main import booking_coordinator
    if booking_coordinator:
        entry = raft_node.get_entry(raft_node.commit_index)
        if entry:
            if result.get("fencing_token"):
                entry.fencing_token = result["fencing_token"]
            db_res = await booking_coordinator.reconcile_entry(entry)
            # Ensure return always includes state machine metadata
            if isinstance(db_res, dict):
                for k, v in result.items():
                    if k not in db_res or db_res[k] is None:
                        db_res[k] = v
            return db_res

    return result

@router.post("/renew")
async def renew_reservation(
    req: RenewRequest,
    db: AsyncSession = Depends(get_db),
    raft_node=Depends(get_raft_node)
):
    verify_leader(raft_node)
    cached = await check_idempotency(db, req.idempotency_key, req.model_dump())
    if cached:
        return cached

    cmd_payload = {
        "booking_id": req.booking_id,
        "owner_id": req.owner_id,
        "current_token": req.current_token
    }

    success, result, err = await raft_node.propose(
        command="RENEW_RESERVATION",
        payload=cmd_payload,
        idempotency_key=req.idempotency_key
    )
    if not success:
        raise HTTPException(status_code=500, detail=err)

    if result.get("status", "").startswith("REJECTED"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)

    from backend.main import booking_coordinator
    if booking_coordinator:
        entry = raft_node.get_entry(raft_node.commit_index)
        if entry:
            if result.get("fencing_token"):
                entry.fencing_token = result["fencing_token"]
            db_res = await booking_coordinator.reconcile_entry(entry)
            if isinstance(db_res, dict):
                for k, v in result.items():
                    if k not in db_res or db_res[k] is None:
                        db_res[k] = v
            return db_res

    return result

@router.post("/release")
async def release_reservation(
    req: ReleaseRequest,
    db: AsyncSession = Depends(get_db),
    raft_node=Depends(get_raft_node)
):
    verify_leader(raft_node)
    cached = await check_idempotency(db, req.idempotency_key, req.model_dump())
    if cached:
        return cached

    cmd_payload = {
        "booking_id": req.booking_id,
        "owner_id": req.owner_id,
        "current_token": req.current_token
    }

    success, result, err = await raft_node.propose(
        command="RELEASE_RESERVATION",
        payload=cmd_payload,
        idempotency_key=req.idempotency_key
    )
    if not success:
        raise HTTPException(status_code=500, detail=err)

    if result.get("status", "").startswith("REJECTED"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)

    from backend.main import booking_coordinator
    if booking_coordinator:
        entry = raft_node.get_entry(raft_node.commit_index)
        if entry:
            return await booking_coordinator.reconcile_entry(entry)

    return result

@router.post("/confirm")
async def confirm_booking(
    req: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
    raft_node=Depends(get_raft_node)
):
    verify_leader(raft_node)
    cached = await check_idempotency(db, req.idempotency_key, req.model_dump())
    if cached:
        return cached

    cmd_payload = {
        "booking_id": req.booking_id,
        "owner_id": req.owner_id,
        "current_token": req.current_token,
        "customer_name": req.customer_name,
        "customer_email": req.customer_email
    }

    success, result, err = await raft_node.propose(
        command="CONFIRM_BOOKING",
        payload=cmd_payload,
        idempotency_key=req.idempotency_key
    )
    if not success:
        raise HTTPException(status_code=500, detail=err)

    if result.get("status", "").startswith("REJECTED"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)

    from backend.main import booking_coordinator
    if booking_coordinator:
        entry = raft_node.get_entry(raft_node.commit_index)
        if entry:
            return await booking_coordinator.reconcile_entry(entry)

    return result

@router.post("/cancel")
async def cancel_booking(
    req: CancelRequest,
    db: AsyncSession = Depends(get_db),
    raft_node=Depends(get_raft_node)
):
    verify_leader(raft_node)
    cached = await check_idempotency(db, req.idempotency_key, req.model_dump())
    if cached:
        return cached

    token = req.current_token
    if token is None:
        # Lookup existing token from state machine or database
        b_info = raft_node.state_machine.bookings.get(req.booking_id)
        if b_info:
            token = b_info.fencing_token
        else:
            stmt = select(Booking).where(Booking.id == req.booking_id)
            res = await db.execute(stmt)
            b_db = res.scalar_one_or_none()
            if b_db:
                token = b_db.fencing_token
            else:
                token = 1000

    cmd_payload = {
        "booking_id": req.booking_id,
        "owner_id": req.owner_id,
        "current_token": token
    }

    success, result, err = await raft_node.propose(
        command="CANCEL_BOOKING",
        payload=cmd_payload,
        idempotency_key=req.idempotency_key
    )
    if not success:
        raise HTTPException(status_code=500, detail=err)

    if result.get("status", "").startswith("REJECTED"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)

    from backend.main import booking_coordinator
    if booking_coordinator:
        entry = raft_node.get_entry(raft_node.commit_index)
        if entry:
            return await booking_coordinator.reconcile_entry(entry)

    return result
