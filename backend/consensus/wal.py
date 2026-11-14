import json
import os
from typing import Optional
from backend.consensus.models import LogEntry

class DurableStorage:
    """
    Manages durable persistence of Raft metadata (current_term, voted_for)
    and append-only Write-Ahead Log (WAL) with synchronous fsync.
    """
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.meta_file = os.path.join(self.data_dir, "raft.meta")
        self.wal_file = os.path.join(self.data_dir, "raft.wal")

    def save_metadata(self, current_term: int, voted_for: Optional[str]) -> None:
        """Atomically persist Raft metadata with fsync."""
        tmp_file = f"{self.meta_file}.tmp"
        data = {"current_term": current_term, "voted_for": voted_for}
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, self.meta_file)

    def load_metadata(self) -> tuple[int, Optional[str]]:
        """Load Raft metadata if it exists, otherwise default to (0, None)."""
        if not os.path.exists(self.meta_file):
            return 0, None
        try:
            with open(self.meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return int(data.get("current_term", 0)), data.get("voted_for")
        except Exception:
            return 0, None

    def append_entries(self, entries: list[LogEntry]) -> None:
        """Append log entries to WAL and ensure durable disk sync."""
        if not entries:
            return
        with open(self.wal_file, "a", encoding="utf-8") as f:
            for entry in entries:
                line = entry.model_dump_json()
                f.write(f"{line}\n")
            f.flush()
            os.fsync(f.fileno())

    def truncate_and_rewrite(self, entries: list[LogEntry]) -> None:
        """
        Rewrite WAL when log entries conflict with leader's history.
        Uses atomic file replacement with fsync.
        """
        tmp_file = f"{self.wal_file}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            for entry in entries:
                line = entry.model_dump_json()
                f.write(f"{line}\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, self.wal_file)

    def load_log(self) -> list[LogEntry]:
        """
        Replay sequential entries from the WAL on node startup/recovery.
        """
        if not os.path.exists(self.wal_file):
            return []
        entries: list[LogEntry] = []
        with open(self.wal_file, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    try:
                        entry = LogEntry.model_validate_json(line_str)
                        entries.append(entry)
                    except Exception as e:
                        # Log corruption or trailing line
                        break
        return entries
