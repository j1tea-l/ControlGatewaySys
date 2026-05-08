# Codex Specification — ПШУ (Подсистема шлюза управления)

## Название проекта

Подсистема шлюза управления (ПШУ) сетевой инфокоммуникационной платформы для профессиональных аудиосистем.

---

# 1. Назначение проекта

Разработать программный прототип ПШУ на Python, обеспечивающий:

* приём OSC-команд;
* маршрутизацию сообщений;
* трансляцию команд устройствам;
* взаимодействие с подсистемой переходных плат (ППП);
* сбор и отправку телеметрии;
* асинхронную обработку сетевых событий;
* поддержку синхронизации времени и OSC-bundle.

Система должна обеспечивать унифицированное управление аудиоустройствами с различными интерфейсами.

---

# 2. Технологический стек

## Язык

Python 3.11+

## Основные библиотеки

* asyncio
* python-osc
* aiohttp (опционально)
* logging
* json
* dataclasses
* typing

## Среда выполнения

* Raspberry Pi OS Lite
* Raspberry Pi 4 Model B

---

# 3. Архитектура системы

## Основные модули

### 3.1 OSC Server

Отвечает за:

* приём UDP OSC-пакетов;
* обработку OSC-message и OSC-bundle;
* передачу сообщений в Router.

### 3.2 Synchronization Module

Функции:

* обработка timestamp у OSC-bundle;
* буферизация команд;
* отложенное выполнение через asyncio timers;
* поддержка NTP-синхронизации.

### 3.3 Router

Функции:

* поиск драйвера по OSC-адресу;
* маршрутизация команд;
* обработка ошибок маршрутизации.

Поддержка:

* hierarchical OSC addresses;
* longest prefix match.

Примеры адресов:

* /device/amp/gain
* /dev/mixer/channel1/volume
* /dev/amp/status/temp

### 3.4 Driver Manager

Функции:

* регистрация драйверов;
* загрузка конфигурации;
* вызов driver.send_command().

### 3.5 PPP Transport Module

Подсистема взаимодействия с ППП.

Функции:

* TCP/UDP взаимодействие;
* передача команд;
* heartbeat;
* reconnect.

### 3.6 Telemetry Module

Функции:

* приём телеметрии;
* кольцевой буфер;
* подписка клиентов;
* периодическая отправка.

### 3.7 Logging System

Функции:

* журналирование ошибок;
* журналирование команд;
* журналирование сетевых событий.

---

# 4. Требования к функциональности

## 4.1 Приём OSC

Система должна:

* принимать UDP OSC-пакеты;
* поддерживать OSC 1.1;
* поддерживать bundle;
* валидировать сообщения.

Некорректные пакеты:

* игнорировать;
* логировать.

---

## 4.2 Обработка OSC-bundle

Алгоритм:

1. Проверка timestamp.
2. Если timestamp <= current_time:

   * немедленная обработка.
3. Иначе:

   * помещение в buffer queue;
   * выполнение по timer.

---

## 4.3 Маршрутизация

Router должен:

* искать наиболее специфичный route;
* вызывать локальный driver;
* либо пересылать пакет в ППП.

Если route не найден:

* сформировать OSC error response.

---

## 4.4 Драйверный интерфейс

Создать базовый интерфейс:

```python
class BaseDriver:
    async def send_command(self, address: str, args: list):
        raise NotImplementedError

    async def get_telemetry(self):
        raise NotImplementedError
```

Поддержать:

* Ethernet devices;
* PPP devices.

---

## 4.5 Телеметрия

Система должна:

* собирать данные от драйверов;
* преобразовывать их в OSC;
* отправлять подписчикам.

Пример:

```text
/dev/amp/status/temp
```

---

## 4.6 Heartbeat

ПШУ должен:

* периодически отправлять heartbeat;
* контролировать timeout;
* автоматически восстанавливать соединение.

---

# 5. Нефункциональные требования

## Производительность

* задержка обработки ≤ 10 мс;
* поддержка минимум 32 устройств.

## Асинхронность

Все операции должны использовать asyncio.

Запрещено:

* blocking socket I/O;
* time.sleep().

---

# 6. Структура проекта

```text
pshu/
│
├── main.py
├── config/
│   └── routes.json
│
├── core/
│   ├── osc_server.py
│   ├── router.py
│   ├── sync_manager.py
│   ├── telemetry.py
│   ├── transport.py
│   └── heartbeat.py
│
├── drivers/
│   ├── base_driver.py
│   ├── ethernet_driver.py
│   └── ppp_driver.py
│
├── utils/
│   ├── logger.py
│   └── ntp.py
│
├── tests/
│   ├── test_router.py
│   ├── test_osc.py
│   └── test_transport.py
│
└── requirements.txt
```

---

# 7. Формат routes.json

```json
{
  "/dev/amp": "ethernet_driver",
  "/dev/serial": "ppp_driver"
}
```

---

# 8. Алгоритм обработки сообщения

```text
UDP Packet
    ↓
OSC Parser
    ↓
Bundle Check
    ↓
Synchronization Module
    ↓
Router
    ↓
Driver / PPP
    ↓
Telemetry
```

---

# 9. Требования к коду

## Стиль

* PEP8
* type hints
* docstrings
* async/await

## Архитектура

* SOLID
* dependency injection
* modular design

---

# 10. Требования к тестированию

Необходимо реализовать:

* unit tests;
* integration tests;
* эмуляцию ППП;
* тесты потери соединения;
* тесты восстановления связи.

Инструменты:

* pytest
* pytest-asyncio

---

# 11. Пример жизненного цикла команды

1. Клиент отправляет OSC message.
2. OSC Server принимает пакет.
3. Router определяет driver.
4. Driver преобразует команду.
5. Команда отправляется устройству.
6. Устройство отвечает.
7. Telemetry module публикует данные.

---

# 12. Требования к логированию

Логировать:

* входящие OSC;
* ошибки;
* reconnect;
* heartbeat timeout;
* telemetry events.

Формат:

```text
[timestamp] [module] [level] message
```

---

# 13. Дополнительные требования

## Поддержка runtime reload

Router должен поддерживать перезагрузку routes.json без остановки системы.

## Конфигурируемость

Все параметры должны храниться в config files.

## Расширяемость

Добавление нового драйвера не должно требовать изменения ядра.

---

# 14. Что должен сгенерировать Codex

Codex должен:

1. Создать полный Python-проект.
2. Реализовать асинхронный OSC server.
3. Реализовать Router.
4. Реализовать Driver API.
5. Реализовать Telemetry subsystem.
6. Реализовать PPP transport.
7. Реализовать heartbeat/reconnect.
8. Добавить unit tests.
9. Создать requirements.txt.
10. Добавить README.md.

---

# 15. Критерии готовности

Проект считается завершённым если:

* система принимает OSC;
* корректно маршрутизирует команды;
* поддерживает минимум 32 устройства;
* работает асинхронно;
* проходит тесты;
* корректно обрабатывает reconnect;
* поддерживает telemetry;
* код документирован.
