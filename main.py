import asyncio
import logging

from pshu.config import load_config, parse_routes, parse_ntp
from pshu.core import OSCGatewayProtocol, OSCRouter, RouteEntry
from pshu.drivers import EthernetDeviceDriver, PPPDriver, RetryPolicy
from pshu.metrics import MetricsCollector
from pshu.ntp_sync import NTPClock, NTPState

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def build_router(config_path: str):
    cfg = load_config(config_path)
    routes = parse_routes(cfg)
    metrics = MetricsCollector()
    table = {}
    for route in routes:
        drv = route.driver
        policy = RetryPolicy(**drv.get("retry", {}))
        klass = PPPDriver if route.route_type == "ppp" else EthernetDeviceDriver
        driver = klass(
            name=drv["name"],
            host=drv["host"],
            port=drv["port"],
            protocol=drv.get("protocol", "udp"),
            metrics=metrics,
            retry_policy=policy,
        )
        table[route.prefix] = RouteEntry(prefix=route.prefix, driver=driver, route_type=route.route_type)
    ntp = parse_ntp(cfg)
    ntp_clock = None
    if ntp.get("enabled"):
        ntp_clock = NTPClock(NTPState(**{k:v for k,v in ntp.items() if k != "enabled"}))
    return OSCRouter(table), ntp_clock


async def main() -> None:
    router, ntp_clock = build_router("config.example.json")
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    ntp_task = None
    if ntp_clock:
        ntp_task = asyncio.create_task(ntp_clock.run(stop_event))
    transport, _ = await loop.create_datagram_endpoint(lambda: OSCGatewayProtocol(router, ntp_clock=ntp_clock), local_addr=("0.0.0.0", 8000))
    try:
        await asyncio.Event().wait()
    finally:
        stop_event.set()
        if ntp_task:
            await ntp_task
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
