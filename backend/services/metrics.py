import math
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

class MetricsEngine:
    """
    Lightweight, bounded metrics engine collecting actual backend operation latency,
    request counts, and exact percentile calculations without external dependencies.
    """
    def __init__(self, window_size: int = 1000):
        self.window_size = window_size
        self._commit_latencies: deque[float] = deque(maxlen=window_size)
        self._apply_latencies: deque[float] = deque(maxlen=window_size)
        self.total_requests: int = 0
        self.successful_requests: int = 0
        self.rejected_requests: int = 0
        self.last_updated_utc: str = datetime.now(timezone.utc).isoformat()

    def record_proposal(self, latency_ms: float, success: bool, reason: Optional[str] = None) -> None:
        """Record an actual proposal-to-quorum-commit operation latency and result."""
        self.total_requests += 1
        if success:
            self.successful_requests += 1
            self._commit_latencies.append(latency_ms)
        else:
            self.rejected_requests += 1

        self.last_updated_utc = datetime.now(timezone.utc).isoformat()

    def record_apply_latency(self, latency_ms: float) -> None:
        """Record actual state-machine application latency separately."""
        self._apply_latencies.append(latency_ms)
        self.last_updated_utc = datetime.now(timezone.utc).isoformat()

    def get_percentile(self, p: float, data: Optional[deque] = None) -> float:
        """
        Calculate the exact p-th percentile (0.0 to 100.0) from recorded latency measurements.
        Uses standard nearest-rank / linear interpolation method.
        """
        samples = list(data if data is not None else self._commit_latencies)
        if not samples:
            return 0.0

        sorted_latencies = sorted(samples)
        n = len(sorted_latencies)
        if n == 1:
            return sorted_latencies[0]

        # Calculate rank
        rank = (p / 100.0) * (n - 1)
        lower_idx = int(math.floor(rank))
        upper_idx = int(math.ceil(rank))
        weight = rank - lower_idx

        if lower_idx == upper_idx:
            return round(sorted_latencies[lower_idx], 2)

        interpolated = sorted_latencies[lower_idx] * (1.0 - weight) + sorted_latencies[upper_idx] * weight
        return round(interpolated, 2)

    def get_metrics_summary(self) -> dict[str, Any]:
        """Return exact summary statistics computed strictly from recorded measurements."""
        count = len(self._commit_latencies)
        avg_commit = round(sum(self._commit_latencies) / count, 2) if count > 0 else 0.0
        min_commit = round(min(self._commit_latencies), 2) if count > 0 else 0.0
        max_commit = round(max(self._commit_latencies), 2) if count > 0 else 0.0

        apply_count = len(self._apply_latencies)
        avg_apply = round(sum(self._apply_latencies) / apply_count, 2) if apply_count > 0 else 0.0

        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "rejected_requests": self.rejected_requests,
            "sample_count": count,
            # Primary: Proposal-to-Quorum-Commit latency
            "latency_p50_ms": self.get_percentile(50.0, self._commit_latencies),
            "latency_p95_ms": self.get_percentile(95.0, self._commit_latencies),
            "latency_p99_ms": self.get_percentile(99.0, self._commit_latencies),
            "latency_avg_ms": avg_commit,
            "latency_min_ms": min_commit,
            "latency_max_ms": max_commit,
            # Separate: State Machine Application latency
            "apply_sample_count": apply_count,
            "apply_latency_p50_ms": self.get_percentile(50.0, self._apply_latencies),
            "apply_latency_avg_ms": avg_apply,
            "last_updated_utc": self.last_updated_utc
        }

    def clear(self) -> None:
        """Reset metrics (used in test teardowns)."""
        self._commit_latencies.clear()
        self._apply_latencies.clear()
        self.total_requests = 0
        self.successful_requests = 0
        self.rejected_requests = 0

# Global singleton metrics engine instance for node runtime
cluster_metrics = MetricsEngine(window_size=1000)
