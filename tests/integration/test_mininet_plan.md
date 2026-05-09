# Mininet integration-test стенд

## Топология
`Controller -> PSHU -> PPP -> Devices`

## Автопроверки
1. Доставка OSC команд до device echo server.
2. Измерение latency p95/p99.
3. Packet loss при отключении линка.
4. Heartbeat и recovery time после restore.

## Шаги
- Поднять mininet topology script.
- Запустить `main.py` в node PSHU.
- Запустить `scripts/osc_loadgen.py` из Controller.
- Собрать метрики из `MetricsCollector.snapshot()`.
