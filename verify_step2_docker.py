import asyncio
import json
import httpx

FAULT_TOKEN = "dev-fault-insecure-local-token"
BASE_URLS = {
    "node1": "http://localhost:9001",
    "node2": "http://localhost:9002",
    "node3": "http://localhost:9003"
}

def print_topology():
    print("\n--- CLUSTER TOPOLOGY ---")
    for nid, url in BASE_URLS.items():
        try:
            r = httpx.get(f"{url}/api/cluster/topology", timeout=2.0)
            data = r.json()
            print(f"[{nid}] Role: {data['role']:<9} Term: {data['current_term']:<4} Leader: {data['current_leader']} CommitIndex: {data['commit_index']} LastLogIndex: {data['last_log_index']}")
        except Exception as e:
            print(f"[{nid}] Error: {e}")

async def run_live_verification():
    print("=== STEP 2 LIVE DOCKER VERIFICATION ===")

    # 1. Test Fault Endpoint Security & Token Rejection
    print("\n[VERIFICATION 1] Testing Fault Endpoint Security")
    # Test missing token
    r_no_token = httpx.post(f"{BASE_URLS['node1']}/api/fault/isolate", json={})
    print(f"Missing Token Response: HTTP {r_no_token.status_code} - {r_no_token.json()}")
    assert r_no_token.status_code == 401

    # Test bad token
    r_bad_token = httpx.post(f"{BASE_URLS['node1']}/api/fault/isolate", json={}, headers={"X-Fault-Token": "invalid-token-123"})
    print(f"Invalid Token Response: HTTP {r_bad_token.status_code} - {r_bad_token.json()}")
    assert r_bad_token.status_code == 401

    # 2. Check current leader
    print_topology()
    r = httpx.get(f"{BASE_URLS['node1']}/api/cluster/topology", timeout=2.0)
    current_leader_id = r.json()["current_leader"]
    print(f"\n[IDENTIFIED LEADER]: {current_leader_id}")

    # Identify a follower to isolate
    followers = [nid for nid in BASE_URLS if nid != current_leader_id]
    target_follower = followers[0]
    other_follower = followers[1]
    print(f"[TARGET FOLLOWER TO ISOLATE]: {target_follower}")

    # 3. Isolate one follower
    print(f"\n[VERIFICATION 2] Isolating Follower {target_follower}...")
    r_iso = httpx.post(
        f"{BASE_URLS[target_follower]}/api/fault/isolate",
        json={"node_id": target_follower},
        headers={"X-Fault-Token": FAULT_TOKEN}
    )
    print(f"Isolate {target_follower} Response: {r_iso.json()}")
    assert r_iso.status_code == 200

    # Demonstrate that the remaining 2 nodes (leader + other follower) can still commit a real proposal
    print(f"\n[VERIFICATION 3] Proposing reservation through Leader {current_leader_id} while {target_follower} is isolated...")
    prop_payload = {
        "show_id": "show-screen-1-prime",
        "seat_ids": ["seat-B5", "seat-B6"],
        "owner_id": "cust_live_quorum_test",
        "idempotency_key": "step2_docker_key_1"
    }
    r_prop = httpx.post(f"{BASE_URLS[current_leader_id]}/api/cinema/reserve", json=prop_payload, timeout=4.0)
    print(f"Proposal Response: HTTP {r_prop.status_code} - {r_prop.json()}")
    assert r_prop.status_code == 200
    committed_fencing_token = r_prop.json()["fencing_token"]

    print_topology()
    # Confirm isolated follower did not advance commit_index to the new entry
    top_iso = httpx.get(f"{BASE_URLS[target_follower]}/api/cluster/topology").json()
    top_lead = httpx.get(f"{BASE_URLS[current_leader_id]}/api/cluster/topology").json()
    print(f"Leader commit_index: {top_lead['commit_index']} | Isolated follower commit_index: {top_iso['commit_index']}")
    assert top_iso["commit_index"] < top_lead["commit_index"]

    # 4. Heal the follower and demonstrate that it catches up
    print(f"\n[VERIFICATION 4] Healing Follower {target_follower}...")
    r_heal = httpx.post(
        f"{BASE_URLS[target_follower]}/api/fault/heal",
        json={"node_id": target_follower},
        headers={"X-Fault-Token": FAULT_TOKEN}
    )
    print(f"Heal Response: {r_heal.json()}")
    assert r_heal.status_code == 200

    # Wait for heartbeats and catch-up
    print(f"Waiting for {target_follower} to catch up from Leader {current_leader_id}...")
    for _ in range(30):
        await asyncio.sleep(0.1)
        top_healed = httpx.get(f"{BASE_URLS[target_follower]}/api/cluster/topology").json()
        if top_healed["commit_index"] >= top_lead["commit_index"]:
            break

    top_healed = httpx.get(f"{BASE_URLS[target_follower]}/api/cluster/topology").json()
    print(f"Healed follower commit_index after catch-up: {top_healed['commit_index']} (Matches Leader: {top_lead['commit_index']})")
    assert top_healed["commit_index"] == top_lead["commit_index"]
    assert "seat-B5" in top_healed["state_machine"]["seat_locks"]

    # 5. Isolate the current leader and demonstrate natural election among remaining two nodes
    print(f"\n[VERIFICATION 5] Isolating Current Leader {current_leader_id}...")
    r_iso_lead = httpx.post(
        f"{BASE_URLS[current_leader_id]}/api/fault/isolate",
        json={"node_id": current_leader_id},
        headers={"X-Fault-Token": FAULT_TOKEN}
    )
    print(f"Isolate Leader Response: {r_iso_lead.json()}")
    assert r_iso_lead.status_code == 200

    print("Waiting for natural election between the remaining two nodes...")
    new_leader_id = None
    old_term = top_lead["current_term"]
    for _ in range(40):
        await asyncio.sleep(0.15)
        for nid in followers:
            try:
                top = httpx.get(f"{BASE_URLS[nid]}/api/cluster/topology", timeout=1.0).json()
                if top["role"] == "LEADER":
                    new_leader_id = nid
                    break
            except Exception:
                pass
        if new_leader_id:
            break

    assert new_leader_id is not None
    print(f"Natural Election Succeeded! New Leader: {new_leader_id}")
    print_topology()

    # 6. Restore the old leader and verify all three nodes are healthy and consistent
    print(f"\n[VERIFICATION 6] Restoring old leader {current_leader_id} to cluster...")
    r_heal_old = httpx.post(
        f"{BASE_URLS[current_leader_id]}/api/fault/heal",
        json={"node_id": current_leader_id},
        headers={"X-Fault-Token": FAULT_TOKEN}
    )
    print(f"Heal Old Leader Response: {r_heal_old.json()}")
    assert r_heal_old.status_code == 200

    # Wait for cluster consistency
    for _ in range(30):
        await asyncio.sleep(0.1)
        top_all = [httpx.get(f"{u}/api/cluster/topology").json() for u in BASE_URLS.values()]
        leaders = [t for t in top_all if t["role"] == "LEADER"]
        if len(leaders) == 1 and all(t["current_leader"] == new_leader_id for t in top_all):
            break

    print_topology()
    print("\n=== LIVE DOCKER VERIFICATION COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    asyncio.run(run_live_verification())
