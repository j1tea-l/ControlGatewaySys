import asyncio
import time
import logging
from typing import Any, Dict, Tuple, Set

# Предполагается, что установлена библиотека python-osc: pip install python-osc
from pythonosc.osc_message import OscMessage
from pythonosc.osc_bundle import OscBundle

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("PSHU_Core")


# --- Интерфейсы драйверов (согласно п. 2.5) ---

class BaseDriver:
    """Базовый класс для всех драйверов устройств"""

    async def send_command(self, address: str, args: list) -> None:
        raise NotImplementedError


class EthernetDeviceDriver(BaseDriver):
    """Драйвер для устройств с поддержкой Ethernet (например, проприетарное API)"""

    def __init__(self, name: str, ip: str):
        self.name = name
        self.ip = ip

    async def send_command(self, address: str, args: list) -> None:
        # Здесь будет логика трансляции OSC в HTTP/TCP/UDP конкретного вендора
        logger.debug(f"[Ethernet Драйвер '{self.name}'] Трансляция {address} с аргументами {args} на {self.ip}")


class PPPDriver(BaseDriver):
    """Драйвер взаимодействия с Подсистемой Переходных Плат (ППП)"""

    def __init__(self, ppp_id: str, ppp_ip: str, ppp_port: int):
        self.ppp_id = ppp_id
        self.ppp_ip = ppp_ip
        self.ppp_port = ppp_port

    async def send_command(self, address: str, args: list) -> None:
        # ПШУ передает сырой OSC или промежуточный формат на ППП по TCP/UDP
        logger.debug(
            f"[ППП '{self.ppp_id}'] Отправка инкапсулированной команды {address} на {self.ppp_ip}:{self.ppp_port}")


# --- Подсистема маршрутизации (согласно п. 2.3) ---

class OSCRouter:
    def __init__(self, routing_table: Dict[str, BaseDriver]):
        self.routing_table = routing_table

    async def route(self, address: str, args: list, timestamp: float) -> None:
        """Поиск драйвера по префиксу адреса и передача команды"""
        # Сортируем ключи по убыванию длины для поиска наиболее точного совпадения (Longest Prefix Match)
        for prefix in sorted(self.routing_table.keys(), key=len, reverse=True):
            if address.startswith(prefix):
                driver = self.routing_table[prefix]
                try:
                    await driver.send_command(address, args)
                except Exception as e:
                    logger.error(f"Ошибка при отправке команды драйверу {prefix}: {e}")
                return

        logger.warning(f"Маршрут не найден для адреса: {address}")


# --- Ядро шлюза управления (согласно п. 2.2) ---

class OSCGatewayProtocol(asyncio.DatagramProtocol):
    """UDP протокол для обработки входящего OSC-трафика"""

    def __init__(self, router: OSCRouter):
        self.router = router
        self.time_tolerance = 0.001  # Допуск синхронизации (1 мс)
        self.background_tasks: Set[asyncio.Task] = set()  # Защита от Garbage Collector'а

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport
        peername = transport.get_extra_info('peername')
        logger.info(f"Слушатель ПШУ запущен. Ожидание данных...")

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        """Срабатывает мгновенно при получении UDP пакета"""
        # Запускаем асинхронную обработку, не блокируя цикл событий UDP
        task = asyncio.create_task(self.process_packet(data, addr))
        self._register_task(task)

    async def process_packet(self, data: bytes, addr: Tuple[str, int]) -> None:
        """Первичный разбор пакета (Одиночное сообщение или Бандл)"""
        try:
            if data.startswith(b'#bundle'):
                bundle = OscBundle(data)
                await self.handle_bundle(bundle)
            elif data.startswith(b'/'):
                message = OscMessage(data)
                # Маркировка временем приема по локальным часам (NTP)
                await self.router.route(message.address, message.params, time.time())
            else:
                logger.warning(f"Получен неизвестный формат пакета от {addr}")
        except Exception as e:
            logger.error(f"Ошибка парсинга датаграммы от {addr}: {e}")

    async def handle_bundle(self, bundle: OscBundle) -> None:
        """Обработка временных меток бандла (Модуль синхронизации)"""
        current_time = time.time()
        bundle_time = bundle.timestamp

        # Если время выполнения наступило (с учетом допуска)
        if bundle_time <= current_time + self.time_tolerance:
            for content in bundle:
                if isinstance(content, OscMessage):
                    await self.router.route(content.address, content.params, bundle_time)
                elif isinstance(content, OscBundle):
                    await self.handle_bundle(content)  # Рекурсивный разбор вложенных бандлов
        else:
            # Время в будущем: помещаем в буфер отложенного выполнения
            delay = bundle_time - current_time
            logger.debug(f"Бандл отложен на {delay:.4f} сек.")
            task = asyncio.create_task(self.delayed_execution(bundle, delay))
            self._register_task(task)

    async def delayed_execution(self, bundle: OscBundle, delay: float) -> None:
        """Ожидание и последующее выполнение содержимого бандла"""
        await asyncio.sleep(delay)
        # После пробуждения время бандла считается наступившим
        await self.handle_bundle(bundle)

    def _register_task(self, task: asyncio.Task) -> None:
        """Сохраняет сильную ссылку на задачу, пока она не завершится"""
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)


# --- Точка входа ---

async def main():
    # 1. Инициализация таблицы маршрутизации (в реальности загружается из JSON)
    routing_table = {
        "/device/amp/": EthernetDeviceDriver(name="Усилитель_Зона1", ip="192.168.1.15"),
        "/device/mixer/": EthernetDeviceDriver(name="DSP_Матрица", ip="192.168.1.20"),
        "/serial/projector/": PPPDriver(ppp_id="PPP_Зал1", ppp_ip="192.168.1.100", ppp_port=5000),
    }

    # 2. Инициализация модулей
    router = OSCRouter(routing_table)
    loop = asyncio.get_running_loop()

    # 3. Запуск UDP сервера шлюза (порт 8000)
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: OSCGatewayProtocol(router),
        local_addr=('0.0.0.0', 8000)
    )

    try:
        # Шлюз работает бесконечно, пока не будет прерван
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Остановка шлюза...")
    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main()) # Раскомментировать для запуска
    pass