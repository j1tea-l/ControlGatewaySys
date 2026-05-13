import asyncio
import contextlib
import logging

from pshu.config import load_config, parse_routes, parse_ntp
from pshu.core import OSCGatewayProtocol, OSCRouter, RouteEntry
from pshu.drivers import EthernetDeviceDriver, PPPDriver, RetryPolicy
from pshu.metrics import MetricsCollector
from pshu.ntp_sync import NTPClock, NTPState
from pshu.rtc_clock import RPIRTCClock, RTCState, is_raspberry_pi
from pshu.logging_setup import setup_logging
from pshu.telemetry import TelemetryForwardTarget, start_telemetry_bridge
from pshu.heartbeat import HeartbeatManager

logger = logging.getLogger(__name__)

def build_router(config_path: str):
    cfg = load_config(config_path)
    setup_logging(cfg.get("log_file", "logs/pshu.log"), cfg.get("log_level", "INFO"))
    
    routes = parse_routes(cfg)
    metrics = MetricsCollector()
    heartbeat_mgr = HeartbeatManager(check_interval=1.0)
    table = {}
    
    for route in routes:
        drv = route.driver
        policy = RetryPolicy(**drv.get("retry", {}))
        klass = PPPDriver if route.route_type == "ppp" else EthernetDeviceDriver
        driver_kwargs = {
            "name": drv["name"],
            "host": drv["host"],
            "port": drv["port"],
            "protocol": drv.get("protocol", "udp"),
            "metrics": metrics,
            "retry_policy": policy,
            "route_prefix": route.prefix,
            "output_mode": drv.get("output_mode", "json"),
            "mapping_rules": drv.get("mapping_rules", {}),
            "heartbeat": heartbeat_mgr, # Интеграция Heartbeat в драйвер
        }
        
        if klass is PPPDriver:
            driver_kwargs["ppp_profile"] = drv.get("ppp_profile", {})
            
        driver = klass(**driver_kwargs)
        table[route.prefix] = RouteEntry(prefix=route.prefix, driver=driver, route_type=route.route_type)
        
    ntp = parse_ntp(cfg)
    ntp_clock = None
    if ntp.get("enabled"):
        if ntp.get("use_rpi_rtc") and is_raspberry_pi():
            ntp_clock = RPIRTCClock(
                RTCState(
                    poll_interval_sec=ntp.get("poll_interval_sec", 30.0),
                    timeout_sec=ntp.get("timeout_sec", 1.0),
                    hwclock_bin=ntp.get("hwclock_bin", "hwclock"),
                )
            )
            logger.info("Clock source selected: RPi RTC")
        else:
            ntp_clock = NTPClock(NTPState(**{k: v for k, v in ntp.items() if k not in {"enabled", "use_rpi_rtc", "hwclock_bin"}}))
            logger.info("Clock source selected: NTP server=%s", ntp.get("server"))
            
    return OSCRouter(table), ntp_clock, metrics, heartbeat_mgr

async def main() -> None:
    router, ntp_clock, metrics, heartbeat = build_router("config.example.json")
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    
    ntp_task = None
    if ntp_clock:
        ntp_task = asyncio.create_task(ntp_clock.run(stop_event))
        
    cfg = load_config("config.example.json")
    listen_ip = cfg.get("listen_ip", "0.0.0.0")
    listen_port = cfg.get("listen_port", 8000)
    
    transport, _ = await loop.create_datagram_endpoint(
        lambda: OSCGatewayProtocol(router, ntp_clock=ntp_clock), 
        local_addr=(listen_ip, listen_port)
    )

    telemetry_cfg = cfg.get("telemetry", {})
    telemetry_transport = None
    if telemetry_cfg.get("enabled", False):
        targets = [TelemetryForwardTarget(**t) for t in telemetry_cfg.get("targets", [])]
        telemetry_transport = await start_telemetry_bridge(
            telemetry_cfg.get("listen_ip", "0.0.0.0"),
            telemetry_cfg.get("listen_port", 9100),
            targets,
            transport=telemetry_cfg.get("transport", "udp"),
            heartbeat=heartbeat # Интеграция Heartbeat в мост телеметрии
        )
        
    # Запуск фонового мониторинга соединений
    await heartbeat.start()

    try:
        await asyncio.Event().wait()
    finally:
        stop_event.set()
        await heartbeat.stop()
        
        if ntp_task:
            await ntp_task
            
        transport.close()
        
        if telemetry_transport:
            telemetry_transport.close()
            if hasattr(telemetry_transport, "wait_closed"):
                await telemetry_transport.wait_closed()
                
        with contextlib.suppress(Exception):
            metrics.export_prometheus("metrics.prom")


if __name__ == "__main__":
    asyncio.run(main())
