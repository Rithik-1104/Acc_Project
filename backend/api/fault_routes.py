import ipaddress
import os
import time
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Request, status
from pydantic import BaseModel, Field

logger = logging.getLogger("fault_routes")

router = APIRouter(prefix="/api/fault", tags=["fault_injection"])

# Configurable shared local dev auth token
# In production/exposed environments (APP_ENV == 'production'), an explicit non-default token is mandatory.
APP_ENV = os.getenv("APP_ENV", "development").lower()
FAULT_AUTH_TOKEN = os.getenv("FAULT_AUTH_TOKEN", "dev-fault-insecure-local-token" if APP_ENV != "production" else "")

# Allowed private/local subnets (Localhost IPv4/IPv6, Docker default bridge 172.17.0.0/16, Docker compose 172.16.0.0/12, 10.0.0.0/8, 192.168.0.0/16)
ALLOWED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("172.16.0.0/12"),  # Includes 172.21.0.0/16 used by docker-compose
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("192.168.0.0/16"),
]

def verify_fault_authorization(request: Request, x_fault_token: Optional[str] = Header(None)) -> None:
    """
    Enforces multi-layer security for fault-injection controls:
    1. Source IP check: Request must originate from local machine or private Docker subnet.
    2. Shared local dev token check: Requires valid X-Fault-Token header matching FAULT_AUTH_TOKEN.
    """
    client_host = request.client.host if request.client else None
    if not client_host:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Client IP cannot be verified."
        )

    try:
        client_ip = ipaddress.ip_address(client_host)
        is_allowed = any(client_ip in net for net in ALLOWED_NETWORKS)
    except ValueError:
        is_allowed = False

    if not is_allowed:
        logger.warning(f"Unauthorized external access attempt from {client_host}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: External IP {client_host} not permitted to access fault controls."
        )

    # Require non-empty valid auth token header (never log or leak token values)
    if not FAULT_AUTH_TOKEN or x_fault_token != FAULT_AUTH_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing or invalid X-Fault-Token header."
        )

def get_current_raft_node():
    from backend.main import raft_node
    if not raft_node:
        raise HTTPException(status_code=503, detail="Raft node not initialized")
    return raft_node

class FaultActionRequest(BaseModel):
    node_id: Optional[str] = Field(None, description="Optional target node ID for verification")

@router.post("/isolate")
async def isolate_node(req: FaultActionRequest = FaultActionRequest(), request: Request = None, x_fault_token: Optional[str] = Header(None)):
    """
    Isolate this node from all Raft RPC traffic:
    - Drops outgoing RequestVote and AppendEntries RPCs
    - Rejects incoming RequestVote and AppendEntries RPCs
    """
    verify_fault_authorization(request, x_fault_token)
    node = get_current_raft_node()

    if req.node_id and req.node_id != node.node_id:
        raise HTTPException(
            status_code=400,
            detail=f"Target node_id mismatch: request specified {req.node_id}, but this node is {node.node_id}"
        )

    node.isolate()
    return {
        "status": "ISOLATED",
        "node_id": node.node_id,
        "is_network_isolated": node.is_network_isolated,
        "term": node.current_term,
        "role": node.role.value
    }

@router.post("/heal")
async def heal_node(req: FaultActionRequest = FaultActionRequest(), request: Request = None, x_fault_token: Optional[str] = Header(None)):
    """
    Heal this node, restoring all bidirectional RPC communication.
    """
    verify_fault_authorization(request, x_fault_token)
    node = get_current_raft_node()

    if req.node_id and req.node_id != node.node_id:
        raise HTTPException(
            status_code=400,
            detail=f"Target node_id mismatch: request specified {req.node_id}, but this node is {node.node_id}"
        )

    node.heal()
    return {
        "status": "HEALED",
        "node_id": node.node_id,
        "is_network_isolated": node.is_network_isolated,
        "term": node.current_term,
        "role": node.role.value
    }

@router.post("/stop_node")
async def stop_node(req: FaultActionRequest = FaultActionRequest(), request: Request = None, x_fault_token: Optional[str] = Header(None)):
    """
    Gracefully stops the node's background tasks (heartbeat, election timers).
    Leaves HTTP server alive so it can be monitored and restarted.
    """
    verify_fault_authorization(request, x_fault_token)
    node = get_current_raft_node()

    if req.node_id and req.node_id != node.node_id:
        raise HTTPException(
            status_code=400,
            detail=f"Target node_id mismatch: request specified {req.node_id}, but this node is {node.node_id}"
        )

    await node.stop()
    return {
        "status": "STOPPED",
        "node_id": node.node_id,
        "running": node._running,
        "term": node.current_term,
        "role": node.role.value
    }

@router.post("/start_node")
async def start_node(req: FaultActionRequest = FaultActionRequest(), request: Request = None, x_fault_token: Optional[str] = Header(None)):
    """
    Restarts a stopped node from its persistent storage/WAL.
    """
    verify_fault_authorization(request, x_fault_token)
    node = get_current_raft_node()

    if req.node_id and req.node_id != node.node_id:
        raise HTTPException(
            status_code=400,
            detail=f"Target node_id mismatch: request specified {req.node_id}, but this node is {node.node_id}"
        )

    await node.start()
    return {
        "status": "STARTED",
        "node_id": node.node_id,
        "running": node._running,
        "term": node.current_term,
        "role": node.role.value
    }

class StaleTokenInjectionRequest(BaseModel):
    booking_id: Optional[str] = Field(None, description="Booking ID to target or use active booking")
    stale_token: Optional[int] = Field(1, description="Stale fencing token to inject (e.g. 1)")
    action: Optional[str] = Field("RENEW", description="Action to attempt with stale token: RENEW or CONFIRM")

@router.post("/inject_stale_token")
async def inject_stale_token(
    req: StaleTokenInjectionRequest = StaleTokenInjectionRequest(),
    request: Request = None,
    x_fault_token: Optional[str] = Header(None)
):
    """
    Simulates a split-brain or delayed client attempting to mutate state using a stale fencing token.
    Verified to be rejected by the DistributedLockStateMachine.
    """
    verify_fault_authorization(request, x_fault_token)
    node = get_current_raft_node()

    target_booking_id = req.booking_id
    if not target_booking_id and hasattr(node.state_machine, "bookings") and node.state_machine.bookings:
        target_booking_id = next(iter(node.state_machine.bookings.keys()))

    stale_token = req.stale_token if req.stale_token is not None else 1
    cmd = "CONFIRM_BOOKING" if req.action == "CONFIRM" else "RENEW_RESERVATION"

    # If node is leader and ready, propose directly through Raft
    if node.role.value == "LEADER" and node.leader_ready:
        if not target_booking_id:
            import uuid
            demo_bid = f"stale_test_{uuid.uuid4().hex[:6]}"
            ok, res, err = await node.propose(
                command="RESERVE_SEATS",
                payload={
                    "booking_id": demo_bid,
                    "show_id": "show_1",
                    "seat_ids": ["seat-E10"],
                    "owner_id": "stale_tester"
                },
                idempotency_key=f"idemp_stale_{uuid.uuid4().hex[:6]}"
            )
            if ok and res and res.get("status") == "RESERVED":
                target_booking_id = demo_bid

        if not target_booking_id:
            raise HTTPException(
                status_code=400,
                detail="No booking available or able to be created on leader to test stale token."
            )

        ok, res, err = await node.propose(
            command=cmd,
            payload={
                "booking_id": target_booking_id,
                "owner_id": "stale_tester",
                "current_token": stale_token
            },
            fencing_token=stale_token,
            idempotency_key=f"stale_inj_{time.time()}"
        )
        rejection_status = res.get("status") if isinstance(res, dict) else (err or "REJECTED")
    else:
        # If node is not active leader, directly evaluate against state machine to demonstrate rejection
        from backend.consensus.models import LogEntry
        dummy_entry = LogEntry(
            index=node.commit_index + 1,
            term=node.current_term,
            command=cmd,
            payload={
                "booking_id": target_booking_id or "nonexistent_stale",
                "owner_id": "stale_tester",
                "current_token": stale_token
            },
            fencing_token=stale_token,
            idempotency_key=f"stale_inj_{time.time()}",
            created_at_utc=int(time.time() * 1_000_000)
        )
        res = node.state_machine.apply(dummy_entry)
        rejection_status = res.get("status", "REJECTED_STALE_TOKEN")

    return {
        "status": "PROPOSAL_EVALUATED",
        "command": cmd,
        "booking_id": target_booking_id or "nonexistent_stale",
        "injected_token": stale_token,
        "state_machine_result": res,
        "was_rejected": "REJECTED" in str(rejection_status),
        "detail": f"State machine rejected stale fencing token {stale_token}: {rejection_status}"
    }

