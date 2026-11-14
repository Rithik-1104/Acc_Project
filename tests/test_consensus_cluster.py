import asyncio
import os
import shutil
from typing import Optional
import pytest

from backend.consensus.config import RaftConfig
from backend.consensus.models import (
    NodeRole, RequestVoteArgs, RequestVoteReply,
    AppendEntriesArgs, AppendEntriesReply
)
from backend.consensus.node import RaftNode

class MemoryNetworkRouter:
    """
    Direct in-memory router connecting Raft nodes without external HTTP ports.
    Allows exact verification of leader election, majority quorum, log replication,
    and network partition behavior.
    """
    def __init__(self):
        self.nodes: dict[str, RaftNode] = {}
        self.disabled_links: set[tuple[str, str]] = set()

    def register(self, node: RaftNode):
        self.nodes[node.node_id] = node

    def isolate(self, node_id: str):
        for other in self.nodes:
            if other != node_id:
                self.disabled_links.add((node_id, other))
                self.disabled_links.add((other, node_id))

    def reconnect_all(self):
        self.disabled_links.clear()

    async def send_request_vote(self, sender: str, peer_id: str, args: RequestVoteArgs) -> Optional[RequestVoteReply]:
        if (sender, peer_id) in self.disabled_links:
            return None
        target = self.nodes.get(peer_id)
        if not target:
            return None
        return await target.handle_request_vote(args)

    async def send_append_entries(self, sender: str, peer_id: str, args: AppendEntriesArgs) -> Optional[AppendEntriesReply]:
        if (sender, peer_id) in self.disabled_links:
            return None
        target = self.nodes.get(peer_id)
        if not target:
            return None
        return await target.handle_append_entries(args)

class MemoryRPCClient:
    def __init__(self, node_id: str, router: MemoryNetworkRouter):
        self.node_id = node_id
        self.router = router
        self.is_isolated = False

    def isolate(self):
        self.is_isolated = True

    def heal(self):
        self.is_isolated = False

    async def close(self):
        pass

    async def send_request_vote(self, peer_url: str, args: RequestVoteArgs) -> Optional[RequestVoteReply]:
        if self.is_isolated:
            return None
        peer_id = peer_url.replace("mem://", "")
        return await self.router.send_request_vote(self.node_id, peer_id, args)

    async def send_append_entries(self, peer_url: str, args: AppendEntriesArgs) -> Optional[AppendEntriesReply]:
        if self.is_isolated:
            return None
        peer_id = peer_url.replace("mem://", "")
        return await self.router.send_append_entries(self.node_id, peer_id, args)

@pytest.fixture
def cluster_dir():
    d = "./tmp_cluster_data"
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    yield d
    if os.path.exists(d):
        shutil.rmtree(d)

@pytest.mark.asyncio
async def test_three_node_leader_election(cluster_dir):
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
        rpc = MemoryRPCClient(nid, router)
        node = RaftNode(config=cfg, rpc_client=rpc)
        router.register(node)
        nodes[nid] = node

    # Start all 3 nodes
    for node in nodes.values():
        await node.start()

    # Wait for leader election and stabilization
    leader: Optional[RaftNode] = None
    for _ in range(40):
        await asyncio.sleep(0.1)
        leaders = [n for n in nodes.values() if n.role == NodeRole.LEADER]
        if len(leaders) == 1 and leaders[0].leader_ready:
            leader = leaders[0]
            # Ensure followers have received initial heartbeat
            followers = [n for n in nodes.values() if n.role == NodeRole.FOLLOWER]
            if len(followers) == 2:
                break

    assert leader is not None, "Failed to elect a single stable leader among 3 nodes"
    followers = [n for n in nodes.values() if n.role == NodeRole.FOLLOWER]
    assert len(followers) == 2, "Remaining nodes must be followers"

    # Clean up
    for node in nodes.values():
        await node.stop()

@pytest.mark.asyncio
async def test_three_node_log_replication_and_quorum_commit(cluster_dir):
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
        rpc = MemoryRPCClient(nid, router)
        node = RaftNode(config=cfg, rpc_client=rpc)
        router.register(node)
        nodes[nid] = node

    for node in nodes.values():
        await node.start()

    # Wait for leader
    leader: Optional[RaftNode] = None
    for _ in range(40):
        await asyncio.sleep(0.1)
        leaders = [n for n in nodes.values() if n.role == NodeRole.LEADER]
        if len(leaders) == 1 and leaders[0].leader_ready:
            leader = leaders[0]
            break

    assert leader is not None

    # Propose command to leader
    success, result, err = await leader.propose(
        command="SET",
        payload={"key": "seat_B1", "value": "RESERVED"},
        fencing_token=101,
        idempotency_key="idemp_101"
    )
    assert success is True, f"Proposal failed: {err}"
    # Index 1 was the election NOOP; Index 2 is the client proposal
    assert leader.commit_index == 2

    # Verify replication across followers
    await asyncio.sleep(0.2)
    for n in nodes.values():
        assert n.commit_index == 2
        assert n.last_applied == 2
        state = n.state_machine.get_state()
        assert state["store"] == {"seat_B1": "RESERVED"}

    for node in nodes.values():
        await node.stop()

@pytest.mark.asyncio
async def test_minority_isolation_prevents_uncommitted_writes(cluster_dir):
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
        rpc = MemoryRPCClient(nid, router)
        node = RaftNode(config=cfg, rpc_client=rpc)
        router.register(node)
        nodes[nid] = node

    for node in nodes.values():
        await node.start()

    # Find leader
    leader: Optional[RaftNode] = None
    for _ in range(30):
        await asyncio.sleep(0.1)
        leaders = [n for n in nodes.values() if n.role == NodeRole.LEADER]
        if len(leaders) == 1:
            leader = leaders[0]
            break

    assert leader is not None
    isolated_leader_id = leader.node_id

    # Isolate leader (cutting communication with both followers)
    router.isolate(isolated_leader_id)

    # Propose command to the isolated leader (should fail due to inability to achieve 2/3 quorum)
    success, result, err = await leader.propose(
        command="SET",
        payload={"key": "seat_B2", "value": "RESERVED"},
        timeout_sec=0.8
    )
    assert success is False
    assert err in ["PROPOSAL_TIMEOUT_NO_QUORUM", "LOST_LEADERSHIP"]

    # Meanwhile, the 2 connected followers form a majority and elect a new leader
    new_leader: Optional[RaftNode] = None
    for _ in range(30):
        await asyncio.sleep(0.1)
        active_leaders = [
            n for nid, n in nodes.items()
            if nid != isolated_leader_id and n.role == NodeRole.LEADER
        ]
        if active_leaders:
            new_leader = active_leaders[0]
            break

    assert new_leader is not None
    assert new_leader.node_id != isolated_leader_id

    # The majority partition can commit safely
    success2, result2, err2 = await new_leader.propose(
        command="SET",
        payload={"key": "seat_B2", "value": "MAJORITY_RESERVED"},
        timeout_sec=1.0
    )
    assert success2 is True

    for node in nodes.values():
        await node.stop()

@pytest.mark.asyncio
async def test_full_cluster_restart_recovery_with_noop(cluster_dir):
    """
    Regression test:
    1. Start 3 nodes.
    2. Commit a command (SET seat_A1 = LOCKED).
    3. Verify committed and applied.
    4. Stop all 3 nodes.
    5. Restart all 3 nodes with the same persistent WAL directory.
    6. Allow a new leader to be elected.
    7. Verify the new leader commits its NOOP entry.
    8. Verify the original command is recovered and applied on the cluster
       without submitting another client proposal.
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
            data_dir=os.path.join(cluster_dir, nid),
            heartbeat_interval_ms=50,
            election_timeout_min_ms=150,
            election_timeout_max_ms=300
        )
        rpc = MemoryRPCClient(nid, router)
        node = RaftNode(config=cfg, rpc_client=rpc)
        router.register(node)
        nodes[nid] = node

    for node in nodes.values():
        await node.start()

    # Wait for initial leader
    initial_leader: Optional[RaftNode] = None
    for _ in range(30):
        await asyncio.sleep(0.1)
        leaders = [n for n in nodes.values() if n.role == NodeRole.LEADER]
        if len(leaders) == 1:
            initial_leader = leaders[0]
            break

    assert initial_leader is not None

    # Commit test command
    success, result, err = await initial_leader.propose(
        command="SET",
        payload={"key": "seat_A1", "value": "LOCKED"},
        fencing_token=1,
        idempotency_key="idemp_init"
    )
    assert success is True
    assert initial_leader.state_machine.get_state()["store"] == {"seat_A1": "LOCKED"}

    # Stop all 3 nodes
    for node in nodes.values():
        await node.stop()

    # Restart all 3 nodes from the same persistent WAL storage
    router_restart = MemoryNetworkRouter()
    nodes_restarted: dict[str, RaftNode] = {}

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
        rpc = MemoryRPCClient(nid, router_restart)
        node = RaftNode(config=cfg, rpc_client=rpc)
        router_restart.register(node)
        nodes_restarted[nid] = node

    for node in nodes_restarted.values():
        await node.start()

    # Wait for new leader election after restart
    new_leader: Optional[RaftNode] = None
    for _ in range(40):
        await asyncio.sleep(0.1)
        leaders = [n for n in nodes_restarted.values() if n.role == NodeRole.LEADER]
        if len(leaders) == 1:
            new_leader = leaders[0]
            break

    assert new_leader is not None

    # Wait for leader to replicate and commit its election NOOP
    for _ in range(30):
        await asyncio.sleep(0.1)
        if new_leader.leader_ready and new_leader.commit_index >= new_leader._noop_index:
            break

    assert new_leader.leader_ready is True
    assert new_leader.commit_index >= new_leader._noop_index

    # Verify that the original command (seat_A1 = LOCKED) is committed and applied
    # across ALL cluster nodes without submitting another client proposal
    await asyncio.sleep(0.2)
    for nid, node in nodes_restarted.items():
        assert node.commit_index >= 1, f"{nid} commit_index was not recovered"
        assert node.last_applied >= 1, f"{nid} did not apply recovered entries"
        state = node.state_machine.get_state()
        assert state["store"].get("seat_A1") == "LOCKED", f"{nid} state machine missing recovered state"

    for node in nodes_restarted.values():
        await node.stop()

