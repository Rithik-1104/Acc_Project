import asyncio
import random
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from backend.consensus.config import RaftConfig
from backend.consensus.models import (
    NodeRole, LogEntry,
    RequestVoteArgs, RequestVoteReply,
    AppendEntriesArgs, AppendEntriesReply
)
from backend.consensus.wal import DurableStorage
from backend.consensus.state_machine import StateMachine, GenericStateMachine
from backend.consensus.rpc import RaftRPCClient
from backend.services.event_bus import ClusterEvent, EventCategory, cluster_event_bus
from backend.services.metrics import cluster_metrics

def current_time_utc_micros() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000)

class RaftNode:
    """
    Production-grade Raft consensus node implementing:
    - Roles: FOLLOWER, CANDIDATE, LEADER
    - Randomized election timers and heartbeat scheduler
    - Append-only WAL persistence with fsync
    - Log replication and strict majority quorum (2/3 in 3-node cluster)
    - Deterministic state machine application separating commit from apply
    """
    def __init__(
        self,
        config: RaftConfig,
        state_machine: Optional[StateMachine] = None,
        rpc_client: Optional[RaftRPCClient] = None
    ):
        self.config = config
        self.node_id = config.node_id
        self.peers = dict(config.peers)  # peer_id -> url
        self.storage = DurableStorage(config.data_dir)
        self.state_machine = state_machine or GenericStateMachine()
        self.rpc_client = rpc_client or RaftRPCClient(timeout_ms=config.rpc_timeout_ms)

        # Persistent state on all servers (saved to disk before responding)
        self.current_term: int = 0
        self.voted_for: Optional[str] = None
        self.log: list[LogEntry] = []  # 1-indexed in conceptual Raft, 0-indexed in Python list

        # Volatile state on all servers
        self.commit_index: int = 0
        self.last_applied: int = 0
        self.role: NodeRole = NodeRole.FOLLOWER
        self.current_leader: Optional[str] = None

        # Volatile state on leaders
        self.next_index: dict[str, int] = {}
        self.match_index: dict[str, int] = {}
        self.leader_ready: bool = False
        self._noop_index: Optional[int] = None
        self._applied_results: dict[int, Any] = {}

        # Timers and concurrency primitives
        self._election_deadline: float = 0.0
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._election_task: Optional[asyncio.Task] = None
        self._running: bool = True
        self._lock = asyncio.Lock()
        
        # Telemetry / metrics tracking
        self.last_election_duration_ms: float = 0.0
        self.last_heartbeat_time: float = 0.0
        self.on_event: Optional[Callable[[ClusterEvent], None]] = None

        # Fault injection controls (transport layer isolation)
        self.is_network_isolated: bool = False
        self.peer_connectivity: dict[str, dict[str, Any]] = {
            pid: {"connected": True, "last_seen_monotonic": time.monotonic(), "match_index": 0}
            for pid in self.peers
        }

        # Load persisted state from disk
        self._recover_from_storage()

    def _recover_from_storage(self) -> None:
        """
        Recover metadata and replay WAL log.
        Followers and recovering nodes do not unilaterally drop or expire entries.
        """
        self.current_term, self.voted_for = self.storage.load_metadata()
        self.log = self.storage.load_log()

        # Replay committed entries into state machine (up to available log)
        # Note: commit_index starts at 0 and will advance safely via leader heartbeats,
        # but in single-node/restart situations, state machine can replay verified entries.
        for entry in self.log:
            # We don't advance commit_index beyond 0 until confirmed, 
            # but if this was already committed in a previous run:
            pass

    def _reset_election_deadline(self) -> None:
        """Reset election timeout randomly between min and max config values."""
        timeout_sec = random.uniform(
            self.config.election_timeout_min_ms / 1000.0,
            self.config.election_timeout_max_ms / 1000.0
        )
        self._election_deadline = time.monotonic() + timeout_sec

    def get_last_log_index(self) -> int:
        return self.log[-1].index if self.log else 0

    def get_last_log_term(self) -> int:
        return self.log[-1].term if self.log else 0

    def get_peer_info(self) -> dict[str, dict[str, Any]]:
        """Return connectivity and match_index info for known peers."""
        now = time.monotonic()
        result = {}
        for pid, purl in self.peers.items():
            info = self.peer_connectivity.get(pid, {})
            # Consider connected if marked connected and seen within last 2 seconds or if node is active
            last_seen = info.get("last_seen_monotonic", 0.0)
            is_connected = info.get("connected", False) and (now - last_seen < 3.0 or last_seen == 0.0)
            if self.is_network_isolated:
                is_connected = False
            result[pid] = {
                "peer_id": pid,
                "url": purl,
                "connected": is_connected,
                "match_index": self.match_index.get(pid, info.get("match_index", 0)),
                "next_index": self.next_index.get(pid, 1),
                "seconds_since_last_contact": round(now - last_seen, 2) if last_seen > 0 else None
            }
        return result

    def get_entry(self, index: int) -> Optional[LogEntry]:
        if 1 <= index <= len(self.log):
            return self.log[index - 1]
        return None

    def _emit_event(
        self,
        category: EventCategory,
        action: str,
        details: Optional[dict[str, Any]] = None,
        latency_ms: Optional[float] = None
    ) -> None:
        """Lightweight non-blocking telemetry emitter."""
        evt = ClusterEvent(
            node_id=self.node_id,
            term=self.current_term,
            category=category,
            action=action,
            details=details or {},
            latency_ms=latency_ms
        )
        cluster_event_bus.publish_nowait(evt)
        if self.on_event:
            try:
                self.on_event(evt)
            except Exception:
                pass

    def isolate(self) -> None:
        """
        Isolate this node from network traffic:
        - Drops outbound RequestVote and AppendEntries RPCs in rpc_client
        - Drops inbound RequestVote and AppendEntries RPC requests
        """
        self.is_network_isolated = True
        if hasattr(self.rpc_client, "isolate"):
            self.rpc_client.isolate()
        self._emit_event(
            category=EventCategory.FAULT,
            action="NODE_ISOLATED",
            details={"node_id": self.node_id, "term": self.current_term, "role": self.role.value}
        )

    def heal(self) -> None:
        """
        Restore network communication for this node.
        Resets election deadline so the node can participate normally.
        """
        self.is_network_isolated = False
        if hasattr(self.rpc_client, "heal"):
            self.rpc_client.heal()
        self._reset_election_deadline()
        self._emit_event(
            category=EventCategory.FAULT,
            action="NODE_HEALED",
            details={"node_id": self.node_id, "term": self.current_term, "role": self.role.value}
        )

    async def start(self) -> None:
        """Start the Raft background election and heartbeat tasks."""
        async with self._lock:
            if self._running and self._election_task and not self._election_task.done():
                return
            # Reload persisted state if restarting after stop
            self._recover_from_storage()
            self._running = True
            self._reset_election_deadline()
            if not self._election_task or self._election_task.done():
                self._election_task = asyncio.create_task(self._election_timer_loop())
            action = "NODE_RESTARTED" if len(self.log) > 0 or self.current_term > 0 else "NODE_STARTED"
            self._emit_event(
                category=EventCategory.FAULT,
                action=action,
                details={"node_id": self.node_id, "term": self.current_term, "role": self.role.value}
            )

    async def stop(self) -> None:
        """Gracefully stop background tasks and close network connections."""
        async with self._lock:
            self._running = False
            if self.role == NodeRole.LEADER:
                self.role = NodeRole.FOLLOWER
            self.leader_ready = False
            self.current_leader = None

        if self._election_task:
            self._election_task.cancel()
            try:
                await self._election_task
            except asyncio.CancelledError:
                pass
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        await self.rpc_client.close()
        self._emit_event(
            category=EventCategory.FAULT,
            action="NODE_STOPPED",
            details={"node_id": self.node_id, "term": self.current_term, "role": self.role.value}
        )

    # -------------------------------------------------------------------------
    # Election and Role Transitions
    # -------------------------------------------------------------------------
    async def _election_timer_loop(self) -> None:
        while self._running:
            await asyncio.sleep(0.05)
            async with self._lock:
                if self.is_network_isolated:
                    self._reset_election_deadline()
                    continue
                if self.role != NodeRole.LEADER and time.monotonic() >= self._election_deadline:
                    # Election timeout elapsed without heartbeat from leader
                    asyncio.create_task(self._start_election())

    async def _start_election(self) -> None:
        start_time = time.monotonic()
        async with self._lock:
            self.role = NodeRole.CANDIDATE
            self.current_term += 1
            self.voted_for = self.node_id
            self.current_leader = None
            self.storage.save_metadata(self.current_term, self.voted_for)
            self._reset_election_deadline()

            current_term = self.current_term
            last_log_index = self.get_last_log_index()
            last_log_term = self.get_last_log_term()
            votes_received = 1  # Vote for self
            peers_to_contact = dict(self.peers)

        total_nodes = len(peers_to_contact) + 1
        majority = (total_nodes // 2) + 1

        if votes_received >= majority:
            # Single-node cluster case
            async with self._lock:
                await self._become_leader()
            return

        # Prepare RequestVote arguments
        vote_args = RequestVoteArgs(
            term=current_term,
            candidate_id=self.node_id,
            last_log_index=last_log_index,
            last_log_term=last_log_term
        )

        async def request_peer_vote(peer_id: str, peer_url: str) -> bool:
            reply = await self.rpc_client.send_request_vote(peer_url, vote_args)
            if not reply:
                if peer_id in self.peer_connectivity:
                    self.peer_connectivity[peer_id]["connected"] = False
                return False
            if peer_id in self.peer_connectivity:
                self.peer_connectivity[peer_id]["connected"] = True
                self.peer_connectivity[peer_id]["last_seen_monotonic"] = time.monotonic()
            async with self._lock:
                if reply.term > self.current_term:
                    self.current_term = reply.term
                    self.role = NodeRole.FOLLOWER
                    self.voted_for = None
                    self.storage.save_metadata(self.current_term, self.voted_for)
                    self._reset_election_deadline()
                    return False
                if self.role == NodeRole.CANDIDATE and reply.term == self.current_term and reply.vote_granted:
                    return True
            return False

        tasks = [
            asyncio.create_task(request_peer_vote(pid, purl))
            for pid, purl in peers_to_contact.items()
        ]

        for completed in asyncio.as_completed(tasks):
            granted = await completed
            if granted:
                votes_received += 1
                if votes_received >= majority:
                    async with self._lock:
                        if self.role == NodeRole.CANDIDATE and self.current_term == current_term:
                            self.last_election_duration_ms = (time.monotonic() - start_time) * 1000.0
                            await self._become_leader()
                    break

    async def _become_leader(self) -> None:
        self.role = NodeRole.LEADER
        self.current_leader = self.node_id
        self.leader_ready = False

        self._emit_event(
            category=EventCategory.CONSENSUS,
            action="ELECTION_WON",
            details={"term": self.current_term, "duration_ms": round(self.last_election_duration_ms, 2)}
        )

        # Append internal election NOOP entry in the new current_term
        new_index = self.get_last_log_index() + 1
        self._noop_index = new_index
        noop_entry = LogEntry(
            index=new_index,
            term=self.current_term,
            command="NOOP",
            payload={"reason": "election_stabilization"},
            created_at_utc=current_time_utc_micros()
        )
        self.log.append(noop_entry)
        self.storage.append_entries([noop_entry])

        last_index = self.get_last_log_index()
        for pid in self.peers:
            self.next_index[pid] = last_index + 1
            self.match_index[pid] = 0

        # Check if single-node cluster
        total_nodes = len(self.peers) + 1
        if total_nodes == 1:
            self.commit_index = new_index
            await self._apply_entries_to_state_machine()
            self.leader_ready = True

        # Start periodic heartbeats
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        # Send initial immediate heartbeat to replicate NOOP
        asyncio.create_task(self._send_heartbeats_to_all())

    # -------------------------------------------------------------------------
    # Heartbeat and Replication Loop
    # -------------------------------------------------------------------------
    async def _heartbeat_loop(self) -> None:
        interval_sec = self.config.heartbeat_interval_ms / 1000.0
        while self._running and self.role == NodeRole.LEADER:
            await self._send_heartbeats_to_all()
            await asyncio.sleep(interval_sec)

    async def _send_heartbeats_to_all(self) -> None:
        async with self._lock:
            if self.role != NodeRole.LEADER:
                return
            current_term = self.current_term
            leader_commit = self.commit_index
            peers_snapshot = dict(self.peers)

        for pid, purl in peers_snapshot.items():
            asyncio.create_task(self._replicate_to_peer(pid, purl, current_term, leader_commit))

    async def _replicate_to_peer(self, peer_id: str, peer_url: str, current_term: int, leader_commit: int) -> None:
        async with self._lock:
            if self.role != NodeRole.LEADER or self.current_term != current_term:
                return
            prev_index = self.next_index.get(peer_id, self.get_last_log_index() + 1) - 1
            prev_term = 0
            if prev_index > 0:
                prev_entry = self.get_entry(prev_index)
                if prev_entry:
                    prev_term = prev_entry.term

            entries_to_send = self.log[prev_index:]

        args = AppendEntriesArgs(
            term=current_term,
            leader_id=self.node_id,
            prev_log_index=prev_index,
            prev_log_term=prev_term,
            entries=entries_to_send,
            leader_commit=leader_commit
        )

        reply = await self.rpc_client.send_append_entries(peer_url, args)
        if not reply:
            if peer_id in self.peer_connectivity:
                self.peer_connectivity[peer_id]["connected"] = False
            return

        if peer_id in self.peer_connectivity:
            self.peer_connectivity[peer_id]["connected"] = True
            self.peer_connectivity[peer_id]["last_seen_monotonic"] = time.monotonic()
            self.peer_connectivity[peer_id]["match_index"] = reply.match_index

        async with self._lock:
            if reply.term > self.current_term:
                self.current_term = reply.term
                self.role = NodeRole.FOLLOWER
                self.voted_for = None
                self.current_leader = None
                self.leader_ready = False
                self._noop_index = None
                self.storage.save_metadata(self.current_term, self.voted_for)
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()
                self._reset_election_deadline()
                return

            if self.role != NodeRole.LEADER or self.current_term != current_term:
                return

            if reply.success:
                old_match = self.match_index.get(peer_id, 0)
                self.next_index[peer_id] = reply.match_index + 1
                self.match_index[peer_id] = reply.match_index
                # Only emit genuine replication event when log entries were actually replicated (avoid empty heartbeat spam)
                if reply.match_index > old_match:
                    self._emit_event(
                        category=EventCategory.CONSENSUS,
                        action="FOLLOWER_REPLICATION_SUCCESS",
                        details={
                            "follower_id": peer_id,
                            "replicated_index": reply.match_index,
                            "term": current_term
                        }
                    )
                await self._check_and_advance_commit_index()
            else:
                # Follower log inconsistency: decrement next_index and retry
                self.next_index[peer_id] = max(1, self.next_index.get(peer_id, 2) - 1)

    async def _check_and_advance_commit_index(self) -> None:
        """
        Leader checks if there exists an N > commit_index such that
        a majority of match_index[i] >= N and log[N].term == current_term.
        """
        total_nodes = len(self.peers) + 1
        majority = (total_nodes // 2) + 1

        for n in range(self.get_last_log_index(), self.commit_index, -1):
            entry = self.get_entry(n)
            if entry and entry.term == self.current_term:
                # Count matches (including self)
                matches = 1
                for pid in self.peers:
                    if self.match_index.get(pid, 0) >= n:
                        matches += 1
                if matches >= majority:
                    old_commit = self.commit_index
                    self.commit_index = n
                    if self._noop_index and self.commit_index >= self._noop_index:
                        self.leader_ready = True
                    self._emit_event(
                        category=EventCategory.CONSENSUS,
                        action="COMMIT_ADVANCED",
                        details={"old_commit": old_commit, "new_commit": n, "term": self.current_term, "matches": matches}
                    )
                    await self._apply_entries_to_state_machine()
                    break

    async def _apply_entries_to_state_machine(self) -> None:
        """
        Apply committed, unapplied entries sequentially to the state machine.
        """
        while self.commit_index > self.last_applied:
            self.last_applied += 1
            entry = self.get_entry(self.last_applied)
            if entry:
                t0 = time.monotonic()
                res = self.state_machine.apply(entry)
                apply_lat_ms = (time.monotonic() - t0) * 1000.0
                cluster_metrics.record_apply_latency(apply_lat_ms)
                self._applied_results[entry.index] = res

    async def handle_request_vote(self, args: RequestVoteArgs) -> RequestVoteReply:
        if not self._running:
            return RequestVoteReply(
                term=self.current_term,
                vote_granted=False,
                reason="NODE_STOPPED"
            )

        if self.is_network_isolated:
            return RequestVoteReply(
                term=self.current_term,
                vote_granted=False,
                reason="NETWORK_ISOLATED"
            )

        async with self._lock:
            # 1. Reply false if term < current_term
            if args.term < self.current_term:
                return RequestVoteReply(
                    term=self.current_term,
                    vote_granted=False,
                    reason=f"Candidate term {args.term} < current_term {self.current_term}"
                )

            # If term > current_term, step down to follower
            if args.term > self.current_term:
                self.current_term = args.term
                self.role = NodeRole.FOLLOWER
                self.voted_for = None
                self.current_leader = None
                self.leader_ready = False
                self._noop_index = None
                self.storage.save_metadata(self.current_term, self.voted_for)

            # 2. Check if voted_for is null or candidate_id, and candidate's log is at least as up-to-date
            can_vote = (self.voted_for is None or self.voted_for == args.candidate_id)
            
            my_last_term = self.get_last_log_term()
            my_last_index = self.get_last_log_index()

            log_up_to_date = False
            if args.last_log_term > my_last_term:
                log_up_to_date = True
            elif args.last_log_term == my_last_term and args.last_log_index >= my_last_index:
                log_up_to_date = True

            if can_vote and log_up_to_date:
                self.voted_for = args.candidate_id
                self.storage.save_metadata(self.current_term, self.voted_for)
                self._reset_election_deadline()
                return RequestVoteReply(term=self.current_term, vote_granted=True)

            return RequestVoteReply(
                term=self.current_term,
                vote_granted=False,
                reason=f"Vote denied (can_vote={can_vote}, log_up_to_date={log_up_to_date})"
            )

    async def handle_append_entries(self, args: AppendEntriesArgs) -> AppendEntriesReply:
        if not self._running:
            return AppendEntriesReply(
                term=self.current_term,
                success=False,
                match_index=0,
                reason="NODE_STOPPED"
            )

        if self.is_network_isolated:
            return AppendEntriesReply(
                term=self.current_term,
                success=False,
                match_index=0,
                reason="NETWORK_ISOLATED"
            )

        async with self._lock:
            self.last_heartbeat_time = time.monotonic()
            if args.leader_id in self.peer_connectivity:
                self.peer_connectivity[args.leader_id]["connected"] = True
                self.peer_connectivity[args.leader_id]["last_seen_monotonic"] = time.monotonic()
            
            # 1. Reply false if term < current_term
            if args.term < self.current_term:
                return AppendEntriesReply(
                    term=self.current_term,
                    success=False,
                    reason=f"Leader term {args.term} < current_term {self.current_term}"
                )

            # Recognize valid leader and reset election timer
            if args.term > self.current_term or self.role != NodeRole.FOLLOWER:
                self.current_term = args.term
                self.role = NodeRole.FOLLOWER
                self.voted_for = None
                self.leader_ready = False
                self._noop_index = None
                self.storage.save_metadata(self.current_term, self.voted_for)

            self.current_leader = args.leader_id
            self._reset_election_deadline()

            # 2. Reply false if log doesn't contain entry at prev_log_index matching prev_log_term
            if args.prev_log_index > 0:
                prev_entry = self.get_entry(args.prev_log_index)
                if not prev_entry or prev_entry.term != args.prev_log_term:
                    return AppendEntriesReply(
                        term=self.current_term,
                        success=False,
                        match_index=self.get_last_log_index(),
                        reason=f"Log mismatch at prev_log_index {args.prev_log_index}"
                    )

            # 3. If an existing entry conflicts with a new one, delete existing entry and all that follow it
            insert_idx = args.prev_log_index
            needs_rewrite = False
            for entry in args.entries:
                insert_idx += 1
                existing = self.get_entry(insert_idx)
                if existing:
                    if existing.term != entry.term:
                        # Conflict: truncate in memory and prepare rewrite
                        self.log = self.log[:insert_idx - 1]
                        needs_rewrite = True
                        break
                else:
                    break

            if needs_rewrite:
                self.storage.truncate_and_rewrite(self.log)

            # 4. Append any new entries not already in the log
            new_entries: list[LogEntry] = []
            for entry in args.entries:
                if entry.index > self.get_last_log_index():
                    self.log.append(entry)
                    new_entries.append(entry)

            if new_entries:
                # Durably flush to WAL before acknowledging
                self.storage.append_entries(new_entries)

            # 5. If leader_commit > commit_index, set commit_index = min(leader_commit, index of last entry)
            if args.leader_commit > self.commit_index:
                old_c = self.commit_index
                new_c = min(args.leader_commit, self.get_last_log_index())
                if new_c > old_c:
                    self.commit_index = new_c
                    self._emit_event(
                        category=EventCategory.CONSENSUS,
                        action="COMMIT_ADVANCED",
                        details={"old_commit": old_c, "new_commit": new_c, "term": self.current_term, "leader_id": args.leader_id}
                    )
                    await self._apply_entries_to_state_machine()

            return AppendEntriesReply(
                term=self.current_term,
                success=True,
                match_index=self.get_last_log_index()
            )

    # -------------------------------------------------------------------------
    # Client Command Proposal (Leader API)
    # -------------------------------------------------------------------------
    async def propose(
        self,
        command: str,
        payload: dict[str, Any],
        fencing_token: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        timeout_sec: float = 3.0
    ) -> tuple[bool, Any, Optional[str]]:
        """
        Propose a new command to the Raft cluster.
        Returns: (success, result, error_message)
        """
        start_time = time.monotonic()
        if not self._running:
            return False, None, "NODE_STOPPED"

        async with self._lock:
            if not self._running:
                return False, None, "NODE_STOPPED"
            if self.role != NodeRole.LEADER:
                cluster_metrics.record_proposal(latency_ms=0.0, success=False, reason="NOT_LEADER")
                return False, None, f"NOT_LEADER:{self.current_leader or 'UNKNOWN'}"

            new_index = self.get_last_log_index() + 1
            entry = LogEntry(
                index=new_index,
                term=self.current_term,
                command=command,
                payload=payload,
                fencing_token=fencing_token,
                idempotency_key=idempotency_key,
                created_at_utc=current_time_utc_micros()
            )
            self.log.append(entry)
            self.storage.append_entries([entry])

            # If single-node cluster (no peers), advance commit immediately
            if not self.peers:
                self.commit_index = new_index
                await self._apply_entries_to_state_machine()

        # Trigger immediate replication
        await self._send_heartbeats_to_all()

        # Wait until entry is committed
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            async with self._lock:
                if self.role != NodeRole.LEADER:
                    lat_ms = (time.monotonic() - start_time) * 1000.0
                    cluster_metrics.record_proposal(latency_ms=lat_ms, success=False, reason="LOST_LEADERSHIP")
                    return False, None, "LOST_LEADERSHIP"
                if self.commit_index >= new_index and self.leader_ready:
                    # Entry has achieved majority quorum commitment
                    result = self._applied_results.get(new_index)
                    if result is None:
                        result = self.state_machine.get_state()
                    lat_ms = (time.monotonic() - start_time) * 1000.0
                    cluster_metrics.record_proposal(latency_ms=lat_ms, success=True)
                    self._emit_event(
                        category=EventCategory.CONSENSUS,
                        action="PROPOSAL_COMMITTED",
                        details={"command": command, "index": new_index, "term": self.current_term},
                        latency_ms=round(lat_ms, 2)
                    )
                    return True, result, None
            await asyncio.sleep(0.02)

        lat_ms = (time.monotonic() - start_time) * 1000.0
        cluster_metrics.record_proposal(latency_ms=lat_ms, success=False, reason="TIMEOUT_NO_QUORUM")
        self._emit_event(
            category=EventCategory.CONSENSUS,
            action="PROPOSAL_FAILED",
            details={"command": command, "index": new_index, "reason": "PROPOSAL_TIMEOUT_NO_QUORUM"},
            latency_ms=round(lat_ms, 2)
        )
        return False, None, "PROPOSAL_TIMEOUT_NO_QUORUM"
