# ControlGatewaySys / ПШУ

## Функциональные блоки репозитория
- `pshu/core.py` — OSC server, bundle scheduling, router.
- `pshu/drivers.py` — реальные TCP/UDP клиенты, retry/timeout/reconnect политика.
- `pshu/config.py` — загрузка конфигурации JSON/YAML.
- `pshu/metrics.py` — latency/loss/heartbeat/recovery метрики.
- `scripts/osc_loadgen.py` — генератор OSC-нагрузки (message/bundle).
- `tests/integration/test_mininet_plan.md` — сценарий интеграционного стенда Mininet.
- `.github/workflows/integration-mininet.yml` — CI-джоб integration-mininet.

## Что реализовано
- Реальная сетевая отправка команд через UDP/TCP клиенты с timeout/retry/backoff.
- Асинхронный роутинг OSC сообщений/бандлов по longest prefix.
- Конфигурирование роутов и драйверов из внешнего JSON/YAML.
- Сбор базовых метрик p95/p99/loss/recovery.

## NTP буфер и синхронизация
- Добавлен `pshu/ntp_sync.py` для фоновой NTP синхронизации часов (оценка offset + сглаживание EMA).
- В `OSCGatewayProtocol` добавлен NTP-aware clock и буфер `ntp_buffer_sec` для отложенного исполнения bundle с поправкой времени.

## Логирование для Mininet
- Включено детальное логирование RX/TX и маршрутизации: `ROUTE HIT/MISS`, `OSC MESSAGE`, `BUNDLE`, `TX PREP/OK/FAIL`.
- Логи пишутся в stdout и `logs/pshu.log` (rotating file).

## Topology для WSL2/Mininet
- Добавлен `topology.py` с `controller=None` и `switch=OVSBridge` (аналог `--controller=none --switch ovsbr --test pingall`), чтобы избежать 100% packet loss на шаге 13.

## Автоинтеграция Mininet
- Добавлен `tests/integration/mininet_topology.py` (smoke-run с поднятием endpoint на `dsp1`, запуском ПШУ на `pshu`, и loadgen на `controller`).
- Добавлен `tests/integration/test_metrics_thresholds.py` с assert-порогами метрик.
- CI workflow запускает Mininet smoke через `sudo` и затем pytest-порогов.

## Единый файл запуска Mininet-тестов
- Используйте `tests/integration/run_mininet_e2e.py` — он **одним запуском** поднимает topology, endpoints (`dsp1`, `ppp1`), стартует ПШУ, отправляет трафик, проверяет маршрутизацию/коммутацию и парсит логи (`ROUTE HIT`, `TX OK`, и т.д.).
- По завершении формирует отчёт `mininet_e2e_report.json` с метриками доставки и парсингом логов.

---

## Подробная инструкция: зависимости и запуск Mininet-тестирования

Ниже — пошаговый runbook, который закрывает типовую ошибку запуска вида:
`ModuleNotFoundError: No module named 'pythonosc'`.

### 1) Системные зависимости (Ubuntu/Debian)

> Требуется root/sudo, потому что Mininet создает network namespaces и virtual links.

```bash
sudo apt-get update
sudo apt-get install -y \
  python3 python3-pip python3-venv \
  mininet openvswitch-switch \
  iproute2 iputils-ping net-tools
```

Проверка:
```bash
python3 --version
mn --version
ovs-vsctl --version
```

### 2) Python-зависимости проекта

`main.py` и `scripts/osc_loadgen.py` используют пакет `python-osc` (импорт `pythonosc.*`).
Если его нет — ПШУ в namespace не поднимется.

Рекомендуемый способ — через virtualenv:

```bash
cd /home/user/project
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install python-osc PyYAML pytest mininet
```

Минимум для устранения вашей ошибки:
```bash
python -m pip install python-osc
```

Быстрая проверка импорта:
```bash
python - <<'PY'
from pythonosc.udp_client import SimpleUDPClient
from pythonosc.osc_bundle import OscBundle
print('python-osc import OK')
PY
```

### 3) Подготовка конфигурации перед E2E

E2E-скрипт сам создаёт `config.e2e.json` и копирует его в `config.example.json`,
чтобы `main.py` стартовал с Mininet-адресами (`10.0.0.x`) внутри тестовой топологии.

Отдельно вручную ничего править не нужно, но важно запускать E2E из корня репозитория.

### 4) Запуск полного Mininet E2E

Из корня репозитория:

```bash
cd /home/user/project
sudo -E python3 tests/integration/run_mininet_e2e.py
```

Что делает скрипт:
1. Поднимает Mininet с `controller=None` и `OVSBridge`.
2. Создаёт хосты: `controller`, `pshu`, `dsp1`, `ppp1`.
3. На `dsp1`/`ppp1` запускает UDP mock endpoints.
4. На `pshu` запускает `python3 main.py`.
5. С `controller` шлёт OSC-трафик (`scripts/osc_loadgen.py` + direct `SimpleUDPClient`).
6. Проверяет:
   - ping drop (`pingAll`) = 0,
   - факт доставки в `dsp1` и `ppp1`,
   - наличие `ROUTE HIT` и `TX OK` в логах.
7. Пишет отчёт `mininet_e2e_report.json`.

### 5) Где смотреть диагностику при падении

Если ПШУ не стартует или E2E падает:

- Итоговый файл: `mininet_e2e_report.json`.
- Лог ПШУ в namespace: `/tmp/pshu.stdout` и `/tmp/pshu.log`.
- Логи mock endpoints:
  - `/tmp/dsp.log`
  - `/tmp/ppp.log`
- Счётчики полученных команд:
  - `/tmp/dsp_messages.jsonl`
  - `/tmp/ppp_messages.jsonl`

Типовые причины:
- не установлен `python-osc`;
- Mininet/OVS не установлены;
- запуск не от root/sudo;
- в системе остались «хвосты» Mininet после аварийного завершения.

Очистка Mininet:
```bash
sudo mn -c
```

### 6) Запуск smoke-сценария

```bash
cd /home/user/project
sudo -E python3 tests/integration/mininet_topology.py
```

Этот сценарий легче E2E: поднимает базовую топологию, прогоняет loadgen и печатает хвосты логов.

### 7) Проверка метрик (post-check)

Если после прогона сформирован `metrics.prom`, можно проверить пороги:

```bash
cd /home/user/project
python3 -m pytest -q tests/integration/test_metrics_thresholds.py
```

### 8) Рекомендации для CI и namespace-окружений

- Используйте образ/runner, где уже есть Mininet и OVS.
- Запускайте интеграцию в privileged-окружении.
- Перед стартом теста делайте `mn -c`.
- Всегда проверяйте импорт `python-osc` до запуска `main.py`.

Мини-проверка перед стартом:
```bash
python3 - <<'PY'
import mininet
import pythonosc
print('deps OK')
PY
```


## Телеметрия: OSC over UDP (общий случай)
- Телеметрия от устройств (DSP, ППП и любые другие) принимается ПШУ как **OSC over UDP** на `telemetry.listen_ip:telemetry.listen_port`.
- ПШУ не подменяет payload и пересылает исходный OSC datagram на контроллеры из `telemetry.targets`.
- Поддерживаются OSC-message и OSC-bundle; в логах фиксируются `TELEMETRY RX` и `TELEMETRY FWD`.

### One-file E2E запуск
Для полного сценария (топология + команды + телеметрия) используется **один файл**:

```bash
sudo -E python3 tests/integration/run_mininet_e2e.py
```

Скрипт сам:
- поднимает Mininet;
- стартует ПШУ;
- генерирует OSC-команды и OSC-телеметрию;
- проверяет доставку на устройства и на telemetry sink контроллера;
- сохраняет отчёт в `mininet_e2e_report.json`.

