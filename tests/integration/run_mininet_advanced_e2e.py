import json
import re
import time
from pathlib import Path

from mininet.net import Mininet
from mininet.node import OVSBridge
from mininet.link import TCLink

def _count_lines(path: str) -> str:
    # Заменяем многострочный Python-скрипт на простой однострочный bash-пайплайн,
    # чтобы избежать вывода символов PS2 ('>') от heredoc.
    return f"cat {path} 2>/dev/null | wc -l"

def _to_int_safe(v: str) -> int:
    # Безопасное извлечение первого найденного числа из строки, игнорируя мусор
    m = re.search(r"(\d+)", v)
    return int(m.group(1)) if m else 0

def run():
    repo = Path(__file__).resolve().parents[2]
    
    # Инициализация Mininet с поддержкой TCLink для контроля джиттера и задержек
    net = Mininet(controller=None, switch=OVSBridge, link=TCLink)
    s1 = net.addSwitch('s1')
    
    # Создание узлов (Топология: Звезда)
    client = net.addHost('client', ip='10.0.0.1/24')
    pshu = net.addHost('pshu', ip='10.0.0.2/24')
    dsp1 = net.addHost('dsp1', ip='10.0.0.3/24')
    ppp1 = net.addHost('ppp1', ip='10.0.0.4/24')

    # Подключение к L2 коммутатору с эмуляцией реальной сети (TCLink)
    # Настраиваем разные задержки и джиттер для проверки системы синхронизации
    net.addLink(client, s1, delay='5ms', jitter='2ms')
    net.addLink(pshu, s1, delay='2ms', jitter='1ms')
    net.addLink(dsp1, s1, delay='10ms', jitter='3ms')
    net.addLink(ppp1, s1, delay='15ms', jitter='5ms')

    net.start()
    
    # Прогрев сети (ARP resolution)
    net.pingAll()

    # Очистка старых артефактов
    pshu.cmd("rm -f /tmp/pshu.log /tmp/pshu.stdout")
    dsp1.cmd("rm -f /tmp/dsp.log /tmp/dsp_messages.jsonl")
    ppp1.cmd("rm -f /tmp/ppp.log /tmp/ppp_messages.jsonl /tmp/ppp_profile.json")
    client.cmd("rm -f /tmp/telemetry_sink.log /tmp/client_telemetry.jsonl /tmp/client_capture.pcap")

    # 1. Запуск эмуляторов устройств и телеметрии
    dsp1.cmd(f'cd {repo} && python3 scripts/mock_device_udp.py --port 9000 --out /tmp/dsp_messages.jsonl > /tmp/dsp.log 2>&1 &')
    ppp1.cmd(f'cd {repo} && python3 scripts/mock_ppp_tcp_device.py --port 9001 --out /tmp/ppp_messages.jsonl --profile-out /tmp/ppp_profile.json > /tmp/ppp.log 2>&1 &')
    client.cmd(f'cd {repo} && python3 tests/integration/telemetry_sink.py --port 9200 --out /tmp/client_telemetry.jsonl > /tmp/telemetry_sink.log 2>&1 &')

    # Захват трафика для анализа маршрутов
    client.cmd("tcpdump -i any -n -w /tmp/client_capture.pcap udp port 8000 or udp port 9100 or udp port 9200 &")

    # 2. Конфигурация и запуск ПШУ
    cfg = {
        "listen_ip": "0.0.0.0",
        "listen_port": 8000,
        "log_level": "INFO",
        "log_file": "/tmp/pshu.log",
        "ntp": {"enabled": False}, # В Mininet часы хоста едины, используем их
        "routes": [
            {"prefix": "/dsp1", "route_type": "local", "driver": {"name": "dsp1", "host": "10.0.0.3", "port": 9000, "protocol": "udp", "output_mode": "mapped_json"}},
            {"prefix": "/ppp1", "route_type": "ppp", "driver": {"name": "ppp1", "host": "10.0.0.4", "port": 9001, "protocol": "tcp", "output_mode": "osc_native", "ppp_profile": {"signing_key": "secret", "rules": {}}}}
        ],
        "telemetry": {
            "enabled": True, "listen_ip": "0.0.0.0", "transport": "tcp", "listen_port": 9100,
            "targets": [{"name": "client_app", "host": "10.0.0.1", "port": 9200}]
        }
    }
    (repo / 'config.e2e.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    pshu.cmd(f'cd {repo} && cp config.e2e.json config.example.json && python3 main.py > /tmp/pshu.stdout 2>&1 &')
    time.sleep(2.0)

    # 3. Тест №1: Проверка системы синхронизации (OSC Bundle scheduling)
    # Генерируем бандл с отложенным выполнением на 1.5 секунды
    sync_test_script = """
import time
from pythonosc.udp_client import SimpleUDPClient
from pythonosc.osc_bundle_builder import OscBundleBuilder
from pythonosc.osc_message_builder import OscMessageBuilder

c = SimpleUDPClient('10.0.0.2', 8000)
target_time = time.time() + 1.5

msg = OscMessageBuilder(address='/dsp1/sync_test')
msg.add_arg('delayed_execution')
msg.add_arg(target_time)

bundle = OscBundleBuilder(target_time)
bundle.add_content(msg.build())
c.send(bundle.build())
print(f"SENT BUNDLE: target_time={target_time}")
"""
    client.cmd(f"python3 -c \"{sync_test_script}\" > /tmp/sync_test.log")
    
    # Ожидаем срабатывания таймера бандла (+1.5с) + сетевые задержки
    time.sleep(2.5)

    # 4. Тест №2: Нагрузочное тестирование, телеметрия и проверка маршрутизации
    client.cmd(f'cd {repo} && python3 scripts/osc_loadgen.py --host 10.0.0.2 --port 8000 --count 10 --mode message --address /ppp1/volume')
    dsp1.cmd(f'cd {repo} && python3 scripts/telemetry_gen.py --host 10.0.0.2 --port 9100 --device dsp1 --count 10 --interval 0.05 > /dev/null 2>&1 &')
    time.sleep(1.0)

    # 5. Сбор метрик и анализ результатов
    pshu_log = pshu.cmd('cat /tmp/pshu.log 2>/dev/null || true')
    dsp_messages = dsp1.cmd('cat /tmp/dsp_messages.jsonl 2>/dev/null || true').strip().split('\n')
    
    # Анализ точности синхронизации
    sync_success = False
    sync_delta_ms = 0
    for line in dsp_messages:
        if 'sync_test' in line:
            rec = json.loads(line)
            # В payload находится JSON-структура драйвера
            payload = json.loads(rec['payload'])
            target_ts = payload['args'][1]
            actual_receive_ts = rec['ts']
            
            # Разница между временем, когда бандл ДОЛЖЕН был выполниться, 
            # и временем, когда устройство его РЕАЛЬНО получило.
            # Ожидаемая задержка: pshu -> s1 (2ms) + s1 -> dsp1 (10ms) = ~12ms + джиттер
            sync_delta_ms = (actual_receive_ts - target_ts) * 1000
            if 0 < sync_delta_ms < 50: # Учитываем сетевой TCLink delay
                sync_success = True
            break

    # Сбор статистики
    result = {
        'network_delays': {
            'client_to_pshu_link': '5ms + 2ms',
            'pshu_to_dsp_link': '2ms + 10ms'
        },
        'sync_system_test': {
            'success': sync_success,
            'network_and_processing_latency_ms': round(sync_delta_ms, 2),
            'log_evidence': [line for line in pshu_log.split('\n') if 'BUNDLE' in line]
        },
        'routing_and_telemetry': {
            'dsp_received_count': _to_int_safe(dsp1.cmd(_count_lines('/tmp/dsp_messages.jsonl'))),
            'ppp_received_count': _to_int_safe(ppp1.cmd(_count_lines('/tmp/ppp_messages.jsonl'))),
            'client_telemetry_count': _to_int_safe(client.cmd(_count_lines('/tmp/client_telemetry.jsonl')))
        }
    }

    (repo / 'mininet_advanced_report.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')

    # Очистка
    pshu.cmd('pkill -f "python3 main.py" || true')
    dsp1.cmd('pkill -f python || true')
    ppp1.cmd('pkill -f python || true')
    client.cmd('pkill -f tcpdump || true')
    net.stop()

    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    run()
