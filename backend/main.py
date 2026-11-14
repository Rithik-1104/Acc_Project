import os
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Optional
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from backend.consensus.config import get_node_config_from_env
from backend.consensus.node import RaftNode
from backend.consensus.lock_state_machine import DistributedLockStateMachine
from backend.consensus.lease_manager import LeaseManager
from backend.consensus.models import (
    RequestVoteArgs, RequestVoteReply,
    AppendEntriesArgs, AppendEntriesReply
)
from backend.db.session import AsyncSessionLocal, init_db
from backend.db.init_db import seed_cinema_data
from backend.services.booking_coordinator import BookingCoordinator
from backend.api.cinema_routes import router as cinema_router
from backend.api.fault_routes import router as fault_router
from backend.api.telemetry_routes import router as telemetry_router

raft_node: Optional[RaftNode] = None
booking_coordinator: Optional[BookingCoordinator] = None
lease_manager: Optional[LeaseManager] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global raft_node, booking_coordinator, lease_manager
    config = get_node_config_from_env()

    # Phase 2: Use DistributedLockStateMachine with atomic multi-seat locks and 64-bit fencing
    lock_sm = DistributedLockStateMachine()
    raft_node = RaftNode(config=config, state_machine=lock_sm)
    await raft_node.start()

    # Initialize BookingCoordinator for PostgreSQL reconciliation
    booking_coordinator = BookingCoordinator(session_factory=AsyncSessionLocal)

    # Initialize background lease manager (leader-driven auto expiry)
    lease_manager = LeaseManager(raft_node=raft_node, check_interval_sec=1.0)
    lease_manager.start()

    # Background task to automatically reconcile unapplied committed entries if this node becomes Leader
    async def reconciliation_loop():
        while True:
            try:
                await asyncio.sleep(0.5)
                if raft_node and raft_node.role.value == "LEADER" and raft_node.leader_ready and booking_coordinator:
                    await booking_coordinator.reconcile_unapplied_entries(raft_node)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    reconciliation_task = asyncio.create_task(reconciliation_loop())

    # Seed cinema database if DB is reachable
    try:
        await seed_cinema_data()
    except Exception as e:
        # DB might be offline during standalone unit tests
        pass

    yield

    reconciliation_task.cancel()

    if lease_manager:
        lease_manager.stop()
    if raft_node:
        await raft_node.stop()

app = FastAPI(title="Fault-Tolerant Distributed Lock Cinema Service", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cinema_router)
app.include_router(fault_router)
app.include_router(telemetry_router)

# Consensus RPC Endpoints
@app.post("/raft/request_vote", response_model=RequestVoteReply)
async def request_vote(args: RequestVoteArgs):
    if not raft_node:
        raise HTTPException(status_code=503, detail="Raft node not initialized")
    return await raft_node.handle_request_vote(args)

@app.post("/raft/append_entries", response_model=AppendEntriesReply)
async def append_entries(args: AppendEntriesArgs):
    if not raft_node:
        raise HTTPException(status_code=503, detail="Raft node not initialized")
    return await raft_node.handle_append_entries(args)

# Cluster Topology and Inspection Endpoints
@app.get("/api/cluster/topology")
async def get_topology():
    if not raft_node:
        raise HTTPException(status_code=503, detail="Raft node not initialized")

    return {
        "node_id": raft_node.node_id,
        "role": raft_node.role.value,
        "current_term": raft_node.current_term,
        "voted_for": raft_node.voted_for,
        "current_leader": raft_node.current_leader,
        "commit_index": raft_node.commit_index,
        "last_applied": raft_node.last_applied,
        "last_log_index": raft_node.get_last_log_index(),
        "last_log_term": raft_node.get_last_log_term(),
        "peers": raft_node.peers,
        "peer_info": raft_node.get_peer_info() if hasattr(raft_node, "get_peer_info") else {},
        "is_network_isolated": raft_node.is_network_isolated,
        "is_running": raft_node._running,
        "last_election_duration_ms": raft_node.last_election_duration_ms,
        "state_machine": raft_node.state_machine.get_state()
    }

class ProposeCommandRequest(BaseModel):
    command: str
    payload: dict[str, Any]
    fencing_token: Optional[int] = None
    idempotency_key: Optional[str] = None

@app.post("/api/cluster/propose")
async def propose_command(req: ProposeCommandRequest):
    if not raft_node:
        raise HTTPException(status_code=503, detail="Raft node not initialized")

    if raft_node.role.value != "LEADER":
        leader_id = raft_node.current_leader
        leader_url = raft_node.peers.get(leader_id) if leader_id else None
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail=f"Not leader. Current leader is {leader_id}",
            headers={"X-Raft-Leader": leader_url or "UNKNOWN"}
        )

    success, result, error = await raft_node.propose(
        command=req.command,
        payload=req.payload,
        fencing_token=req.fencing_token,
        idempotency_key=req.idempotency_key
    )
    if not success:
        raise HTTPException(status_code=500, detail=error or "Proposal failed")

    return {
        "status": "COMMITTED",
        "commit_index": raft_node.commit_index,
        "state_machine_result": result
    }
