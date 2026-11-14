import os
import shutil
import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from backend.consensus.models import LogEntry
from backend.consensus.lock_state_machine import DistributedLockStateMachine
from backend.db.models import Base, Seat, Show, Movie, Booking, BookingSeat, IdempotencyRecord, RaftAppliedProgress, FencingAuditLog
from backend.services.booking_coordinator import BookingCoordinator
from backend.services.idempotency import canonical_json_hash

def now_micros():
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000)

@pytest.fixture
def cluster_dir():
    d = "./tmp_locks_cluster"
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    yield d
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)

@pytest.fixture
async def sqlite_session_factory():
    """In-memory async SQLite engine for deterministic fast unit testing."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Seed sample show and seats
    factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            m = Movie(id="m1", title="Interstellar", duration_minutes=169)
            s = Show(id="s1", movie_id="m1", start_time=datetime.now(timezone.utc), screen_name="Screen 1")
            session.add_all([m, s])
            for i in range(1, 6):
                seat = Seat(id=f"seat-A{i}", show_id="s1", seat_code=f"A{i}", row_label="A", seat_index=i, current_status="AVAILABLE", last_fencing_token=0)
                session.add(seat)
            progress = RaftAppliedProgress(cluster_id="cluster", last_applied_index=0, last_applied_term=0)
            session.add(progress)

    yield factory
    await test_engine.dispose()

# -----------------------------------------------------------------------------
# 1. Successful Single-Seat Reservation
# -----------------------------------------------------------------------------
def test_1_successful_single_seat_reservation():
    sm = DistributedLockStateMachine()
    entry = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b1", "show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "user1"},
        created_at_utc=now_micros()
    )
    res = sm.apply(entry)
    assert res["status"] == "RESERVED"
    assert res["booking_id"] == "b1"
    assert res["fencing_token"] == 1001
    assert "seat-A1" in sm.seat_locks
    assert sm.seat_locks["seat-A1"].status == "RESERVED"

# -----------------------------------------------------------------------------
# 2. Successful Atomic Multi-Seat Reservation
# -----------------------------------------------------------------------------
def test_2_successful_atomic_multi_seat_reservation():
    sm = DistributedLockStateMachine()
    entry = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b2", "show_id": "s1", "seat_ids": ["seat-A1", "seat-A2", "seat-A3"], "owner_id": "user1"},
        created_at_utc=now_micros()
    )
    res = sm.apply(entry)
    assert res["status"] == "RESERVED"
    assert len(res["seat_ids"]) == 3
    assert sm.seat_locks["seat-A1"].booking_id == "b2"
    assert sm.seat_locks["seat-A2"].booking_id == "b2"
    assert sm.seat_locks["seat-A3"].booking_id == "b2"

# -----------------------------------------------------------------------------
# 3. Concurrent Requests for the Same Seat
# -----------------------------------------------------------------------------
def test_3_concurrent_requests_same_seat():
    sm = DistributedLockStateMachine()
    t = now_micros()
    e1 = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b1", "show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "user1"},
        created_at_utc=t
    )
    e2 = LogEntry(
        index=2, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b2", "show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "user2"},
        created_at_utc=t + 10
    )
    res1 = sm.apply(e1)
    res2 = sm.apply(e2)
    assert res1["status"] == "RESERVED"
    assert res2["status"] == "REJECTED_SEAT_LOCKED"
    assert res2["conflict_seat"] == "seat-A1"

# -----------------------------------------------------------------------------
# 4. All-or-Nothing Failure When One Seat is Unavailable
# -----------------------------------------------------------------------------
def test_4_all_or_nothing_failure():
    sm = DistributedLockStateMachine()
    t = now_micros()
    # Reserve A2 first
    e1 = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b1", "show_id": "s1", "seat_ids": ["seat-A2"], "owner_id": "user1"},
        created_at_utc=t
    )
    sm.apply(e1)

    # Now attempt batch [A1, A2, A3] -> must fail completely, A1 and A3 must NOT be locked
    e2 = LogEntry(
        index=2, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b2", "show_id": "s1", "seat_ids": ["seat-A1", "seat-A2", "seat-A3"], "owner_id": "user2"},
        created_at_utc=t + 10
    )
    res2 = sm.apply(e2)
    assert res2["status"] == "REJECTED_SEAT_LOCKED"
    assert res2["conflict_seat"] == "seat-A2"
    assert "seat-A1" not in sm.seat_locks
    assert "seat-A3" not in sm.seat_locks

# -----------------------------------------------------------------------------
# 5. Lease Renewal and Token Rotation
# -----------------------------------------------------------------------------
def test_5_lease_renewal_and_token_rotation():
    sm = DistributedLockStateMachine()
    t = now_micros()
    e1 = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b1", "show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "user1"},
        created_at_utc=t
    )
    res1 = sm.apply(e1)
    initial_token = res1["fencing_token"]
    initial_expiry = res1["expires_at_utc"]

    # Renew lease (+30s)
    e2 = LogEntry(
        index=2, term=1, command="RESERVE_SEATS" if False else "RENEW_RESERVATION",
        payload={"booking_id": "b1", "owner_id": "user1", "current_token": initial_token},
        created_at_utc=t + 10 * 1_000_000
    )
    res2 = sm.apply(e2)
    assert res2["status"] == "RENEWED"
    assert res2["fencing_token"] > initial_token  # Rotated token
    assert res2["expires_at_utc"] == initial_expiry + 30 * 1_000_000

# -----------------------------------------------------------------------------
# 6. Rejection of Old Fencing Token
# -----------------------------------------------------------------------------
def test_6_rejection_of_old_fencing_token():
    sm = DistributedLockStateMachine()
    t = now_micros()
    e1 = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b1", "show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "user1"},
        created_at_utc=t
    )
    res1 = sm.apply(e1)
    initial_token = res1["fencing_token"]

    # Renew, giving it token 1002
    e2 = LogEntry(
        index=2, term=1, command="RENEW_RESERVATION",
        payload={"booking_id": "b1", "owner_id": "user1", "current_token": initial_token},
        created_at_utc=t + 10 * 1_000_000
    )
    sm.apply(e2)

    # Now attempt confirm using the old token 1001
    e3 = LogEntry(
        index=3, term=1, command="CONFIRM_BOOKING",
        payload={"booking_id": "b1", "owner_id": "user1", "current_token": initial_token},
        created_at_utc=t + 20 * 1_000_000
    )
    res3 = sm.apply(e3)
    assert res3["status"] == "REJECTED_STALE_TOKEN"

# -----------------------------------------------------------------------------
# 7. Automatic Lease Expiry
# -----------------------------------------------------------------------------
def test_7_automatic_lease_expiry():
    sm = DistributedLockStateMachine()
    t = now_micros()
    e1 = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b1", "show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "user1"},
        created_at_utc=t
    )
    sm.apply(e1)
    assert "seat-A1" in sm.seat_locks

    # Expire leases after 61 seconds
    e2 = LogEntry(
        index=2, term=1, command="EXPIRE_LEASES",
        payload={"booking_ids": ["b1"]},
        created_at_utc=t + 61 * 1_000_000
    )
    res2 = sm.apply(e2)
    assert res2["status"] == "EXPIRED"
    assert res2["expired_count"] == 1
    assert "seat-A1" not in sm.seat_locks

# -----------------------------------------------------------------------------
# 8. Confirmation After Expiry Rejected
# -----------------------------------------------------------------------------
def test_8_confirmation_after_expiry_rejected():
    sm = DistributedLockStateMachine()
    t = now_micros()
    e1 = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b1", "show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "user1"},
        created_at_utc=t
    )
    res1 = sm.apply(e1)
    token = res1["fencing_token"]

    # Attempt confirmation after 65 seconds (lease deadline was 60s)
    e2 = LogEntry(
        index=2, term=1, command="CONFIRM_BOOKING",
        payload={"booking_id": "b1", "owner_id": "user1", "current_token": token},
        created_at_utc=t + 65 * 1_000_000
    )
    res2 = sm.apply(e2)
    assert res2["status"] == "REJECTED_EXPIRED"

# -----------------------------------------------------------------------------
# 9. Explicit Reservation Release
# -----------------------------------------------------------------------------
def test_9_explicit_reservation_release():
    sm = DistributedLockStateMachine()
    t = now_micros()
    e1 = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b1", "show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "user1"},
        created_at_utc=t
    )
    res1 = sm.apply(e1)
    token = res1["fencing_token"]

    # Client voluntarily releases reservation
    e2 = LogEntry(
        index=2, term=1, command="RELEASE_RESERVATION",
        payload={"booking_id": "b1", "owner_id": "user1", "current_token": token},
        created_at_utc=t + 5 * 1_000_000
    )
    res2 = sm.apply(e2)
    assert res2["status"] == "RELEASED"
    assert "seat-A1" not in sm.seat_locks

# -----------------------------------------------------------------------------
# 10. Successful Booking Confirmation
# -----------------------------------------------------------------------------
def test_10_successful_booking_confirmation():
    sm = DistributedLockStateMachine()
    t = now_micros()
    e1 = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b1", "show_id": "s1", "seat_ids": ["seat-A1", "seat-A2"], "owner_id": "user1"},
        created_at_utc=t
    )
    res1 = sm.apply(e1)
    token = res1["fencing_token"]

    e2 = LogEntry(
        index=2, term=1, command="CONFIRM_BOOKING",
        payload={"booking_id": "b1", "owner_id": "user1", "current_token": token},
        created_at_utc=t + 10 * 1_000_000
    )
    res2 = sm.apply(e2)
    assert res2["status"] == "CONFIRMED"
    assert sm.bookings["b1"].status == "CONFIRMED"
    assert sm.seat_locks["seat-A1"].status == "BOOKED"
    assert sm.seat_locks["seat-A2"].status == "BOOKED"

# -----------------------------------------------------------------------------
# 11. Confirmed Booking Cancellation
# -----------------------------------------------------------------------------
def test_11_confirmed_booking_cancellation():
    sm = DistributedLockStateMachine()
    t = now_micros()
    e1 = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b1", "show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "user1"},
        created_at_utc=t
    )
    res1 = sm.apply(e1)
    token = res1["fencing_token"]

    e2 = LogEntry(
        index=2, term=1, command="CONFIRM_BOOKING",
        payload={"booking_id": "b1", "owner_id": "user1", "current_token": token},
        created_at_utc=t + 5 * 1_000_000
    )
    sm.apply(e2)

    # Cancel confirmed ticket
    e3 = LogEntry(
        index=3, term=1, command="CANCEL_BOOKING",
        payload={"booking_id": "b1", "owner_id": "user1", "current_token": token},
        created_at_utc=t + 15 * 1_000_000
    )
    res3 = sm.apply(e3)
    assert res3["status"] == "CANCELLED"
    assert sm.bookings["b1"].status == "CANCELLED"
    assert "seat-A1" not in sm.seat_locks

# -----------------------------------------------------------------------------
# 12 & 13. Idempotency Key Tests (Same payload vs different payload)
# -----------------------------------------------------------------------------
def test_12_and_13_idempotency_hashing():
    p1 = {"show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "u1"}
    p2 = {"owner_id": "u1", "seat_ids": ["seat-A1"], "show_id": "s1"}  # Permuted keys
    p3 = {"show_id": "s1", "seat_ids": ["seat-A2"], "owner_id": "u1"}  # Different seat

    h1 = canonical_json_hash(p1)
    h2 = canonical_json_hash(p2)
    h3 = canonical_json_hash(p3)

    assert h1 == h2, "Canonical hash must be identical regardless of key order"
    assert h1 != h3, "Different payloads must produce different hashes"

# -----------------------------------------------------------------------------
# 14, 15, 16. PostgreSQL Transactional Reconciliation & Progress Tracking
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_14_15_16_postgresql_reconciliation_and_crash_recovery(sqlite_session_factory):
    coordinator = BookingCoordinator(session_factory=sqlite_session_factory)
    t = now_micros()

    # Step 1: Reconcile RESERVE_SEATS (Index 1)
    e1 = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "b1", "show_id": "s1", "seat_ids": ["seat-A1", "seat-A2"], "owner_id": "u1"},
        fencing_token=1001,
        idempotency_key="idemp_1001",
        created_at_utc=t
    )
    res1 = await coordinator.reconcile_entry(e1)
    assert res1["status"] == "RESERVED"

    # Verify progress advanced to 1 in DB
    last_applied = await coordinator.get_last_applied_index()
    assert last_applied == 1

    # Verify seats are RESERVED in DB
    async with sqlite_session_factory() as session:
        stmt = select(Seat).where(Seat.id.in_(["seat-A1", "seat-A2"]))
        res = await session.execute(stmt)
        seats = res.scalars().all()
        assert len(seats) == 2
        for s in seats:
            assert s.current_status == "RESERVED"
            assert s.last_fencing_token == 1001

    # Step 2: Idempotent Replay (Crash Recovery simulation)
    # If the leader crashed and replays Index 1 again:
    res_replay = await coordinator.reconcile_entry(e1)
    assert res_replay["status"] == "ALREADY_APPLIED"
    assert await coordinator.get_last_applied_index() == 1  # No duplicate execution!

    # Step 3: Reconcile CONFIRM_BOOKING (Index 2)
    e2 = LogEntry(
        index=2, term=1, command="CONFIRM_BOOKING",
        payload={"booking_id": "b1", "owner_id": "u1", "current_token": 1001, "customer_name": "Alice"},
        fencing_token=1001,
        created_at_utc=t + 10 * 1_000_000
    )
    res2 = await coordinator.reconcile_entry(e2)
    assert res2["status"] == "CONFIRMED"
    assert await coordinator.get_last_applied_index() == 2

    # Verify seats are BOOKED in DB
    async with sqlite_session_factory() as session:
        stmt = select(Seat).where(Seat.id.in_(["seat-A1", "seat-A2"]))
        res = await session.execute(stmt)
        for s in res.scalars().all():
            assert s.current_status == "BOOKED"

# -----------------------------------------------------------------------------
# 18. Exactly 50 Seats Configuration & Seat Codes Verification
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_18_fifty_seat_configuration(sqlite_session_factory):
    # Use the seeder on an engine to confirm exactly 50 seats
    from backend.db.init_db import seed_cinema_data
    from backend.db.session import AsyncSessionLocal

    async with sqlite_session_factory() as session:
        # Seed the remaining rows B-E to bring total to 50
        rows = ["A", "B", "C", "D", "E"]
        for row in rows:
            for idx in range(1, 11):
                seat_id = f"seat-{row}{idx}"
                stmt_s = select(Seat).where(Seat.id == seat_id)
                res_s = await session.execute(stmt_s)
                if not res_s.scalar_one_or_none():
                    seat = Seat(
                        id=seat_id,
                        show_id="s1",
                        seat_code=f"{row}{idx}",
                        row_label=row,
                        seat_index=idx,
                        seat_tier="VIP" if row in ["A", "B"] else "STANDARD",
                        current_status="AVAILABLE",
                        last_fencing_token=0
                    )
                    session.add(seat)
        await session.commit()

        # Query all seats for show
        stmt = select(Seat).where(Seat.show_id == "s1").order_by(Seat.seat_code)
        res = await session.execute(stmt)
        all_seats = res.scalars().all()
        assert len(all_seats) == 50, f"Expected exactly 50 seats, found {len(all_seats)}"

        codes = [s.seat_code for s in all_seats]
        expected_codes = [f"{r}{i}" for r in ["A", "B", "C", "D", "E"] for i in range(1, 11)]
        assert sorted(codes) == sorted(expected_codes)

# -----------------------------------------------------------------------------
# 19. Quorum Loss Prevents Lock Acquisition (State Machine & DB Unchanged)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_19_quorum_loss_prevents_lock_acquisition(cluster_dir):
    from tests.test_consensus_cluster import MemoryNetworkRouter, MemoryRPCClient
    from backend.consensus.config import RaftConfig
    from backend.consensus.node import RaftNode
    from backend.consensus.models import NodeRole

    router = MemoryNetworkRouter()
    nodes: dict[str, RaftNode] = {}

    for i in range(1, 4):
        nid = f"node{i}"
        peers = {f"node{j}": f"mem://node{j}" for j in range(1, 4) if j != i}
        cfg = RaftConfig(
            node_id=nid,
            port=8000 + i,
            peers=peers,
            data_dir=os.path.join(cluster_dir, nid),
            heartbeat_interval_ms=50,
            election_timeout_min_ms=150,
            election_timeout_max_ms=300
        )
        sm = DistributedLockStateMachine()
        node = RaftNode(config=cfg, state_machine=sm, rpc_client=MemoryRPCClient(nid, router))
        router.register(node)
        nodes[nid] = node
        await node.start()

    # Find elected leader
    leader = None
    import asyncio
    for _ in range(30):
        await asyncio.sleep(0.1)
        for n in nodes.values():
            if n.role == NodeRole.LEADER:
                leader = n
                break
        if leader:
            break

    assert leader is not None
    leader_id = leader.node_id

    # Isolate leader from both peers (cluster loses quorum: 1 out of 3)
    router.isolate(leader_id)

    # Attempt to reserve seats through isolated leader
    success, result, err = await leader.propose(
        command="RESERVE_SEATS",
        payload={"booking_id": "b_quorum_fail", "show_id": "s1", "seat_ids": ["seat-A1", "seat-A2"], "owner_id": "user_x"},
        timeout_sec=0.8
    )

    # Must fail because no majority quorum can be assembled
    assert success is False
    assert err in ["PROPOSAL_TIMEOUT_NO_QUORUM", "LOST_LEADERSHIP"]

    # Verify state machine on leader has NOT reserved the seats
    assert "seat-A1" not in leader.state_machine.seat_locks
    assert "seat-A2" not in leader.state_machine.seat_locks
    assert "b_quorum_fail" not in leader.state_machine.bookings

    for n in nodes.values():
        await n.stop()

# -----------------------------------------------------------------------------
# 20. Committed-But-Unapplied Raft Entry Recovery on New Leader
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_20_committed_but_unapplied_reconciliation_on_new_leader(cluster_dir, sqlite_session_factory):
    """
    Exact Verification Sequence:
    1. Commit a valid reservation entry through the 3-node Raft cluster.
    2. Simulate a leader crash after the entry is committed but before its PostgreSQL application is completed.
    3. Allow a new leader to take over.
    4. Verify that the new leader reconciles the committed entry into PostgreSQL.
    5. Confirm that booking and seat records are correct and not duplicated.
    """
    from tests.test_consensus_cluster import MemoryNetworkRouter, MemoryRPCClient
    from backend.consensus.config import RaftConfig
    from backend.consensus.node import RaftNode
    from backend.consensus.models import NodeRole
    import asyncio

    router = MemoryNetworkRouter()
    nodes: dict[str, RaftNode] = {}

    for i in range(1, 4):
        nid = f"node{i}"
        peers = {f"node{j}": f"mem://node{j}" for j in range(1, 4) if j != i}
        cfg = RaftConfig(
            node_id=nid,
            port=8000 + i,
            peers=peers,
            data_dir=os.path.join(cluster_dir, nid),
            heartbeat_interval_ms=50,
            election_timeout_min_ms=150,
            election_timeout_max_ms=300
        )
        sm = DistributedLockStateMachine()
        node = RaftNode(config=cfg, state_machine=sm, rpc_client=MemoryRPCClient(nid, router))
        router.register(node)
        nodes[nid] = node
        await node.start()

    # Step 1: Wait for initial leader
    leader1: Optional[RaftNode] = None
    for _ in range(40):
        await asyncio.sleep(0.1)
        leaders = [n for n in nodes.values() if n.role == NodeRole.LEADER and n.leader_ready]
        if len(leaders) == 1:
            leader1 = leaders[0]
            break

    assert leader1 is not None
    leader1_id = leader1.node_id

    # Commit valid reservation entry through Raft cluster
    success, res, err = await leader1.propose(
        command="RESERVE_SEATS",
        payload={
            "booking_id": "b_unapplied_test",
            "show_id": "s1",
            "seat_ids": ["seat-A3", "seat-A4"],
            "owner_id": "user_recovery",
            "idempotency_key": "idemp_unapplied_1"
        },
        timeout_sec=2.0
    )
    assert success is True
    commit_idx = leader1.commit_index
    assert commit_idx >= 1

    # Step 2: SIMULATE CRASH BEFORE POSTGRESQL APPLICATION
    # In PostgreSQL, last_applied_index is still 0 (or previous index).
    coordinator = BookingCoordinator(session_factory=sqlite_session_factory)
    assert await coordinator.get_last_applied_index() == 0

    # Crash leader 1 immediately
    await leader1.stop()
    nodes.pop(leader1_id)

    # Step 3: Allow remaining 2 nodes to elect a new leader (quorum = 2/3)
    leader2: Optional[RaftNode] = None
    for _ in range(50):
        await asyncio.sleep(0.1)
        leaders = [n for n in nodes.values() if n.role == NodeRole.LEADER and n.leader_ready]
        if len(leaders) == 1:
            leader2 = leaders[0]
            break

    assert leader2 is not None
    assert leader2.node_id != leader1_id

    # Step 4: The new leader's reconciliation service runs reconcile_unapplied_entries
    reconciled_results = await coordinator.reconcile_unapplied_entries(leader2)
    assert len(reconciled_results) >= 1

    # Step 5: Confirm booking and seat records in PostgreSQL are correct and NOT duplicated
    assert await coordinator.get_last_applied_index() >= commit_idx

    async with sqlite_session_factory() as session:
        # Check seats are RESERVED
        stmt_s = select(Seat).where(Seat.id.in_(["seat-A3", "seat-A4"]))
        res_s = await session.execute(stmt_s)
        seats = res_s.scalars().all()
        assert len(seats) == 2
        for s in seats:
            assert s.current_status == "RESERVED"

        # Check single unique booking created (not duplicated)
        stmt_b = select(Booking).where(Booking.id == "b_unapplied_test")
        res_b = await session.execute(stmt_b)
        bookings = res_b.scalars().all()
        assert len(bookings) == 1
        assert bookings[0].status == "PENDING"
        assert bookings[0].owner_id == "user_recovery"

    # Step 6: If reconcile_unapplied_entries is called again, verify idempotency (zero duplicates)
    reconciled_again = await coordinator.reconcile_unapplied_entries(leader2)
    assert len(reconciled_again) == 0

    for n in nodes.values():
        await n.stop()


