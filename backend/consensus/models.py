from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field

class NodeRole(str, Enum):
    FOLLOWER = "FOLLOWER"
    CANDIDATE = "CANDIDATE"
    LEADER = "LEADER"

class LogEntry(BaseModel):
    index: int = Field(..., description="1-based log index")
    term: int = Field(..., description="Term in which entry was proposed")
    command: str = Field(..., description="State machine command name")
    payload: dict[str, Any] = Field(default_factory=dict, description="Arbitrary command payload")
    fencing_token: Optional[int] = Field(default=None, description="Monotonic 64-bit token")
    idempotency_key: Optional[str] = Field(default=None, description="Client idempotency key")
    created_at_utc: int = Field(..., description="Timestamp in UTC microseconds")

# RequestVote RPC Models
class RequestVoteArgs(BaseModel):
    term: int = Field(..., description="Candidate's term")
    candidate_id: str = Field(..., description="Candidate requesting vote")
    last_log_index: int = Field(..., description="Index of candidate's last log entry")
    last_log_term: int = Field(..., description="Term of candidate's last log entry")

class RequestVoteReply(BaseModel):
    term: int = Field(..., description="Current term of voter, for candidate to update itself")
    vote_granted: bool = Field(..., description="True means candidate received vote")
    reason: Optional[str] = Field(default=None)

# AppendEntries RPC Models
class AppendEntriesArgs(BaseModel):
    term: int = Field(..., description="Leader's term")
    leader_id: str = Field(..., description="So follower can redirect clients")
    prev_log_index: int = Field(..., description="Index of log entry immediately preceding new ones")
    prev_log_term: int = Field(..., description="Term of prev_log_index entry")
    entries: list[LogEntry] = Field(default_factory=list, description="Log entries to store (empty for heartbeat)")
    leader_commit: int = Field(..., description="Leader's commit_index")

class AppendEntriesReply(BaseModel):
    term: int = Field(..., description="Current term, for leader to update itself")
    success: bool = Field(..., description="True if follower contained entry matching prev_log_index and prev_log_term")
    match_index: int = Field(default=0, description="Highest index replicated successfully")
    reason: Optional[str] = Field(default=None)
