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

## Что нужно для полного прогона Mininet
- Добавить python-скрипт топологии Mininet и запуск в CI с sudo/capabilities.
- Поднять echo/device endpoints в namespaces Mininet.
- Подключить экспорт метрик в файл/Prometheus и assert-порогов в тестах.


## NTP буфер и синхронизация
- Добавлен `pshu/ntp_sync.py` для фоновой NTP синхронизации часов (оценка offset + сглаживание EMA).
- В `OSCGatewayProtocol` добавлен NTP-aware clock и буфер `ntp_buffer_sec` для отложенного исполнения bundle с поправкой времени.


## Логирование для Mininet
- Включено детальное логирование RX/TX и маршрутизации: `ROUTE HIT/MISS`, `OSC MESSAGE`, `BUNDLE`, `TX PREP/OK/FAIL`.
- Логи пишутся в stdout и `logs/pshu.log` (rotating file).

## Topology для WSL2/Mininet
- Добавлен `topology.py` с `controller=None` и `switch=OVSBridge` (аналог `--controller=none --switch ovsbr --test pingall`), чтобы избежать 100% packet loss на шаге 13.
