from __future__ import annotations
import asyncio
import json
import logging
import socket
import time
from dataclasses import dataclass
from typing import Optional

from pshu.metrics import MetricsCollector

logger = logging.getLogger("PSHU_Drivers")


class BaseDriver:
    async def send_command(self, address: str, args: list) -> None:
        raise NotImplementedError


@dataclass
class RetryPolicy:
    timeout_sec: float = 1.0
    retries: int = 3
    retry_backoff_sec: float = 0.2


class UDPCommandClient:
    def __init__(self, host: str, port: int, policy: RetryPolicy):
        self.host = host
        self.port = port
        self.policy = policy

    async def send(self, payload: bytes) -> None:
        loop = asyncio.get_running_loop()
        last_exc: Optional[Exception] = None
        for attempt in range(self.policy.retries + 1):
            try:
                await asyncio.wait_for(loop.run_in_executor(None, self._send_once, payload), timeout=self.policy.timeout_sec)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < self.policy.retries:
                    await asyncio.sleep(self.policy.retry_backoff_sec * (attempt + 1))
        raise RuntimeError(f"UDP send failed after retries: {last_exc}")

    def _send_once(self, payload: bytes) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, (self.host, self.port))


class TCPCommandClient:
    def __init__(self, host: str, port: int, policy: RetryPolicy):
        self.host = host
        self.port = port
        self.policy = policy

    async def send(self, payload: bytes) -> None:
        last_exc: Optional[Exception] = None
        for attempt in range(self.policy.retries + 1):
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), timeout=self.policy.timeout_sec)
                writer.write(payload + b"\n")
                await asyncio.wait_for(writer.drain(), timeout=self.policy.timeout_sec)
                writer.close()
                await writer.wait_closed()
                return
            except Exception as exc:
                last_exc = exc
                if attempt < self.policy.retries:
                    await asyncio.sleep(self.policy.retry_backoff_sec * (attempt + 1))
        raise RuntimeError(f"TCP send failed after retries: {last_exc}")


class EthernetDeviceDriver(BaseDriver):
    def __init__(self, name: str, host: str, port: int, protocol: str, metrics: MetricsCollector, retry_policy: RetryPolicy):
        self.name = name
        self.metrics = metrics
        self.client = TCPCommandClient(host, port, retry_policy) if protocol == "tcp" else UDPCommandClient(host, port, retry_policy)

    async def send_command(self, address: str, args: list) -> None:
        started = time.time()
        self.metrics.sent += 1
        payload = json.dumps({"driver": self.name, "command": address, "args": args}, ensure_ascii=False).encode("utf-8")
        try:
            await self.client.send(payload)
            self.metrics.record_latency(started)
        except Exception:
            self.metrics.failed += 1
            raise


class PPPDriver(EthernetDeviceDriver):
    pass
