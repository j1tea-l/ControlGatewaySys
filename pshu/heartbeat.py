import asyncio
import logging
import time
from typing import Dict, Optional, Callable, Awaitable

logger = logging.getLogger("PSHU_Heartbeat")

class DeviceState:
    def __init__(self, name: str, host: str, port: int, protocol: str, timeout_sec: float = 3.0):
        self.name = name
        self.host = host
        self.port = port
        self.protocol = protocol.lower()
        self.timeout_sec = timeout_sec
        
        self.last_seen = time.time()
        self.is_online = True
        self.reconnect_attempts = 0
        
        
        self.is_reconnecting = False
        
       
        self.on_reconnect: Optional[Callable[[], Awaitable[None]]] = None

    def mark_seen(self):
        self.last_seen = time.time()
        if not self.is_online:
            logger.info("СВЯЗЬ ВОССТАНОВЛЕНА: устройство %s (%s:%s)", self.name, self.host, self.port)
            self.is_online = True
            self.reconnect_attempts = 0
            self.is_reconnecting = False # Сбрасываем флаг при успешном коннекте

    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) <= self.timeout_sec


class HeartbeatManager:
    
    def __init__(self, check_interval: float = 1.0):
        self.check_interval = check_interval
        self.devices: Dict[str, DeviceState] = {}
        self._task: Optional[asyncio.Task] = None

    def register(self, name: str, host: str, port: int, protocol: str, timeout_sec: float = 3.0) -> DeviceState:
        dev = DeviceState(name, host, port, protocol, timeout_sec)
        self.devices[name] = dev
        logger.debug("Heartbeat: зарегистрировано устройство %s", name)
        return dev

    def mark_seen(self, name: str) -> None:
        if dev := self.devices.get(name):
            dev.mark_seen()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._monitor_loop())
            logger.info("Модуль Heartbeat запущен")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _monitor_loop(self) -> None:
        while True:
            for dev in self.devices.values():
                if not dev.is_alive():
                    if dev.is_online:
                        logger.warning("ОБРЫВ СВЯЗИ: устройство %s (%s:%s)", dev.name, dev.host, dev.port)
                        dev.is_online = False
                    
                    # Запускаем активное восстановление для TCP (ППП) только если процесс еще не запущен!
                    if dev.protocol == "tcp" and not dev.is_reconnecting:
                        asyncio.create_task(self._try_tcp_reconnect(dev))
                    
            await asyncio.sleep(self.check_interval)

    async def _try_tcp_reconnect(self, dev: DeviceState) -> None:
        dev.is_reconnecting = True  # Устанавливаем блокировку
        try:
            dev.reconnect_attempts += 1
            # Экспоненциальная задержка между попытками (до 30 секунд)
            backoff = min(30.0, 2 ** max(1, dev.reconnect_attempts - 1))
            await asyncio.sleep(backoff)
            
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(dev.host, dev.port),
                    timeout=1.0 # Жесткий таймаут на попытку, чтобы не вешать сокет
                )
                writer.close()
                await writer.wait_closed()
                
                # Если TCP handshake успешен, устройство физически в сети
                dev.mark_seen()
                
                # Запускаем callback для логического восстановления
                if dev.on_reconnect:
                    try:
                        await dev.on_reconnect()
                    except Exception as e:
                        logger.error("Ошибка при восстановлении %s: %s", dev.name, e)
            except Exception:
                pass  # Устройство все еще недоступно
                
        finally:
            # Обязательно снимаем блокировку в finally, чтобы даже в случае 
            # непредвиденной системной ошибки мы могли попробовать снова
            if not dev.is_online:
                dev.is_reconnecting = False
