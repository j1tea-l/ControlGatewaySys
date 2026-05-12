from __future__ import annotations
import asyncio
import json
import logging
import socket
import struct
import time
import hashlib
from dataclasses import dataclass
from typing import Optional, Any

from pythonosc.osc_message_builder import OscMessageBuilder

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

    async def send_line(self, payload: bytes) -> None:
        await self._send(payload + b"\n")

    async def send_framed(self, payload: bytes) -> None:
        header = struct.pack("!I", len(payload))
        await self._send(header + payload)

    async def _send(self, payload: bytes) -> None:
        last_exc: Optional[Exception] = None
        for attempt in range(self.policy.retries + 1):
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), timeout=self.policy.timeout_sec)
                writer.write(payload)
                await asyncio.wait_for(writer.drain(), timeout=self.policy.timeout_sec)
                writer.close()
                await writer.wait_closed()
                return
            except Exception as exc:
                last_exc = exc
                if attempt < self.policy.retries:
                    await asyncio.sleep(self.policy.retry_backoff_sec * (attempt + 1))
        raise RuntimeError(f"TCP send failed after retries: {last_exc}")


def _strip_prefix(address: str, prefix: str) -> str:
    if address == prefix:
        return "/"
    if address.startswith(prefix + "/"):
        suffix = address[len(prefix):]
        return suffix if suffix.startswith("/") else "/" + suffix
    return address


class EthernetDeviceDriver(BaseDriver):
    def __init__(self, name: str, host: str, port: int, protocol: str, metrics: MetricsCollector, retry_policy: RetryPolicy, route_prefix: str, output_mode: str = "json", mapping_rules: Optional[dict[str, Any]] = None):
        self.name = name
        self.metrics = metrics
        self.protocol = protocol
        self.route_prefix = route_prefix
        self.output_mode = output_mode
        self.mapping_rules = mapping_rules or {}
        self.udp_client = UDPCommandClient(host, port, retry_policy)
        self.tcp_client = TCPCommandClient(host, port, retry_policy)

    def _encode_payload(self, address: str, args: list) -> bytes:
        if self.output_mode == "osc_native":
            osc_address = _strip_prefix(address, self.route_prefix)
            msg = OscMessageBuilder(address=osc_address)
            for arg in args:
                msg.add_arg(arg)
            return msg.build().dgram
        if self.output_mode == "mapped_json":
            key = address
            rule = self.mapping_rules.get(key, {})
            payload = {
                "driver": self.name,
                "endpoint": rule.get("endpoint", address),
                "fields": rule.get("fields", {}),
                "args": args,
            }
            return json.dumps(payload, ensure_ascii=False).encode("utf-8")
        payload = json.dumps({"driver": self.name, "command": address, "args": args}, ensure_ascii=False).encode("utf-8")
        return payload

    async def send_command(self, address: str, args: list) -> None:
        started = time.time()
        self.metrics.sent += 1
        payload = self._encode_payload(address, args)
        logger.info("TX PREP driver=%s mode=%s bytes=%s address=%s", self.name, self.output_mode, len(payload), address)
        try:
            if self.protocol == "tcp":
                if self.output_mode == "osc_native":
                    await self.tcp_client.send_framed(payload)
                else:
                    await self.tcp_client.send_line(payload)
            else:
                await self.udp_client.send(payload)
            self.metrics.record_latency(started)
            logger.info("TX OK driver=%s address=%s latency_ms=%.3f", self.name, address, self.metrics.latency_ms[-1])
        except Exception as exc:
            self.metrics.failed += 1
            logger.error("TX FAIL driver=%s address=%s err=%s", self.name, address, exc)
            raise


class PPPDriver(EthernetDeviceDriver):
    def __init__(self, *args, ppp_profile: Optional[dict[str, Any]] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ppp_profile = ppp_profile or {}
        self._profile_sent = False

    async def _push_profile_once(self) -> None:
        if self._profile_sent:
            return
        profile = json.dumps(self.ppp_profile.get("rules", {}), ensure_ascii=False).encode("utf-8")
        signature = hashlib.sha256(profile + self.ppp_profile.get("signing_key", "").encode("utf-8")).hexdigest()
        envelope = json.dumps({"type": "ppp_driver_profile", "signature": signature, "payload": profile.decode("utf-8")}, ensure_ascii=False).encode("utf-8")
        await self.tcp_client.send_line(envelope)
        logger.info("PPP PROFILE PUSHED driver=%s bytes=%s", self.name, len(envelope))
        self._profile_sent = True

    async def send_command(self, address: str, args: list) -> None:
        await self._push_profile_once()
        await super().send_command(address, args)
