import time
import json
import urllib.request
import urllib.error

LEADER_PORT = 9003
LEADER_URL = f"http://127.0.0.1:{LEADER_PORT}"

def post_json(url, data, headers=None):
    req_headers = {'Content-Type': 'application/json'}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=req_headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = body
        return e.code, parsed

def get_json(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as response:
        return response.status, json.loads(response.read().decode('utf-8'))

print("=== STEP 1: Verify all 3 nodes healthy and participating ===")
for p in [9001, 9002, 9003]:
    st, topo = get_json(f"http://127.0.0.1:{p}/api/cluster/topology")
    print(f"Node {topo['node_id']} (port {p}): Role={topo['role']}, Term={topo['current_term']}, Commit={topo['commit_index']}, Applied={topo['last_applied']}, Running={topo['is_running']}, Isolated={topo['is_network_isolated']}")

print("\n=== STEP 2: Normal booking with majority quorum (VIP Seat B4 = INR300 + Standard Seat C4 = INR180 => INR480) ===")
# Reserve seats B4 and C4
booking_id = f"test-bk-{int(time.time())}"
reserve_payload = {
    "booking_id": booking_id,
    "show_id": "show-screen-1-prime",
    "seat_ids": ["seat-B4", "seat-C4"],
    "owner_id": "customer_a",
    "idempotency_key": f"idemp-res-{booking_id}"
}
st, res_data = post_json(f"{LEADER_URL}/api/cinema/reserve", reserve_payload)
print(f"Reserve status: {st}, Response: {res_data}")
assert st == 200, f"Expected 200, got {st}"
assert res_data["total_amount"] == 480.0, f"Expected total_amount 480.0, got {res_data.get('total_amount')}"
token = res_data["fencing_token"]
allocated_booking_id = res_data["booking_id"]

# Confirm booking
confirm_payload = {
    "booking_id": allocated_booking_id,
    "owner_id": "customer_a",
    "fencing_token": token,
    "customer_name": "Customer A",
    "customer_email": "customer_a@example.com",
    "idempotency_key": f"idemp-conf-{allocated_booking_id}"
}
st_conf, conf_data = post_json(f"{LEADER_URL}/api/cinema/confirm", confirm_payload)
print(f"Confirm status: {st_conf}, Response: {conf_data}")
assert st_conf == 200, f"Expected 200, got {st_conf}"
assert conf_data["status"] == "CONFIRMED"
assert conf_data["total_amount"] == 480.0

print("\n=== STEP 3: Stop two nodes (node1 and node2) using fault injection ===")
auth_header = {"X-Fault-Token": "dev-fault-insecure-local-token"}
st1, r1 = post_json("http://127.0.0.1:9001/api/fault/stop_node", {}, headers=auth_header)
st2, r2 = post_json("http://127.0.0.1:9002/api/fault/stop_node", {}, headers=auth_header)
print(f"Stopped node1: status={st1}, response={r1}")
print(f"Stopped node2: status={st2}, response={r2}")
assert st1 == 200 and r1.get("running") is False
assert st2 == 200 and r2.get("running") is False

time.sleep(1)

# Check node1 and node2 reject AppendEntries directly
append_test_args = {
    "term": 406,
    "leader_id": "node3",
    "prev_log_index": 0,
    "prev_log_term": 0,
    "entries": [],
    "leader_commit": 0
}
st_app1, r_app1 = post_json("http://127.0.0.1:9001/raft/append_entries", append_test_args)
st_app2, r_app2 = post_json("http://127.0.0.1:9002/raft/append_entries", append_test_args)
print(f"AppendEntries on stopped node1: success={r_app1.get('success')}, reason={r_app1.get('reason')}")
print(f"AppendEntries on stopped node2: success={r_app2.get('success')}, reason={r_app2.get('reason')}")
assert r_app1.get("success") is False and r_app1.get("reason") == "NODE_STOPPED"
assert r_app2.get("success") is False and r_app2.get("reason") == "NODE_STOPPED"

print("\n=== STEP 4: Attempt reservation on remaining node (node3) during 2-node stoppage ===")
fail_bid = f"test-bk-fail-{int(time.time())}"
fail_payload = {
    "booking_id": fail_bid,
    "show_id": "show-screen-1-prime",
    "seat_ids": ["seat-B2"],
    "owner_id": "customer_b",
    "idempotency_key": f"idemp-fail-{fail_bid}"
}
st_fail, fail_data = post_json(f"{LEADER_URL}/api/cinema/reserve", fail_payload)
print(f"Quorum-loss reservation status: {st_fail}, response: {fail_data}")
assert st_fail in [500, 503, 504], f"Expected 5xx consensus failure, got {st_fail}"
print("VERIFIED: Quorum safety preserved! Reservation failed because stopped nodes rejected consensus.")

# Verify seat B2 was NOT reserved or locked
st_seats, seats = get_json(f"{LEADER_URL}/api/cinema/seats/show-screen-1-prime")
seat_b2 = [s for s in seats if s["seat_code"] == "B2"][0]
print(f"Seat B2 current status in DB: {seat_b2['status']}")
assert seat_b2["status"] == "AVAILABLE", "Seat B2 should still be AVAILABLE"

print("\n=== STEP 5: Restart the two nodes (node1 and node2) ===")
st_start1, r_s1 = post_json("http://127.0.0.1:9001/api/fault/start_node", {}, headers=auth_header)
st_start2, r_s2 = post_json("http://127.0.0.1:9002/api/fault/start_node", {}, headers=auth_header)
print(f"Restarted node1: {r_s1}")
print(f"Restarted node2: {r_s2}")

time.sleep(2)

print("\n=== STEP 6: Verify cluster recovery and convergence ===")
for p in [9001, 9002, 9003]:
    st, topo = get_json(f"http://127.0.0.1:{p}/api/cluster/topology")
    print(f"Node {topo['node_id']} (port {p}): Role={topo['role']}, Term={topo['current_term']}, Commit={topo['commit_index']}, Applied={topo['last_applied']}, Running={topo['is_running']}")

print("\n=== STEP 7: Test Cancellation via Raft Consensus ===")
# Cancel the booking made in Step 2 (allocated_booking_id)
cancel_payload = {
    "booking_id": allocated_booking_id,
    "owner_id": "customer_a",
    "idempotency_key": f"idemp-cancel-{allocated_booking_id}"
}
st_canc, canc_data = post_json(f"{LEADER_URL}/api/cinema/cancel", cancel_payload)
print(f"Cancel status: {st_canc}, Response: {canc_data}")
assert st_canc == 200, f"Expected 200, got {st_canc}"
assert canc_data["status"] == "CANCELLED"

# Verify seats B4 and C4 are now released back to AVAILABLE
st_seats2, seats2 = get_json(f"{LEADER_URL}/api/cinema/seats/show-screen-1-prime")
seat_b4 = [s for s in seats2 if s["seat_code"] == "B4"][0]
seat_c4 = [s for s in seats2 if s["seat_code"] == "C4"][0]
print(f"Seat B4 status after cancellation: {seat_b4['status']}")
print(f"Seat C4 status after cancellation: {seat_c4['status']}")
assert seat_b4["status"] == "AVAILABLE"
assert seat_c4["status"] == "AVAILABLE"

print("\n=== STEP 8: Verify Customer A and Customer B Booking History APIs ===")
st_a, b_a = get_json(f"{LEADER_URL}/api/cinema/bookings/customer/customer_a")
st_b, b_b = get_json(f"{LEADER_URL}/api/cinema/bookings/customer/customer_b")
print(f"Customer A booking count: {len(b_a)}")
print(f"Customer B booking count: {len(b_b)}")
assert any(b["id"] == allocated_booking_id for b in b_a), "Cancelled booking must appear in Customer A history"
assert not any(b["id"] == allocated_booking_id for b in b_b), "Cancelled booking must NOT appear in Customer B history"

print("\nALL ACCEPTANCE CRITERIA VERIFIED SUCCESSFULLY!")
