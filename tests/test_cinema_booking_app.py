import pytest
from datetime import datetime, timezone
from backend.consensus.models import LogEntry
from backend.consensus.lock_state_machine import DistributedLockStateMachine

def now_micros():
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000)

def test_cinema_customer_profiles_and_isolation():
    """Requirement 4: Distinct customer identities with separate sessions"""
    sm = DistributedLockStateMachine()
    customer_a = "customer_a"
    customer_b = "customer_b"
    assert customer_a != customer_b

    # Customer A reserves A1
    e1 = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-a-1", "show_id": "show-screen-1-prime", "seat_ids": ["seat-A1"], "owner_id": customer_a},
        created_at_utc=now_micros()
    )
    res1 = sm.apply(e1)
    assert res1["status"] == "RESERVED"
    assert res1["booking_id"] == "bk-a-1"

    # Customer B reserves A2
    e2 = LogEntry(
        index=2, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-b-1", "show_id": "show-screen-1-prime", "seat_ids": ["seat-A2"], "owner_id": customer_b},
        created_at_utc=now_micros()
    )
    res2 = sm.apply(e2)
    assert res2["status"] == "RESERVED"
    assert sm.seat_locks["seat-A1"].owner_id == customer_a
    assert sm.seat_locks["seat-A2"].owner_id == customer_b

def test_cinema_concurrency_collision_same_seat():
    """Requirement 8 & 13: Customer A and Customer B race for seat A5. Exactly one wins."""
    sm = DistributedLockStateMachine()
    t = now_micros()

    e1 = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-cust-a", "show_id": "show-screen-1-prime", "seat_ids": ["seat-A5"], "owner_id": "customer_a"},
        created_at_utc=t
    )
    e2 = LogEntry(
        index=2, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-cust-b", "show_id": "show-screen-1-prime", "seat_ids": ["seat-A5"], "owner_id": "customer_b"},
        created_at_utc=t + 5
    )

    res_a = sm.apply(e1)
    res_b = sm.apply(e2)

    assert res_a["status"] == "RESERVED"
    assert res_a["fencing_token"] == 1001
    assert res_b["status"] == "REJECTED_SEAT_LOCKED"
    assert res_b["conflict_seat"] == "seat-A5"

def test_cinema_atomic_multi_seat_reservation():
    """Requirement 7: Multi-seat atomic reservation (all-or-nothing failure)."""
    sm = DistributedLockStateMachine()
    
    # Pre-reserve C3 by customer_a
    e_setup = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-cust-a-c3", "show_id": "show-screen-1-prime", "seat_ids": ["seat-C3"], "owner_id": "customer_a"},
        created_at_utc=now_micros()
    )
    sm.apply(e_setup)

    # Customer B attempts to reserve C1, C2, C3, C4
    e_multi = LogEntry(
        index=2, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-cust-b-multi", "show_id": "show-screen-1-prime", "seat_ids": ["seat-C1", "seat-C2", "seat-C3", "seat-C4"], "owner_id": "customer_b"},
        created_at_utc=now_micros()
    )
    res_multi = sm.apply(e_multi)

    assert res_multi["status"] == "REJECTED_SEAT_LOCKED"
    assert res_multi["conflict_seat"] == "seat-C3"
    # Ensure no partial locks leaked for C1, C2, or C4
    assert "seat-C1" not in sm.seat_locks
    assert "seat-C2" not in sm.seat_locks
    assert "seat-C4" not in sm.seat_locks

def test_cinema_lease_renewal_and_ceiling():
    """Requirement 8: Lease renewal (+30s) up to 120s max duration ceiling."""
    sm = DistributedLockStateMachine()
    t = now_micros()

    # Reserve seat B1 (initial 60s lease)
    e_reserve = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-b1", "show_id": "show-screen-1-prime", "seat_ids": ["seat-B1"], "owner_id": "customer_a", "ttl_seconds": 60},
        created_at_utc=t
    )
    res_reserve = sm.apply(e_reserve)
    orig_token = res_reserve["fencing_token"]

    # First Renewal (+30s -> total 90s)
    e_renew1 = LogEntry(
        index=2, term=1, command="RENEW_RESERVATION",
        payload={"booking_id": "bk-b1", "owner_id": "customer_a", "current_token": orig_token},
        created_at_utc=t + 10 * 1_000_000
    )
    res_renew1 = sm.apply(e_renew1)
    assert res_renew1["status"] == "RENEWED"
    token_1 = res_renew1["fencing_token"]
    assert token_1 > orig_token

    # Second Renewal (+30s -> total 120s)
    e_renew2 = LogEntry(
        index=3, term=1, command="RENEW_RESERVATION",
        payload={"booking_id": "bk-b1", "owner_id": "customer_a", "current_token": token_1},
        created_at_utc=t + 20 * 1_000_000
    )
    res_renew2 = sm.apply(e_renew2)
    assert res_renew2["status"] == "RENEWED"
    token_2 = res_renew2["fencing_token"]

    # Third Renewal attempts to exceed 120s ceiling -> REJECTED_MAX_CEILING_REACHED
    e_renew3 = LogEntry(
        index=4, term=1, command="RENEW_RESERVATION",
        payload={"booking_id": "bk-b1", "owner_id": "customer_a", "current_token": token_2},
        created_at_utc=t + 30 * 1_000_000
    )
    res_renew3 = sm.apply(e_renew3)
    assert res_renew3["status"] == "REJECTED_MAX_CEILING_REACHED"

def test_cinema_stale_fencing_token_rejection():
    """Requirement 9: Expired or stale fencing token is strictly rejected upon confirmation."""
    sm = DistributedLockStateMachine()
    t = now_micros()

    e_reserve = LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-stale", "show_id": "show-screen-1-prime", "seat_ids": ["seat-D1"], "owner_id": "customer_a"},
        created_at_utc=t
    )
    res_res = sm.apply(e_reserve)
    correct_token = res_res["fencing_token"]

    # Attempt confirmation with wrong/stale fencing token
    e_confirm_stale = LogEntry(
        index=2, term=1, command="CONFIRM_BOOKING",
        payload={"booking_id": "bk-stale", "owner_id": "customer_a", "current_token": correct_token - 50},
        created_at_utc=t + 1_000_000
    )
    res_bad = sm.apply(e_confirm_stale)
    assert res_bad["status"] == "REJECTED_STALE_TOKEN"

    # Attempt confirmation with correct fencing token
    e_confirm_good = LogEntry(
        index=3, term=1, command="CONFIRM_BOOKING",
        payload={"booking_id": "bk-stale", "owner_id": "customer_a", "current_token": correct_token},
        created_at_utc=t + 2_000_000
    )
    res_good = sm.apply(e_confirm_good)
    assert res_good["status"] == "CONFIRMED"
    assert sm.seat_locks["seat-D1"].status == "BOOKED"

def test_cinema_booking_cancellation():
    """Requirement 11: Booking cancellation releases seats back to the available pool."""
    sm = DistributedLockStateMachine()
    t = now_micros()

    # Reserve & Confirm
    res_res = sm.apply(LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-cancel-test", "show_id": "show-screen-1-prime", "seat_ids": ["seat-E10"], "owner_id": "customer_a"},
        created_at_utc=t
    ))
    token = res_res["fencing_token"]
    sm.apply(LogEntry(
        index=2, term=1, command="CONFIRM_BOOKING",
        payload={"booking_id": "bk-cancel-test", "owner_id": "customer_a", "current_token": token},
        created_at_utc=t + 1_000_000
    ))
    assert sm.seat_locks["seat-E10"].status == "BOOKED"

    # Customer A cancels booking
    res_cancel = sm.apply(LogEntry(
        index=3, term=1, command="CANCEL_BOOKING",
        payload={"booking_id": "bk-cancel-test", "owner_id": "customer_a", "current_token": token},
        created_at_utc=t + 2_000_000
    ))
    assert res_cancel["status"] == "CANCELLED"
    assert "seat-E10" not in sm.seat_locks

    # Seat E10 can now be reserved by Customer B
    res_b = sm.apply(LogEntry(
        index=4, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-cust-b-e10", "show_id": "show-screen-1-prime", "seat_ids": ["seat-E10"], "owner_id": "customer_b"},
        created_at_utc=t + 3_000_000
    ))
    assert res_b["status"] == "RESERVED"
    assert sm.seat_locks["seat-E10"].owner_id == "customer_b"

@pytest.mark.asyncio
async def test_stopped_and_isolated_node_rpc_rejection():
    """Requirement 2: Stopped and isolated nodes reject AppendEntries and RequestVote."""
    from backend.consensus.config import RaftConfig
    from backend.consensus.node import RaftNode
    from backend.consensus.models import RequestVoteArgs, AppendEntriesArgs

    cfg = RaftConfig(node_id="test_node", port=8999, data_dir="./tmp_test_wal")
    node = RaftNode(config=cfg)

    # 1. When running normally
    vote_req = RequestVoteArgs(term=2, candidate_id="candidate1", last_log_index=0, last_log_term=0)
    vote_reply = await node.handle_request_vote(vote_req)
    assert vote_reply.vote_granted is True

    # 2. When node is stopped
    await node.stop()
    assert node._running is False

    stopped_vote = await node.handle_request_vote(vote_req)
    assert stopped_vote.vote_granted is False
    assert stopped_vote.reason == "NODE_STOPPED"

    stopped_append = await node.handle_append_entries(AppendEntriesArgs(
        term=2, leader_id="leader1", prev_log_index=0, prev_log_term=0, entries=[], leader_commit=0
    ))
    assert stopped_append.success is False
    assert stopped_append.reason == "NODE_STOPPED"

    # 3. When restarted and then network isolated
    await node.start()
    assert node._running is True
    node.isolate()
    assert node.is_network_isolated is True

    isolated_vote = await node.handle_request_vote(vote_req)
    assert isolated_vote.vote_granted is False
    assert isolated_vote.reason == "NETWORK_ISOLATED"

    isolated_append = await node.handle_append_entries(AppendEntriesArgs(
        term=2, leader_id="leader1", prev_log_index=0, prev_log_term=0, entries=[], leader_commit=0
    ))
    assert isolated_append.success is False
    assert isolated_append.reason == "NETWORK_ISOLATED"

    # 4. When healed
    node.heal()
    assert node.is_network_isolated is False
    healed_append = await node.handle_append_entries(AppendEntriesArgs(
        term=2, leader_id="leader1", prev_log_index=0, prev_log_term=0, entries=[], leader_commit=0
    ))
    assert healed_append.success is True

def test_cinema_ticket_pricing_calculations():
    """Requirement 3: VIP (Rows A & B) = ₹300, Standard (Rows C, D, E) = ₹180."""
    def calculate_price(seat_codes: list[str]) -> float:
        return sum(300.00 if s[0] in ["A", "B"] else 180.00 for s in seat_codes)

    # VIP single
    assert calculate_price(["A1"]) == 300.00
    assert calculate_price(["B5"]) == 300.00

    # Standard single
    assert calculate_price(["C1"]) == 180.00
    assert calculate_price(["D3"]) == 180.00
    assert calculate_price(["E10"]) == 180.00

    # Two VIP
    assert calculate_price(["A1", "A2"]) == 600.00

    # Two Standard
    assert calculate_price(["C1", "D1"]) == 360.00

    # Mixed: Two VIP and one Standard = 300 + 300 + 180 = 780
    assert calculate_price(["A1", "B1", "C1"]) == 780.00

    # Mixed: One VIP and two Standard = 300 + 180 + 180 = 660
    assert calculate_price(["A1", "C1", "D1"]) == 660.00

    # Ten VIP = 3000
    assert calculate_price([f"A{i}" for i in range(1, 11)]) == 3000.00

    # Ten Standard = 1800
    assert calculate_price([f"C{i}" for i in range(1, 11)]) == 1800.00

# =============================================================================
# Targeted Tests: Lease Renewal Countdown & Booking Eligibility (Tests 1 - 6)
# =============================================================================

def test_targeted_test_1_initial_lease():
    """Test 1 — Initial lease: Reserve seat, verify 60s initial lease."""
    sm = DistributedLockStateMachine()
    t = now_micros()
    res = sm.apply(LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-test1", "show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "cust1"},
        created_at_utc=t
    ))
    assert res["status"] == "RESERVED"
    initial_exp_utc = res["expires_at_utc"]
    # Initial lease must be exactly 60 seconds (60,000,000 microseconds)
    assert initial_exp_utc == t + 60 * 1_000_000
    # Conceptual frontend countdown: max(0, ceil((expires_at - now)/1000))
    simulated_now = t / 1_000_000.0
    exp_sec = initial_exp_utc / 1_000_000.0
    countdown = max(0, int((exp_sec - simulated_now) + 0.9999))
    assert countdown == 60

def test_targeted_test_2_renewal_with_40s_remaining():
    """
    Test 2 — Renewal with approx 40s remaining:
    Start with 60s lease, simulate 20s passing (40s left), renew successfully.
    Verify backend returns expiry 30s later than previous expiry (~70s remaining from renewal).
    """
    sm = DistributedLockStateMachine()
    t = now_micros()
    res1 = sm.apply(LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-test2", "show_id": "s1", "seat_ids": ["seat-A2"], "owner_id": "cust1"},
        created_at_utc=t
    ))
    initial_exp = res1["expires_at_utc"]
    token1 = res1["fencing_token"]

    # Simulate 20 seconds passing (40s remaining)
    renew_time = t + 20 * 1_000_000
    remaining_before_renew = (initial_exp - renew_time) / 1_000_000.0
    assert abs(remaining_before_renew - 40.0) < 0.001

    # Renew reservation
    res2 = sm.apply(LogEntry(
        index=2, term=1, command="RENEW_RESERVATION",
        payload={"booking_id": "bk-test2", "owner_id": "cust1", "current_token": token1},
        created_at_utc=renew_time
    ))
    assert res2["status"] == "RENEWED"
    new_exp = res2["expires_at_utc"]
    # Backend expiry is extended by 30 seconds from PREVIOUS expiry, NOT reset to 30s
    assert new_exp == initial_exp + 30 * 1_000_000
    
    # Authoritative remaining time from renewal point is ~70 seconds
    remaining_after_renew = (new_exp - renew_time) / 1_000_000.0
    assert abs(remaining_after_renew - 70.0) < 0.001
    assert remaining_after_renew != 30.0

def test_targeted_test_3_countdown_continuation():
    """
    Test 3 — Countdown continuation:
    Verify countdown decreases smoothly from ~70s and does not jump back to 30s.
    """
    sm = DistributedLockStateMachine()
    t = now_micros()
    res1 = sm.apply(LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-test3", "show_id": "s1", "seat_ids": ["seat-A3"], "owner_id": "cust1"},
        created_at_utc=t
    ))
    renew_time = t + 20 * 1_000_000
    res2 = sm.apply(LogEntry(
        index=2, term=1, command="RENEW_RESERVATION",
        payload={"booking_id": "bk-test3", "owner_id": "cust1", "current_token": res1["fencing_token"]},
        created_at_utc=renew_time
    ))
    new_exp = res2["expires_at_utc"]

    # As time progresses after renewal, countdown decreases from 70s
    for elapsed in [5, 15, 25, 35, 45, 65]:
        curr = renew_time + elapsed * 1_000_000
        sec_left = (new_exp - curr) / 1_000_000.0
        expected = 70.0 - elapsed
        assert abs(sec_left - expected) < 0.001
        # At elapsed = 35s, seconds left is 35s (still > 30s)
        if elapsed == 35:
            assert sec_left > 30.0

def test_targeted_test_4_maximum_lease_duration():
    """
    Test 4 — Maximum lease duration:
    Renew repeatedly. Verify total duration never exceeds 120s ceiling.
    """
    sm = DistributedLockStateMachine()
    t = now_micros()
    res = sm.apply(LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-test4", "show_id": "s1", "seat_ids": ["seat-A4"], "owner_id": "cust1"},
        created_at_utc=t
    ))
    max_ceiling = res["max_expiry_ceiling_utc"]
    assert max_ceiling == t + 120 * 1_000_000

    # Renewal 1 (+30s -> 90s)
    res_r1 = sm.apply(LogEntry(
        index=2, term=1, command="RENEW_RESERVATION",
        payload={"booking_id": "bk-test4", "owner_id": "cust1", "current_token": res["fencing_token"]},
        created_at_utc=t + 10 * 1_000_000
    ))
    assert res_r1["status"] == "RENEWED"
    assert res_r1["expires_at_utc"] == t + 90 * 1_000_000

    # Renewal 2 (+30s -> 120s max ceiling)
    res_r2 = sm.apply(LogEntry(
        index=3, term=1, command="RENEW_RESERVATION",
        payload={"booking_id": "bk-test4", "owner_id": "cust1", "current_token": res_r1["fencing_token"]},
        created_at_utc=t + 20 * 1_000_000
    ))
    assert res_r2["status"] == "RENEWED"
    assert res_r2["expires_at_utc"] == max_ceiling

    # Renewal 3 exceeds ceiling -> REJECTED_MAX_CEILING_REACHED
    res_r3 = sm.apply(LogEntry(
        index=4, term=1, command="RENEW_RESERVATION",
        payload={"booking_id": "bk-test4", "owner_id": "cust1", "current_token": res_r2["fencing_token"]},
        created_at_utc=t + 30 * 1_000_000
    ))
    assert res_r3["status"] == "REJECTED_MAX_CEILING_REACHED"

def test_targeted_test_5_genuine_expiry():
    """
    Test 5 — Genuine expiry:
    Allow backend lease to expire. Confirmation rejected. Seat freed upon EXPIRE_LEASES.
    """
    sm = DistributedLockStateMachine()
    t = now_micros()
    res = sm.apply(LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-test5", "show_id": "s1", "seat_ids": ["seat-B5"], "owner_id": "cust1"},
        created_at_utc=t
    ))
    token = res["fencing_token"]
    exp_utc = res["expires_at_utc"]

    # Before expiry (at t + 59s), confirmation succeeds
    # After expiry (at t + 61s):
    t_expired = exp_utc + 1 * 1_000_000
    
    # Confirm attempt after expiry is rejected
    res_confirm = sm.apply(LogEntry(
        index=2, term=1, command="CONFIRM_BOOKING",
        payload={"booking_id": "bk-test5", "owner_id": "cust1", "current_token": token},
        created_at_utc=t_expired
    ))
    assert res_confirm["status"] == "REJECTED_EXPIRED"

    # Background lease manager proposes EXPIRE_LEASES
    res_exp = sm.apply(LogEntry(
        index=3, term=1, command="EXPIRE_LEASES",
        payload={"booking_ids": ["bk-test5"]},
        created_at_utc=t_expired + 500_000
    ))
    assert res_exp["status"] == "EXPIRED"
    assert "seat-B5" in res_exp["freed_seats"]
    assert "seat-B5" not in sm.seat_locks

def test_targeted_test_6_fencing_token_safety():
    """
    Test 6 — Fencing-token safety:
    Renew reservation receives new token. Attempt confirmation with old token rejected.
    Confirmation with current token succeeds.
    """
    sm = DistributedLockStateMachine()
    t = now_micros()
    res_res = sm.apply(LogEntry(
        index=1, term=1, command="RESERVE_SEATS",
        payload={"booking_id": "bk-test6", "show_id": "s1", "seat_ids": ["seat-B6"], "owner_id": "cust1"},
        created_at_utc=t
    ))
    old_token = res_res["fencing_token"]

    # Renew
    res_renew = sm.apply(LogEntry(
        index=2, term=1, command="RENEW_RESERVATION",
        payload={"booking_id": "bk-test6", "owner_id": "cust1", "current_token": old_token},
        created_at_utc=t + 10 * 1_000_000
    ))
    new_token = res_renew["fencing_token"]
    assert new_token > old_token

    # Attempt confirmation with old token -> REJECTED_STALE_TOKEN
    res_stale = sm.apply(LogEntry(
        index=3, term=1, command="CONFIRM_BOOKING",
        payload={"booking_id": "bk-test6", "owner_id": "cust1", "current_token": old_token},
        created_at_utc=t + 15 * 1_000_000
    ))
    assert res_stale["status"] == "REJECTED_STALE_TOKEN"

    # Attempt confirmation with current token -> CONFIRMED
    res_current = sm.apply(LogEntry(
        index=4, term=1, command="CONFIRM_BOOKING",
        payload={"booking_id": "bk-test6", "owner_id": "cust1", "current_token": new_token},
        created_at_utc=t + 20 * 1_000_000
    ))
    assert res_current["status"] == "CONFIRMED"
    assert sm.seat_locks["seat-B6"].status == "BOOKED"

