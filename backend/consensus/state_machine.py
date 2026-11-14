from abc import ABC, abstractmethod
from typing import Any
from backend.consensus.models import LogEntry

class StateMachine(ABC):
    """
    Abstract interface for the Replicated State Machine.
    Ensures clear separation between log replication, quorum commit, and application.
    """
    @abstractmethod
    def apply(self, entry: LogEntry) -> Any:
        """Apply a committed log entry deterministically."""
        pass

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """Return a snapshot or diagnostic view of current state."""
        pass

class GenericStateMachine(StateMachine):
    """
    General deterministic key-value / command state machine for testing
    and base verification before Phase 2 cinema lock engine.
    """
    def __init__(self):
        self.applied_entries: list[LogEntry] = []
        self.kv_store: dict[str, Any] = {}
        self.last_applied_index: int = 0

    def apply(self, entry: LogEntry) -> Any:
        self.applied_entries.append(entry)
        self.last_applied_index = entry.index
        
        # Simple deterministic command interpreter
        if entry.command == "SET":
            key = entry.payload.get("key")
            val = entry.payload.get("value")
            if key is not None:
                self.kv_store[key] = val
                return {"status": "OK", "key": key, "value": val}
        elif entry.command == "DELETE":
            key = entry.payload.get("key")
            removed = self.kv_store.pop(key, None)
            return {"status": "OK", "removed": removed}
        elif entry.command == "NOOP":
            return {"status": "OK", "noop": True}
        
        return {"status": "APPLIED", "command": entry.command}

    def get_state(self) -> dict[str, Any]:
        return {
            "last_applied_index": self.last_applied_index,
            "applied_count": len(self.applied_entries),
            "store": dict(self.kv_store)
        }
