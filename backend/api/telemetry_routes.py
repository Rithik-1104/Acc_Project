import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.services.event_bus import cluster_event_bus, ClusterEvent
from backend.services.metrics import cluster_metrics

logger = logging.getLogger("telemetry_routes")

router = APIRouter(tags=["telemetry"])

def current_utc_micros() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000)

def get_node_state_snapshot(client_id: Optional[str] = None) -> dict[str, Any]:
    from backend.main import raft_node

    if not raft_node:
        return {
            "type": "snapshot",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "node_id": "UNKNOWN",
            "role": "DISCONNECTED",
            "current_term": 0,
            "current_leader": None,
            "commit_index": 0,
            "last_applied": 0,
            "last_log_index": 0,
            "last_log_term": 0,
            "peer_info": {},
            "active_reservations": [],
            "confirmed_bookings": [],
            "active_locks": {},
            "metrics": cluster_metrics.get_metrics_summary(),
            "connection_info": {
                "client_id": client_id,
                "node_status": "UNINITIALIZED",
                "is_network_isolated": False
            }
        }

    sm = raft_node.state_machine
    now_micros = current_utc_micros()

    # Build active reservations with remaining lease seconds calculated from backend deadlines
    active_reservations: list[dict[str, Any]] = []
    confirmed_bookings: list[dict[str, Any]] = []
    active_locks: dict[str, dict[str, Any]] = {}

    if hasattr(sm, "bookings"):
        for bid, binfo in sm.bookings.items():
            remaining_us = max(0, binfo.expires_at_utc - now_micros)
            remaining_sec = round(remaining_us / 1_000_000.0, 2)
            
            b_data = {
                "booking_id": binfo.booking_id,
                "show_id": binfo.show_id,
                "seat_ids": binfo.seat_ids,
                "owner_id": binfo.owner_id,
                "fencing_token": binfo.fencing_token,
                "status": binfo.status,
                "created_at_utc": binfo.created_at_utc,
                "expires_at_utc": binfo.expires_at_utc,
                "remaining_seconds": remaining_sec if binfo.status == "PENDING" else 0.0,
                "max_expiry_ceiling_utc": binfo.max_expiry_ceiling_utc,
                "confirmed_at_utc": binfo.confirmed_at_utc,
                "cancelled_at_utc": binfo.cancelled_at_utc
            }
            if binfo.status == "PENDING" and remaining_us > 0:
                active_reservations.append(b_data)
            elif binfo.status == "CONFIRMED":
                confirmed_bookings.append(b_data)

    if hasattr(sm, "seat_locks"):
        for sid, sinfo in sm.seat_locks.items():
            remaining_us = max(0, sinfo.expires_at_utc - now_micros)
            active_locks[sid] = {
                "seat_id": sinfo.seat_id,
                "booking_id": sinfo.booking_id,
                "owner_id": sinfo.owner_id,
                "fencing_token": sinfo.fencing_token,
                "status": sinfo.status,
                "created_at_utc": sinfo.created_at_utc,
                "expires_at_utc": sinfo.expires_at_utc,
                "remaining_seconds": round(remaining_us / 1_000_000.0, 2) if sinfo.status == "RESERVED" else 0.0,
                "max_expiry_ceiling_utc": sinfo.max_expiry_ceiling_utc
            }

    peer_info = raft_node.get_peer_info() if hasattr(raft_node, "get_peer_info") else {}

    return {
        "type": "snapshot",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "node_id": raft_node.node_id,
        "role": raft_node.role.value,
        "current_term": raft_node.current_term,
        "current_leader": raft_node.current_leader,
        "commit_index": raft_node.commit_index,
        "last_applied": raft_node.last_applied,
        "last_log_index": raft_node.get_last_log_index(),
        "last_log_term": raft_node.get_last_log_term(),
        "peers": raft_node.peers,
        "peer_info": peer_info,
        "is_network_isolated": raft_node.is_network_isolated,
        "is_running": raft_node._running,
        "active_reservations": active_reservations,
        "confirmed_bookings": confirmed_bookings,
        "active_locks": active_locks,
        "fencing_counter": getattr(sm, "fencing_counter", 0),
        "metrics": cluster_metrics.get_metrics_summary(),
        "connection_info": {
            "client_id": client_id,
            "node_status": "RUNNING" if raft_node._running else "STOPPED",
            "is_network_isolated": raft_node.is_network_isolated,
            "active_subscribers": len(cluster_event_bus._subscribers)
        }
    }


@router.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint streaming real-time telemetry from this Raft node:
    - Sends an initial connection_status and full snapshot immediately on connection.
    - Streams genuine real-time events as they occur via bounded EventBus subscription.
    - Emits fresh periodic state snapshots every 1.0 second.
    - Detects subscriber queue overflow and sends sync_required notifications.
    - Never blocks consensus operations or other subscribers.
    """
    await websocket.accept()
    client_id = f"client_{int(time.time() * 1000)}_{id(websocket)}"
    subscriber_queue = cluster_event_bus.subscribe(max_queue_size=100)

    try:
        # 1. Immediately provide connection_status and initial state snapshot
        conn_msg = {
            "type": "connection_status",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": "CONNECTED",
            "client_id": client_id,
            "server_time_micros": current_utc_micros()
        }
        await websocket.send_text(json.dumps(conn_msg))

        initial_snapshot = get_node_state_snapshot(client_id=client_id)
        await websocket.send_text(json.dumps(initial_snapshot))

        # Replay recent history from bounded in-memory ring buffer so timeline survives refresh
        recent_events = cluster_event_bus.get_history(limit=50)
        for h_event in recent_events:
            event_payload = {
                "type": "event",
                "timestamp_utc": h_event.get("timestamp_utc"),
                "timestamp_micros": h_event.get("timestamp_micros"),
                "originating_node": h_event.get("node_id"),
                "term": h_event.get("term"),
                "category": h_event.get("category"),
                "action": h_event.get("action"),
                "details": h_event.get("details", {}),
                "latency_ms": h_event.get("latency_ms")
            }
            await websocket.send_text(json.dumps(event_payload))

        # 2. Main streaming loop: multiplex real-time events and 1-second periodic snapshots
        last_snapshot_time = time.monotonic()
        snapshot_interval_sec = 1.0

        while True:
            # Calculate remaining time until next periodic snapshot
            now = time.monotonic()
            time_until_snapshot = max(0.05, snapshot_interval_sec - (now - last_snapshot_time))

            try:
                # Wait for next event or timeout for next snapshot
                event: ClusterEvent = await asyncio.wait_for(subscriber_queue.get(), timeout=time_until_snapshot)
                
                # Check for queue overflow signal
                if event.action == "SUBSCRIBER_QUEUE_OVERFLOW":
                    overflow_msg = {
                        "type": "sync_required",
                        "timestamp_utc": event.timestamp_utc,
                        "originating_node": event.node_id,
                        "details": event.details
                    }
                    await websocket.send_text(json.dumps(overflow_msg))
                    # Follow immediately with an authoritative state snapshot for re-synchronization
                    fresh_snapshot = get_node_state_snapshot(client_id=client_id)
                    await websocket.send_text(json.dumps(fresh_snapshot))
                else:
                    event_payload = {
                        "type": "event",
                        "timestamp_utc": event.timestamp_utc,
                        "timestamp_micros": event.timestamp_micros,
                        "originating_node": event.node_id,
                        "term": event.term,
                        "category": event.category.value,
                        "action": event.action,
                        "details": event.details,
                        "latency_ms": event.latency_ms
                    }
                    await websocket.send_text(json.dumps(event_payload))

            except asyncio.TimeoutError:
                # Time to send periodic 1-second snapshot
                fresh_snapshot = get_node_state_snapshot(client_id=client_id)
                await websocket.send_text(json.dumps(fresh_snapshot))
                last_snapshot_time = time.monotonic()

    except WebSocketDisconnect:
        logger.info(f"WebSocket client {client_id} disconnected normally.")
    except Exception as e:
        logger.warning(f"WebSocket client {client_id} connection terminated: {e}")
    finally:
        cluster_event_bus.unsubscribe(subscriber_queue)
