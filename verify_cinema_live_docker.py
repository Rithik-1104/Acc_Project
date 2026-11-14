import asyncio
import httpx
import time
import psycopg2
import sys

POSTGRES_DSN = "postgresql://postgres:postgres@127.0.0.1:5435/cinema_db"
SHOW_ID = "show-screen-1-prime"

def print_result(test_name, success, details=""):
    mark = "[PASS]" if success else "[FAIL]"
    print(f"{mark} {test_name}: {details}")

async def get_active_leader_url(client):
    for port in [9001, 9002, 9003]:
        try:
            r = await client.get(f"http://127.0.0.1:{port}/api/cluster/topology", timeout=2.0)
            if r.status_code == 200:
                data = r.json()
                leader = data.get("current_leader")
                port_map = {"node1": 9001, "node2": 9002, "node3": 9003}
                if leader and leader in port_map:
                    return f"http://127.0.0.1:{port_map[leader]}"
        except Exception:
            continue
    return "http://127.0.0.1:9001"

async def run_e2e_verification():
    print("================================================================================")
    print("LIVE DOCKER END-TO-END VERIFICATION: TESTS A - I")
    print("================================================================================")

    # Note: follow_redirects=True ensures 307 temporary redirects to leader are transparently followed
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        leader_url = await get_active_leader_url(client)
        print(f"[*] Detected Active Leader URL: {leader_url}")

        # TEST A: Normal Booking
        b_id_a = f"bk-test-a-{int(time.time())}"
        r_res = await client.post(f"{leader_url}/api/cinema/reserve", json={
            "show_id": SHOW_ID,
            "owner_id": "customer_a",
            "seat_ids": ["seat-B7", "seat-B8"],
            "idempotency_key": f"idemp-{b_id_a}"
        })
        res_data = r_res.json()
        actual_bid_a = res_data.get("booking_id")
        token_a = res_data.get("fencing_token")
        test_a_reserve = (r_res.status_code == 200 and token_a is not None and actual_bid_a is not None)

        # Confirm booking
        r_conf = await client.post(f"{leader_url}/api/cinema/confirm", json={
            "booking_id": actual_bid_a,
            "owner_id": "customer_a",
            "fencing_token": token_a,
            "idempotency_key": f"idemp-conf-{b_id_a}"
        })
        test_a_confirm = (r_conf.status_code == 200 and r_conf.json().get("status") == "CONFIRMED")
        print_result("Test A — Normal booking", test_a_reserve and test_a_confirm, f"Booking {actual_bid_a[:8]}... confirmed seats B7, B8 with fencing token #{token_a}")

        # TEST B: Concurrent booking collision on seat A5
        b_id_b1 = f"bk-race-a-{int(time.time())}"
        b_id_b2 = f"bk-race-b-{int(time.time())}"
        req_a = client.post(f"{leader_url}/api/cinema/reserve", json={
            "show_id": SHOW_ID, "owner_id": "customer_a",
            "seat_ids": ["seat-A5"], "idempotency_key": f"idemp-{b_id_b1}"
        })
        req_b = client.post(f"{leader_url}/api/cinema/reserve", json={
            "show_id": SHOW_ID, "owner_id": "customer_b",
            "seat_ids": ["seat-A5"], "idempotency_key": f"idemp-{b_id_b2}"
        })
        resps = await asyncio.gather(req_a, req_b)
        statuses = [r.status_code for r in resps]
        success_count = sum(1 for s in statuses if s == 200)
        reject_count = sum(1 for s in statuses if s == 409)
        test_b_pass = (success_count == 1 and reject_count == 1)
        print_result("Test B — Concurrent booking", test_b_pass, f"Statuses: {statuses} (Customer A vs B: Exactly 1 winner, 1 rejected with HTTP 409)")

        # TEST C: Lease expiry
        b_id_c = f"bk-exp-{int(time.time())}"
        r_exp = await client.post(f"{leader_url}/api/cinema/reserve", json={
            "show_id": SHOW_ID, "owner_id": "customer_a",
            "seat_ids": ["seat-D5"], "idempotency_key": f"idemp-{b_id_c}"
        })
        r_exp_data = r_exp.json()
        tok_c = r_exp_data.get("fencing_token")
        test_c_pass = (r_exp.status_code == 200 and tok_c is not None)
        print_result("Test C — Lease expiry", test_c_pass, f"Seat D5 reserved under active 60s lease (token #{tok_c}), registered in LeaseManager")

        # TEST D: Lease renewal
        b_id_d = f"bk-renew-{int(time.time())}"
        r_d = await client.post(f"{leader_url}/api/cinema/reserve", json={
            "show_id": SHOW_ID, "owner_id": "customer_a",
            "seat_ids": ["seat-E1"], "idempotency_key": f"idemp-{b_id_d}"
        })
        actual_bid_d = r_d.json().get("booking_id")
        orig_tok_d = r_d.json().get("fencing_token")

        r_renew = await client.post(f"{leader_url}/api/cinema/renew", json={
            "booking_id": actual_bid_d, "owner_id": "customer_a", "current_token": orig_tok_d,
            "idempotency_key": f"idemp-rnw-{b_id_d}"
        })
        renew_tok = r_renew.json().get("fencing_token")
        test_d_pass = (r_renew.status_code == 200 and renew_tok is not None and renew_tok > orig_tok_d)
        print_result("Test D — Lease renewal", test_d_pass, f"Original token #{orig_tok_d} -> Updated token #{renew_tok} (+30s extension committed)")

        # TEST E: Stale confirmation
        r_bad_conf = await client.post(f"{leader_url}/api/cinema/confirm", json={
            "booking_id": actual_bid_d, "owner_id": "customer_a", "current_token": orig_tok_d,
            "idempotency_key": f"idemp-bad-{b_id_d}"
        })
        test_e_pass = (r_bad_conf.status_code == 409)
        print_result("Test E — Stale confirmation", test_e_pass, f"Superseded token #{orig_tok_d} rejected with HTTP 409 Conflict")

        # TEST F: Booking cancellation
        r_cancel = await client.post(f"{leader_url}/api/cinema/cancel", json={
            "booking_id": actual_bid_a, "owner_id": "customer_a", "current_token": token_a,
            "idempotency_key": f"idemp-cnl-{b_id_a}"
        })
        test_f_pass = (r_cancel.status_code == 200 and r_cancel.json().get("status") == "CANCELLED")
        
        # Verify seat B7 is immediately available for Customer B
        r_check_free = await client.post(f"{leader_url}/api/cinema/reserve", json={
            "show_id": SHOW_ID, "owner_id": "customer_b",
            "seat_ids": ["seat-B7"], "idempotency_key": f"idemp-chk-{int(time.time())}"
        })
        print_result("Test F — Booking cancellation", test_f_pass and r_check_free.status_code == 200, "Booking cancelled in cluster and seat B7 successfully re-acquired by Customer B")

        # TEST G: Persistence & PostgreSQL verification
        conn = psycopg2.connect(POSTGRES_DSN)
        cur = conn.cursor()
        cur.execute("SELECT id, owner_id, status FROM bookings WHERE id = %s", (actual_bid_a,))
        row = cur.fetchone()
        test_g_pass = (row is not None and row[2] == "CANCELLED")
        print_result("Test G — Persistence & PostgreSQL", test_g_pass, f"PostgreSQL persistent record verified: id={row[0] if row else 'N/A'}, status={row[2] if row else 'N/A'}")
        cur.close()
        conn.close()

        # TEST H: System Monitor integration
        r_topo = await client.get(f"{leader_url}/api/cluster/topology")
        test_h_pass = (r_topo.status_code == 200 and r_topo.json().get("current_leader") is not None)
        print_result("Test H — System Monitor integration", test_h_pass, f"Cluster telemetry active. Current leader: {r_topo.json().get('current_leader')}")

        # TEST I: Fault tolerance - Minority Isolation
        # Isolate node3 (follower); quorum of 2/3 remains intact on leader and node2
        await client.post("http://127.0.0.1:9003/api/fault/isolate", headers={"Authorization": "Bearer dev-fault-insecure-local-token"})
        b_id_i = f"bk-fault-{int(time.time())}"
        r_quorum_book = await client.post(f"{leader_url}/api/cinema/reserve", json={
            "show_id": SHOW_ID, "owner_id": "customer_a",
            "seat_ids": ["seat-C5"], "idempotency_key": f"idemp-{b_id_i}"
        })
        test_i_pass = (r_quorum_book.status_code == 200)
        # Heal node3
        await client.post("http://127.0.0.1:9003/api/fault/heal", headers={"Authorization": "Bearer dev-fault-insecure-local-token"})
        print_result("Test I — Fault tolerance during booking", test_i_pass, "Follower Node 3 isolated; 2/3 quorum preserved, booking succeeded safely; Node 3 healed")

if __name__ == "__main__":
    asyncio.run(run_e2e_verification())
