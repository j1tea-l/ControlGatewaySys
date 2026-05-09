from __future__ import annotations
import statistics
import time
from dataclasses import dataclass, field
from typing import List


@dataclass
class MetricsCollector:
    latency_ms: List[float] = field(default_factory=list)
    sent: int = 0
    failed: int = 0
    heartbeat_failures: int = 0
    recovery_times_ms: List[float] = field(default_factory=list)

    def record_latency(self, start_ts: float) -> None:
        self.latency_ms.append((time.time() - start_ts) * 1000.0)

    def loss_rate(self) -> float:
        if self.sent == 0:
            return 0.0
        return self.failed / self.sent

    def percentile(self, p: int) -> float:
        if not self.latency_ms:
            return 0.0
        values = sorted(self.latency_ms)
        k = int((len(values) - 1) * p / 100)
        return values[k]

    def snapshot(self) -> dict:
        return {
            "sent": self.sent,
            "failed": self.failed,
            "loss_rate": self.loss_rate(),
            "latency_p95_ms": self.percentile(95),
            "latency_p99_ms": self.percentile(99),
            "latency_mean_ms": statistics.mean(self.latency_ms) if self.latency_ms else 0.0,
            "heartbeat_failures": self.heartbeat_failures,
            "recovery_p95_ms": sorted(self.recovery_times_ms)[int((len(self.recovery_times_ms)-1)*0.95)] if self.recovery_times_ms else 0.0,
        }


    def to_prometheus(self) -> str:
        snap = self.snapshot()
        lines = [
            f"pshu_sent {snap['sent']}",
            f"pshu_failed {snap['failed']}",
            f"pshu_loss_rate {snap['loss_rate']}",
            f"pshu_latency_p95_ms {snap['latency_p95_ms']}",
            f"pshu_latency_p99_ms {snap['latency_p99_ms']}",
            f"pshu_heartbeat_failures {snap['heartbeat_failures']}",
            f"pshu_recovery_p95_ms {snap['recovery_p95_ms']}",
        ]
        return "\n".join(lines) + "\n"

    def export_prometheus(self, path: str = "metrics.prom") -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_prometheus())
