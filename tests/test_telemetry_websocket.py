import asyncio
import json
import pytest
from httpx import AsyncClient, ASGITransport
from starlette.testclient import TestClient

from backend.main import app, lifespan
from backend.consensus.config import RaftConfig
from backend.consensus.node import RaftNode
from backend.consensus.lock_state_machine import DistributedLockStateMachine
from backend.services.event_bus import cluster_event_bus, EventCategory, ClusterEvent
from backend.services.metrics import cluster_metrics
import backend.main as main_mod

@pytest.fixture
async def initialized_test_cluster(tmp_path):
    """Setup an in-process RaftNode on main.py so endpoints are fully wired."""
    cluster_event_bus.clear()
    cluster_metrics.clear()

    data_dir = str(tmp_path / "node1_test_data")
    cfg = RaftConfig(
        node_id="node1",
        port=9001,
        peers={"node2": "http://node2:8000", "node3": "http://node3:8000"},
        data_dir=data_dir,
        heartbeat_interval_ms=50,
        election_timeout_min_ms=100,
        election_timeout_max_ms=200
    )
    sm = DistributedLockStateMachine()
    node = RaftNode(config=cfg, state_machine=sm)
    main_mod.raft_node = node
    await node.start()

    yield node

    await node.stop()
    main_mod.raft_node = None
    cluster_event_bus.clear()
    cluster_metrics.clear()

def test_websocket_telemetry_initial_connection_and_snapshot(initialized_test_cluster):
    """
    Verify:
    1. WebSocket connection to /ws/telemetry.
    2. Receives connection_status first.
    3. Receives initial authoritative snapshot with node identity, role, metrics, locks.
    """
    client = TestClient(app)
    with client.websocket_connect("/ws/telemetry") as websocket:
        # Message 1: connection_status
        data1 = websocket.receive_json()
        assert data1["type"] == "connection_status"
        assert data1["status"] == "CONNECTED"
        assert "client_id" in data1

        # Message 2: snapshot
        data2 = websocket.receive_json()
        assert data2["type"] == "snapshot"
        assert data2["node_id"] == "node1"
        assert "role" in data2
        assert "current_term" in data2
        assert "commit_index" in data2
        assert "last_applied" in data2
        assert "last_log_index" in data2
        assert "active_reservations" in data2
        assert "active_locks" in data2
        assert "metrics" in data2
        assert "peer_info" in data2

def test_websocket_telemetry_real_events_streaming(initialized_test_cluster):
    """
    Verify:
    Real events published on the EventBus stream to the WebSocket client as 'event' type messages.
    """
    client = TestClient(app)
    with client.websocket_connect("/ws/telemetry") as websocket:
        # Drain connection_status and initial snapshot
        _ = websocket.receive_json()
        _ = websocket.receive_json()

        # Emit an actual cluster event
        cluster_event_bus.publish_nowait(
            ClusterEvent(
                node_id="node1",
                term=2,
                category=EventCategory.CONSENSUS,
                action="ELECTION_WON",
                details={"term": 2, "duration_ms": 142.5}
            )
        )

        event_msg = websocket.receive_json()
        assert event_msg["type"] == "event"
        assert event_msg["originating_node"] == "node1"
        assert event_msg["term"] == 2
        assert event_msg["category"] == "CONSENSUS"
        assert event_msg["action"] == "ELECTION_WON"
        assert event_msg["details"]["term"] == 2

def test_websocket_telemetry_queue_overflow_and_resync(initialized_test_cluster):
    """
    Verify:
    When a subscriber queue overflows, SUBSCRIBER_QUEUE_OVERFLOW triggers a
    'sync_required' message immediately followed by an authoritative fresh snapshot.
    """
    client = TestClient(app)
    with client.websocket_connect("/ws/telemetry") as websocket:
        _ = websocket.receive_json()
        _ = websocket.receive_json()

        # Emit an overflow alert onto the bus
        cluster_event_bus.publish_nowait(
            ClusterEvent(
                node_id="event_bus",
                term=1,
                category=EventCategory.FAULT,
                action="SUBSCRIBER_QUEUE_OVERFLOW",
                details={"dropped_for_client": 5, "total_dropped": 5}
            )
        )

        # Message 1 should be sync_required
        sync_msg = websocket.receive_json()
        assert sync_msg["type"] == "sync_required"
        assert sync_msg["details"]["dropped_for_client"] == 5

        # Message 2 should be the fresh snapshot for re-synchronization
        fresh_snap = websocket.receive_json()
        assert fresh_snap["type"] == "snapshot"
        assert fresh_snap["node_id"] == "node1"

@pytest.mark.asyncio
async def test_stale_fencing_token_fault_endpoint(initialized_test_cluster):
    """
    Verify the fault injection endpoint /api/fault/inject_stale_token
    deliberately tests stale fencing token rejection with proper authorization.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Unauthorized without token header
        resp = await ac.post("/api/fault/inject_stale_token", json={"stale_token": 1})
        assert resp.status_code == 401

        # Authorized with valid local dev token
        resp_auth = await ac.post(
            "/api/fault/inject_stale_token",
            headers={"X-Fault-Token": "dev-fault-insecure-local-token"},
            json={"stale_token": 1, "action": "RENEW"}
        )
        assert resp_auth.status_code == 200
        data = resp_auth.json()
        assert data["status"] == "PROPOSAL_EVALUATED"
        assert "was_rejected" in data
