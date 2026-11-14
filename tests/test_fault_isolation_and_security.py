import asyncio
import os
import shutil
import pytest
from httpx import AsyncClient, ASGITransport

from backend.consensus.config import RaftConfig
from backend.consensus.node import RaftNode
from backend.consensus.models import NodeRole, RequestVoteArgs, AppendEntriesArgs
from backend.consensus.lock_state_machine import DistributedLockStateMachine
from tests.test_consensus_cluster import MemoryNetworkRouter, MemoryRPCClient
from backend.api.fault_routes import FAULT_AUTH_TOKEN
import backend.main as main_mod

@pytest.fixture
def fault_cluster_dir():
    d = "./tmp_fault_cluster"
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    yield d
    if os.path.exists(d):
        shutil.rmtree(d)

@pytest.mark.asyncio
async def test_isolated_follower_quorum_maintained_and_commits(fault_cluster_dir):
    """
    Test 1: Isolated Follower
    - 3-node cluster starts and elects a leader.
    - Follower is isolated via node.isolate().
    - Remaining 2 nodes (majority 2/3) maintain quorum and continue committing proposals.
    """
    router = MemoryNetworkRouter()
    nodes: dict[str, RaftNode] = {}
    for i in range(1, 4):
        nid = f"node{i}"
        peers = {f"node{j}": f"mem://node{j}" for j in range(1, 4) if j != i}
        cfg = RaftConfig(
            node_id=nid,
            port=8000 + i,
            peers=peers,
            data_dir=os.path.join(fault_cluster_dir, nid),
            heartbeat_interval_ms=50,
            election_timeout_min_ms=150,
            election_timeout_max_ms=300
        )
        sm = DistributedLockStateMachine()
        node = RaftNode(config=cfg, state_machine=sm, rpc_client=MemoryRPCClient(nid, router))
        router.register(node)
        nodes[nid] = node
        await node.start()

    # Find leader and followers
    leader = None
    for _ in range(40):
        await asyncio.sleep(0.05)
        leaders = [n for n in nodes.values() if n.role == NodeRole.LEADER and n.leader_ready]
        if len(leaders) == 1:
            leader = leaders[0]
            break

    assert leader is not None
    followers = [n for n in nodes.values() if n.role == NodeRole.FOLLOWER]
    assert len(followers) == 2

    # Isolate follower 1
    isolated_follower = followers[0]
    isolated_follower.isolate()
    assert isolated_follower.is_network_isolated is True

    # Propose command through leader
    success, res, err = await leader.propose(
        command="RESERVE_SEATS",
        payload={"booking_id": "b_iso_f", "show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "u1"},
        timeout_sec=2.0
    )
    # Must succeed because leader + remaining follower = 2/3 quorum
    assert success is True
    assert res["status"] == "RESERVED"

    # Confirm isolated follower did NOT receive the commit
    assert isolated_follower.commit_index < leader.commit_index

    for n in nodes.values():
        await n.stop()

@pytest.mark.asyncio
async def test_isolated_leader_triggers_re_election(fault_cluster_dir):
    """
    Test 2: Isolated Leader
    - 3-node cluster starts and elects leader1.
    - leader1 is isolated via node.isolate().
    - Remaining 2 followers miss heartbeats and elect a new leader (leader2) in a higher term.
    """
    router = MemoryNetworkRouter()
    nodes: dict[str, RaftNode] = {}
    for i in range(1, 4):
        nid = f"node{i}"
        peers = {f"node{j}": f"mem://node{j}" for j in range(1, 4) if j != i}
        cfg = RaftConfig(
            node_id=nid,
            port=8000 + i,
            peers=peers,
            data_dir=os.path.join(fault_cluster_dir, nid),
            heartbeat_interval_ms=50,
            election_timeout_min_ms=120,
            election_timeout_max_ms=250
        )
        sm = DistributedLockStateMachine()
        node = RaftNode(config=cfg, state_machine=sm, rpc_client=MemoryRPCClient(nid, router))
        router.register(node)
        nodes[nid] = node
        await node.start()

    # Find initial leader
    old_leader = None
    for _ in range(40):
        await asyncio.sleep(0.05)
        leaders = [n for n in nodes.values() if n.role == NodeRole.LEADER and n.leader_ready]
        if len(leaders) == 1:
            old_leader = leaders[0]
            break

    assert old_leader is not None
    old_term = old_leader.current_term
    old_leader_id = old_leader.node_id

    # Isolate leader
    old_leader.isolate()
    assert old_leader.is_network_isolated is True

    # Remaining 2 nodes must elect a new leader in higher term
    new_leader = None
    for _ in range(50):
        await asyncio.sleep(0.05)
        leaders = [n for n in nodes.values() if n.node_id != old_leader_id and n.role == NodeRole.LEADER and n.leader_ready]
        if len(leaders) == 1:
            new_leader = leaders[0]
            break

    assert new_leader is not None
    assert new_leader.node_id != old_leader_id
    assert new_leader.current_term > old_term

    # Proposals to new leader succeed (quorum 2/3 between new leader and 1 follower)
    success, res, err = await new_leader.propose(
        command="RESERVE_SEATS",
        payload={"booking_id": "b_new_lead", "show_id": "s1", "seat_ids": ["seat-B1"], "owner_id": "u2"},
        timeout_sec=2.0
    )
    assert success is True
    assert res["status"] == "RESERVED"

    for n in nodes.values():
        await n.stop()

@pytest.mark.asyncio
async def test_isolated_node_blocks_inbound_and_outbound_rpc(fault_cluster_dir):
    """
    Test 3: Isolated Node RPC Blocking
    - An isolated node rejects inbound RequestVote and AppendEntries RPCs.
    - Outbound RPC attempts by an isolated node return None.
    """
    router = MemoryNetworkRouter()
    cfg = RaftConfig(node_id="node1", port=8001, data_dir=os.path.join(fault_cluster_dir, "node1"))
    rpc = MemoryRPCClient("node1", router)
    node = RaftNode(config=cfg, rpc_client=rpc)

    # Isolate node
    node.isolate()
    assert node.is_network_isolated is True

    # 1. Inbound RequestVote must be denied with NETWORK_ISOLATED
    v_reply = await node.handle_request_vote(RequestVoteArgs(
        term=5, candidate_id="node2", last_log_index=1, last_log_term=1
    ))
    assert v_reply.vote_granted is False
    assert v_reply.reason == "NETWORK_ISOLATED"

    # 2. Inbound AppendEntries must fail with NETWORK_ISOLATED
    a_reply = await node.handle_append_entries(AppendEntriesArgs(
        term=5, leader_id="node2", prev_log_index=0, prev_log_term=0, entries=[], leader_commit=0
    ))
    assert a_reply.success is False
    assert a_reply.reason == "NETWORK_ISOLATED"

    # 3. Outbound RPC must be dropped (returns None)
    outbound_res = await rpc.send_request_vote("mem://node2", RequestVoteArgs(
        term=1, candidate_id="node1", last_log_index=0, last_log_term=0
    ))
    assert outbound_res is None

@pytest.mark.asyncio
async def test_healing_restores_communication_and_log_catchup(fault_cluster_dir):
    """
    Test 4: Healing and Catch-up
    - Isolate follower, commit entries on remaining 2 nodes.
    - Heal follower via node.heal().
    - Verify leader replicates missing entries and follower catches up commit_index.
    """
    router = MemoryNetworkRouter()
    nodes: dict[str, RaftNode] = {}
    for i in range(1, 4):
        nid = f"node{i}"
        peers = {f"node{j}": f"mem://node{j}" for j in range(1, 4) if j != i}
        cfg = RaftConfig(
            node_id=nid,
            port=8000 + i,
            peers=peers,
            data_dir=os.path.join(fault_cluster_dir, nid),
            heartbeat_interval_ms=50,
            election_timeout_min_ms=150,
            election_timeout_max_ms=300
        )
        sm = DistributedLockStateMachine()
        node = RaftNode(config=cfg, state_machine=sm, rpc_client=MemoryRPCClient(nid, router))
        router.register(node)
        nodes[nid] = node
        await node.start()

    # Wait for leader
    leader = None
    for _ in range(40):
        await asyncio.sleep(0.05)
        leaders = [n for n in nodes.values() if n.role == NodeRole.LEADER and n.leader_ready]
        if len(leaders) == 1:
            leader = leaders[0]
            break

    assert leader is not None
    followers = [n for n in nodes.values() if n.role == NodeRole.FOLLOWER]
    lagging_follower = followers[0]

    # Isolate follower and commit entries on leader
    lagging_follower.isolate()
    success, res, err = await leader.propose(
        command="RESERVE_SEATS",
        payload={"booking_id": "b_heal_1", "show_id": "s1", "seat_ids": ["seat-C1"], "owner_id": "u1"},
        timeout_sec=2.0
    )
    assert success is True
    target_commit = leader.commit_index
    assert lagging_follower.commit_index < target_commit

    # Heal the follower
    lagging_follower.heal()
    assert lagging_follower.is_network_isolated is False

    # Wait for leader heartbeats to replicate entries to healed follower
    for _ in range(40):
        await asyncio.sleep(0.05)
        if lagging_follower.commit_index >= target_commit:
            break

    assert lagging_follower.commit_index >= target_commit
    # State machine on healed follower must also have applied the reservation
    assert "seat-C1" in lagging_follower.state_machine.seat_locks

    for n in nodes.values():
        await n.stop()

@pytest.mark.asyncio
async def test_stopped_node_restarts_from_existing_wal(fault_cluster_dir):
    """
    Test 5: Node Lifecycle Stop and Restart from WAL
    - Node receives entries and commits.
    - Node is stopped via node.stop().
    - Node is restarted via node.start() using its existing WAL without data loss.
    """
    router = MemoryNetworkRouter()
    cfg = RaftConfig(
        node_id="node1",
        port=8001,
        data_dir=os.path.join(fault_cluster_dir, "node1"),
        heartbeat_interval_ms=50,
        election_timeout_min_ms=150,
        election_timeout_max_ms=300
    )
    sm = DistributedLockStateMachine()
    node = RaftNode(config=cfg, state_machine=sm, rpc_client=MemoryRPCClient("node1", router))
    await node.start()

    # Single-node cluster becomes leader
    for _ in range(30):
        await asyncio.sleep(0.05)
        if node.role == NodeRole.LEADER and node.leader_ready:
            break

    # Propose command
    success, res, err = await node.propose(
        command="RESERVE_SEATS",
        payload={"booking_id": "b_wal_restart", "show_id": "s1", "seat_ids": ["seat-D1"], "owner_id": "u1"},
        timeout_sec=2.0
    )
    assert success is True
    saved_term = node.current_term
    saved_log_count = len(node.log)

    # Stop node
    await node.stop()
    assert node._running is False

    # Restart same node instance (or new instance with same data_dir)
    await node.start()
    assert node._running is True
    assert node.current_term == saved_term
    assert len(node.log) == saved_log_count

    await node.stop()

@pytest.mark.asyncio
async def test_fault_api_security_and_authorization():
    """
    Test 6: Fault API Security and Endpoint Validation
    - Unauthenticated requests (missing/invalid token) must be rejected with 401.
    - Requests with valid token from local test client succeed.
    - Node ID mismatch returns 400.
    """
    cfg = RaftConfig(node_id="test_node", port=8001, data_dir="./tmp_test_api_fault")
    test_node = RaftNode(config=cfg)
    old_node = main_mod.raft_node
    main_mod.raft_node = test_node

    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Missing token -> 401
        resp = await client.post("/api/fault/isolate", json={})
        assert resp.status_code == 401

        # 2. Invalid token -> 401
        resp = await client.post("/api/fault/isolate", json={}, headers={"X-Fault-Token": "bad-token"})
        assert resp.status_code == 401

        # 3. Node ID mismatch -> 400
        resp = await client.post(
            "/api/fault/isolate",
            json={"node_id": "wrong_node"},
            headers={"X-Fault-Token": FAULT_AUTH_TOKEN}
        )
        assert resp.status_code == 400

        # 4. Valid token and matching node_id -> 200
        resp = await client.post(
            "/api/fault/isolate",
            json={"node_id": "test_node"},
            headers={"X-Fault-Token": FAULT_AUTH_TOKEN}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ISOLATED"
        assert test_node.is_network_isolated is True

        # 5. Heal node -> 200
        resp = await client.post(
            "/api/fault/heal",
            json={"node_id": "test_node"},
            headers={"X-Fault-Token": FAULT_AUTH_TOKEN}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "HEALED"
        assert test_node.is_network_isolated is False

    main_mod.raft_node = old_node
    if os.path.exists("./tmp_test_api_fault"):
        shutil.rmtree("./tmp_test_api_fault")
