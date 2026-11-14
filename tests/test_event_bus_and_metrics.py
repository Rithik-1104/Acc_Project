import asyncio
import os
import pytest
from backend.services.event_bus import EventBus, ClusterEvent, EventCategory, cluster_event_bus
from backend.services.metrics import MetricsEngine, cluster_metrics
from backend.consensus.models import LogEntry
from backend.consensus.lock_state_machine import DistributedLockStateMachine

@pytest.mark.asyncio
async def test_event_bus_publishing_and_subscription():
    bus = EventBus(maxlen=10)
    queue = bus.subscribe()

    await bus.publish(
        node_id="node1",
        term=2,
        category=EventCategory.CONSENSUS,
        action="ELECTION_WON",
        details={"term": 2, "duration_ms": 15.2}
    )

    # Verify event received in subscriber queue
    event: ClusterEvent = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event.node_id == "node1"
    assert event.term == 2
    assert event.category == EventCategory.CONSENSUS
    assert event.action == "ELECTION_WON"
    assert event.details["duration_ms"] == 15.2

    # Verify event present in history
    history = bus.get_history()
    assert len(history) == 1
    assert history[0]["action"] == "ELECTION_WON"

    # Unsubscribe
    bus.unsubscribe(queue)

@pytest.mark.asyncio
async def test_event_bus_bounded_ring_buffer():
    bus = EventBus(maxlen=5)

    for i in range(10):
        await bus.publish(
            node_id="node1",
            term=1,
            category=EventCategory.CONSENSUS,
            action=f"EVENT_{i}",
            details={"index": i}
        )

    # Buffer must strictly hold the last 5 events
    history = bus.get_history()
    assert len(history) == 5
    assert history[0]["action"] == "EVENT_5"
    assert history[-1]["action"] == "EVENT_9"

def test_metrics_engine_exact_percentiles():
    metrics = MetricsEngine(window_size=100)

    # Record 100 measurements from 1.0ms to 100.0ms
    for i in range(1, 101):
        metrics.record_proposal(latency_ms=float(i), success=True)

    summary = metrics.get_metrics_summary()
    assert summary["total_requests"] == 100
    assert summary["successful_requests"] == 100
    assert summary["rejected_requests"] == 0
    assert summary["sample_count"] == 100
    assert summary["latency_min_ms"] == 1.0
    assert summary["latency_max_ms"] == 100.0
    assert summary["latency_avg_ms"] == 50.5
    assert summary["latency_p50_ms"] == 50.5
    assert summary["latency_p95_ms"] == 95.05
    assert summary["latency_p99_ms"] == 99.01

def test_metrics_engine_bounded_window():
    metrics = MetricsEngine(window_size=10)

    for i in range(20):
        metrics.record_proposal(latency_ms=float(i * 10), success=True)

    summary = metrics.get_metrics_summary()
    assert summary["total_requests"] == 20
    assert summary["successful_requests"] == 20
    assert summary["sample_count"] == 10  # Capped at window_size=10
    assert summary["latency_min_ms"] == 100.0
    assert summary["latency_max_ms"] == 190.0

@pytest.mark.asyncio
async def test_lock_state_machine_telemetry_emission():
    bus = EventBus(maxlen=20)
    # Temporarily point global bus to test bus
    from backend.services import event_bus
    old_bus = event_bus.cluster_event_bus
    event_bus.cluster_event_bus = bus
    # In lock_state_machine.py it imports cluster_event_bus
    import backend.consensus.lock_state_machine as sm_mod
    sm_mod.cluster_event_bus = bus

    try:
        sm = DistributedLockStateMachine()
        entry = LogEntry(
            index=1,
            term=1,
            command="RESERVE_SEATS",
            payload={"booking_id": "b_telemetry", "show_id": "s1", "seat_ids": ["seat-A1"], "owner_id": "u1"},
            fencing_token=1001,
            created_at_utc=1000000
        )
        res = sm.apply(entry)
        assert res["status"] == "RESERVED"

        history = bus.get_history()
        assert len(history) == 1
        assert history[0]["category"] == "LOCK"
        assert history[0]["action"] == "RESERVE_SEATS_RESERVED"
        assert history[0]["details"]["booking_id"] == "b_telemetry"
    finally:
        event_bus.cluster_event_bus = old_bus
        sm_mod.cluster_event_bus = old_bus

@pytest.mark.asyncio
async def test_raft_node_proposal_latency_measurement(tmp_path):
    from backend.consensus.config import RaftConfig
    from backend.consensus.node import RaftNode
    from backend.consensus.models import NodeRole
    from tests.test_consensus_cluster import MemoryNetworkRouter, MemoryRPCClient

    router = MemoryNetworkRouter()
    nodes: dict[str, RaftNode] = {}
    for i in range(1, 4):
        nid = f"node{i}"
        peers = {f"node{j}": f"mem://node{j}" for j in range(1, 4) if j != i}
        cfg = RaftConfig(
            node_id=nid,
            port=8000 + i,
            peers=peers,
            data_dir=os.path.join(str(tmp_path), nid),
            heartbeat_interval_ms=50,
            election_timeout_min_ms=100,
            election_timeout_max_ms=200
        )
        sm = DistributedLockStateMachine()
        node = RaftNode(config=cfg, state_machine=sm, rpc_client=MemoryRPCClient(nid, router))
        router.register(node)
        nodes[nid] = node
        await node.start()

    # Wait for leader to be elected and ready
    leader = None
    for _ in range(40):
        await asyncio.sleep(0.05)
        leaders = [n for n in nodes.values() if n.role == NodeRole.LEADER and n.leader_ready]
        if len(leaders) == 1:
            leader = leaders[0]
            break

    assert leader is not None
    assert leader.leader_ready is True

    # Record proposal
    success, res, err = await leader.propose(
        command="RESERVE_SEATS",
        payload={"booking_id": "b_lat", "show_id": "s1", "seat_ids": ["seat-B1"], "owner_id": "u1"},
        timeout_sec=2.0
    )
    assert success is True
    assert res["status"] == "RESERVED"

    # Confirm real latency was recorded into cluster_metrics
    summary = cluster_metrics.get_metrics_summary()
    assert summary["successful_requests"] >= 1
    assert summary["latency_min_ms"] > 0.0
    # Confirm separate state machine application latency was recorded
    assert summary["apply_sample_count"] >= 1
    assert summary["apply_latency_avg_ms"] >= 0.0

    # Item 2 verification: Check that FOLLOWER_REPLICATION_SUCCESS event was published with follower node ID and replicated index
    repl_events = [e for e in cluster_event_bus.get_history() if e["action"] == "FOLLOWER_REPLICATION_SUCCESS"]
    assert len(repl_events) >= 1
    sample_repl = repl_events[0]
    assert sample_repl["category"] == "CONSENSUS"
    assert "follower_id" in sample_repl["details"]
    assert sample_repl["details"]["replicated_index"] >= 1

    for n in nodes.values():
        await n.stop()

@pytest.mark.asyncio
async def test_subscriber_queue_overflow_is_observable():
    """
    Item 3 verification:
    If a subscriber is slow or fails to consume messages, queue overflow is observable.
    The bus tracks dropped counts and inserts a SUBSCRIBER_QUEUE_OVERFLOW alert.
    """
    bus = EventBus(maxlen=20)
    # Register subscriber with small queue size = 2
    q = bus.subscribe(max_queue_size=2)

    # Publish 5 events without reading from q
    for i in range(5):
        await bus.publish(
            node_id="node1",
            term=1,
            category=EventCategory.CONSENSUS,
            action=f"EVENT_{i}",
            details={"index": i}
        )

    # Verify drop tracking
    stats = bus.get_overflow_stats()
    assert stats["total_events_published"] == 5
    assert stats["total_events_dropped"] >= 3

    # Verify that the subscriber receives an overflow alert instructing it to re-sync
    received = []
    while not q.empty():
        received.append(q.get_nowait())

    overflow_alerts = [e for e in received if e.action == "SUBSCRIBER_QUEUE_OVERFLOW"]
    assert len(overflow_alerts) >= 1
    alert = overflow_alerts[0]
    assert alert.category == EventCategory.FAULT
    assert "dropped_for_client" in alert.details
    assert alert.details["dropped_for_client"] >= 1

    bus.unsubscribe(q)
