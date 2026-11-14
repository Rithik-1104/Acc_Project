import asyncio
import sys
import httpx

NODES = {
    "node1": "http://127.0.0.1:9001",
    "node2": "http://127.0.0.1:9002",
    "node3": "http://127.0.0.1:9003",
}

async def inspect_cluster():
    print("=" * 60)
    print("RAFT 3-NODE CLUSTER INSPECTION")
    print("=" * 60)
    
    leader_found = None
    async with httpx.AsyncClient(timeout=2.0) as client:
        for nid, base_url in NODES.items():
            try:
                resp = await client.get(f"{base_url}/api/cluster/topology")
                if resp.status_code == 200:
                    data = resp.json()
                    role = data["role"]
                    term = data["current_term"]
                    leader = data["current_leader"]
                    commit = data["commit_index"]
                    last_idx = data["last_log_index"]
                    print(f"[{nid.upper()}] Role: {role:9s} | Term: {term} | Leader: {leader} | CommitIndex: {commit} | LastLogIndex: {last_idx}")
                    if role == "LEADER":
                        leader_found = (nid, base_url)
                else:
                    print(f"[{nid.upper()}] HTTP {resp.status_code}")
            except Exception as e:
                print(f"[{nid.upper()}] Offline / Unreachable ({e})")

    print("-" * 60)
    if leader_found:
        print(f"Active Quorum Leader: {leader_found[0]} ({leader_found[1]})")
    else:
        print("No active leader detected yet. Election may be in progress.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(inspect_cluster())
