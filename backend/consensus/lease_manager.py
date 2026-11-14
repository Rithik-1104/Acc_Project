import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.consensus.node import RaftNode

logger = logging.getLogger("lease_manager")

class LeaseManager:
    """
    Background task running on the Raft Leader.
    Periodically checks the distributed lock state machine for expired leases.
    Proposes an atomic EXPIRE_LEASES entry to Raft when deadlines pass.
    """
    def __init__(self, raft_node: "RaftNode", check_interval_sec: float = 1.0):
        self.node = raft_node
        self.interval = check_interval_sec
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _run_loop(self):
        while self._running:
            try:
                await asyncio.sleep(self.interval)
                # Only the leader initiates lease expiration
                if self.node.role.value != "LEADER" or not self.node.leader_ready:
                    continue

                sm = self.node.state_machine
                if not hasattr(sm, "bookings"):
                    continue

                now_utc = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
                expired_bids: list[str] = []

                for bid, binfo in list(sm.bookings.items()):
                    if binfo.status == "PENDING" and now_utc >= binfo.expires_at_utc:
                        expired_bids.append(bid)

                if expired_bids:
                    logger.info(f"Leader proposing EXPIRE_LEASES for {len(expired_bids)} bookings")
                    await self.node.propose(
                        command="EXPIRE_LEASES",
                        payload={"booking_ids": expired_bids},
                        timeout_sec=2.0
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in lease manager loop: {e}")
