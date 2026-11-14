import os
import shutil
import pytest
from backend.consensus.config import RaftConfig
from backend.consensus.models import LogEntry, RequestVoteArgs, AppendEntriesArgs, NodeRole
from backend.consensus.wal import DurableStorage
from backend.consensus.state_machine import GenericStateMachine
from backend.consensus.node import RaftNode

@pytest.fixture
def test_dir():
    d = "./tmp_test_wal"
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    yield d
    if os.path.exists(d):
        shutil.rmtree(d)

def test_wal_persistence_and_recovery(test_dir):
    storage = DurableStorage(test_dir)
    storage.save_metadata(current_term=3, voted_for="node2")

    entries = [
        LogEntry(index=1, term=1, command="SET", payload={"key": "k1", "value": "v1"}, created_at_utc=1000),
        LogEntry(index=2, term=2, command="SET", payload={"key": "k2", "value": "v2"}, created_at_utc=2000),
        LogEntry(index=3, term=3, command="DELETE", payload={"key": "k1"}, created_at_utc=3000),
    ]
    storage.append_entries(entries)

    # Re-open storage from scratch (simulate crash restart)
    recovery_storage = DurableStorage(test_dir)
    recovered_term, recovered_vote = recovery_storage.load_metadata()
    assert recovered_term == 3
    assert recovered_vote == "node2"

    recovered_log = recovery_storage.load_log()
    assert len(recovered_log) == 3
    assert recovered_log[0].command == "SET"
    assert recovered_log[0].payload == {"key": "k1", "value": "v1"}
    assert recovered_log[2].command == "DELETE"

def test_state_machine_deterministic_application():
    sm = GenericStateMachine()
    e1 = LogEntry(index=1, term=1, command="SET", payload={"key": "seat_A1", "value": "LOCKED"}, created_at_utc=100)
    e2 = LogEntry(index=2, term=1, command="SET", payload={"key": "seat_A2", "value": "LOCKED"}, created_at_utc=200)
    e3 = LogEntry(index=3, term=1, command="DELETE", payload={"key": "seat_A1"}, created_at_utc=300)

    sm.apply(e1)
    sm.apply(e2)
    sm.apply(e3)

    state = sm.get_state()
    assert state["last_applied_index"] == 3
    assert state["applied_count"] == 3
    assert state["store"] == {"seat_A2": "LOCKED"}

@pytest.mark.asyncio
async def test_vote_denial_on_older_term(test_dir):
    config = RaftConfig(node_id="node1", port=8001, data_dir=test_dir)
    node = RaftNode(config=config)
    node.current_term = 2
    node.storage.save_metadata(node.current_term, None)

    # Candidate with term 1 asks for vote
    reply = await node.handle_request_vote(RequestVoteArgs(
        term=1,
        candidate_id="node2",
        last_log_index=0,
        last_log_term=0
    ))
    assert reply.vote_granted is False
    assert reply.term == 2

@pytest.mark.asyncio
async def test_vote_grant_and_term_step_up(test_dir):
    config = RaftConfig(node_id="node1", port=8001, data_dir=test_dir)
    node = RaftNode(config=config)
    node.current_term = 1
    node.storage.save_metadata(node.current_term, None)

    reply = await node.handle_request_vote(RequestVoteArgs(
        term=2,
        candidate_id="node2",
        last_log_index=0,
        last_log_term=0
    ))
    assert reply.vote_granted is True
    assert reply.term == 2
    assert node.current_term == 2
    assert node.voted_for == "node2"
    assert node.role == NodeRole.FOLLOWER

@pytest.mark.asyncio
async def test_follower_rejects_inconsistent_log_entries(test_dir):
    config = RaftConfig(node_id="node1", port=8001, data_dir=test_dir)
    node = RaftNode(config=config)
    node.current_term = 1

    # Leader claims prev_log_index=2, but follower log is empty
    reply = await node.handle_append_entries(AppendEntriesArgs(
        term=1,
        leader_id="node2",
        prev_log_index=2,
        prev_log_term=1,
        entries=[LogEntry(index=3, term=1, command="SET", payload={"k": "v"}, created_at_utc=100)],
        leader_commit=0
    ))
    assert reply.success is False
