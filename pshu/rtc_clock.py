from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("PSHU_RTC")


@dataclass
class RTCState:
    poll_interval_sec: float = 30.0
    timeout_sec: float = 1.0
    hwclock_bin: str = "hwclock"


def is_raspberry_pi() -> bool:
    model_paths = (
        Path("/proc/device-tree/model"),
        Path("/sys/firmware/devicetree/base/model"),
    )
    for path in model_paths:
        if path.exists():
            try:
                txt = path.read_text(encoding="utf-8", errors="ignore").lower()
                if "raspberry pi" in txt:
                    return True
            except Exception:
                continue
    return False


class RPIRTCClock:
    """Clock source based on RPi hardware RTC (hwclock) with smoothed offset."""

    def __init__(self, state: RTCState):
        self.state = state
        self.offset_sec: float = 0.0
        self.last_sync_ts: float | None = None
        self.sync_failures: int = 0

    def now(self) -> float:
        return time.time() + self.offset_sec

    async def sync_once(self) -> None:
        loop = asyncio.get_running_loop()
        rtc_ts = await asyncio.wait_for(loop.run_in_executor(None, self._read_rtc_unix_ts), timeout=self.state.timeout_sec)
        sys_ts = time.time()
        measured_offset = rtc_ts - sys_ts
        alpha = 0.2
        self.offset_sec = (1.0 - alpha) * self.offset_sec + alpha * measured_offset
        self.last_sync_ts = sys_ts

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.sync_once()
                logger.info("RTC sync ok offset_sec=%.6f", self.offset_sec)
            except Exception as exc:
                self.sync_failures += 1
                logger.warning("RTC sync failed failures=%s err=%s", self.sync_failures, exc)
            await asyncio.sleep(self.state.poll_interval_sec)

    def _read_rtc_unix_ts(self) -> float:
        out = subprocess.check_output(
            [self.state.hwclock_bin, "--get", "--utc"],
            text=True,
            timeout=self.state.timeout_sec,
        ).strip()
        # Example: 2026-05-10 19:40:12.123456+00:00
        dt = datetime.fromisoformat(out)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
