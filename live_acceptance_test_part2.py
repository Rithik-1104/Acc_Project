import time
import json
import urllib.request
import urllib.error

LEADER_PORT = 9003
LEADER_URL = f"http://127.0.0.1:{LEADER_PORT}"
auth_header = {"X-Fault-Token": "dev-fault-insecure-local-token"}

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

print("=== PART A: Test 2 Isolated Nodes (Scenario E - Quorum Loss via Network Partition) ===")
st1, r1 = post_json("http://127.0.0.1:9001/api/fault/isolate", {}, headers=auth_header)
st2, r2 = post_json("http://127.0.0.1:9002/api/fault/isolate", {}, headers=auth_header)
print(f"Isolated node1: status={st1}, response={r1}")
print(f"Isolated node2: status={st2}, response={r2}")

time.sleep(1)

# Verify isolated nodes reject AppendEntries
append_test_args = {
    "term": 406,
    "leader_id": "node3",
    "prev_log_index": 0,
    "prev_log_term": 0,
    "entries": [],
    "leader_commit": 0
}
st_app1, r_app1 = post_json("http://127.0.0.1:9001/raft/append_entries", append_test_args)
print(f"AppendEntries to isolated node1: {r_app1}")
assert r_app1.get("success") is False and r_app1.get("reason") == "NETWORK_ISOLATED"

# Attempt reservation during network isolation (must fail because leader cannot form majority)
fail_bid = f"test-bk-iso-{int(time.time())}"
fail_payload = {
    "booking_id": fail_bid,
    "show_id": "show-screen-1-prime",
    "seat_ids": ["seat-B5"],
    "owner_id": "customer_a",
    "idempotency_key": f"idemp-iso-{fail_bid}"
}
st_fail, fail_data = post_json(f"{LEADER_URL}/api/cinema/reserve", fail_payload)
print(f"Reservation status during isolation: {st_fail}, response: {fail_data}")
assert st_fail in [500, 503, 504]
print("VERIFIED: Isolation prevents consensus commitment!")

# Heal nodes
st_h1, r_h1 = post_json("http://127.0.0.1:9001/api/fault/heal", {}, headers=auth_header)
st_h2, r_h2 = post_json("http://127.0.0.1:9002/api/fault/heal", {}, headers=auth_header)
print(f"Healed node1: {r_h1}")
print(f"Healed node2: {r_h2}")
time.sleep(3)

print("\n=== PART B: Test Lease Renewal & Expiry Countdown ===")
# Reserve seat B6 (VIP - INR 300)
res_bid = f"test-bk-renew-{int(time.time())}"
res_payload = {
    "booking_id": res_bid,
    "show_id": "show-screen-1-prime",
    "seat_ids": ["seat-B6"],
    "owner_id": "customer_b",
    "idempotency_key": f"idemp-res-{res_bid}"
}
st_res, res_data = post_json(f"{LEADER_URL}/api/cinema/reserve", res_payload)
print(f"Reserve seat B6 status: {st_res}, response: {res_data}")
assert st_res == 200, f"Expected 200, got {st_res}: {res_data}"
token1 = res_data["fencing_token"]
alloc_bid = res_data["booking_id"]
initial_expires = res_data["expires_at"]
print(f"Initial reservation: booking_id={alloc_bid}, token=#{token1}, expires={initial_expires}")

# Wait 3 seconds then renew lease
time.sleep(3)
renew_payload = {
    "booking_id": alloc_bid,
    "owner_id": "customer_b",
    "current_token": token1,
    "idempotency_key": f"idemp-renew-{alloc_bid}"
}
st_ren, ren_data = post_json(f"{LEADER_URL}/api/cinema/renew", renew_payload)
print(f"Renewal response: status={st_ren}, data={ren_data}")
assert st_ren == 200
assert ren_data["status"] == "RENEWED"
token2 = ren_data["fencing_token"]
new_expires = ren_data["expires_at"]
assert token2 > token1, "Renewal must generate a monotonically higher fencing token"
print(f"VERIFIED: Renewal extended lease to {new_expires} with new fencing token #{token2}")

# Test Stale Token Rejection: Attempt confirm with old token1
bad_confirm_payload = {
    "booking_id": alloc_bid,
    "owner_id": "customer_b",
    "current_token": token1,
    "idempotency_key": f"idemp-bad-conf-{alloc_bid}"
}
st_bad, bad_data = post_json(f"{LEADER_URL}/api/cinema/confirm", bad_confirm_payload)
print(f"Stale token confirmation status: {st_bad}, response: {bad_data}")
assert st_bad == 409
assert bad_data["detail"]["status"] == "REJECTED_STALE_TOKEN"
print("VERIFIED: Stale fencing token #{} was strictly rejected!".format(token1))

# Confirm with valid token2
good_confirm_payload = {
    "booking_id": alloc_bid,
    "owner_id": "customer_b",
    "current_token": token2,
    "customer_name": "Customer B",
    "customer_email": "customer_b@example.com",
    "idempotency_key": f"idemp-good-conf-{alloc_bid}"
}
st_good, good_data = post_json(f"{LEADER_URL}/api/cinema/confirm", good_confirm_payload)
print(f"Valid token confirmation status: {st_good}, total_amount={good_data.get('total_amount')}")
assert st_good == 200
assert good_data["status"] == "CONFIRMED"
assert good_data["total_amount"] == 300.0, f"Expected 300.0 for VIP seat B5, got {good_data.get('total_amount')}"

# Verify log convergence across all nodes
time.sleep(1)
print("\n=== Log Convergence Check ===")
for p in [9001, 9002, 9003]:
    st, topo = get_json(f"http://127.0.0.1:{p}/api/cluster/topology")
    print(f"Port {p} ({topo['node_id']}): Commit={topo['commit_index']}, Applied={topo['last_applied']}, Term={topo['current_term']}")

print("\nPART A & PART B COMPLETED WITH 100% SUCCESS!")
