import json
import re
import time
from pathlib import Path

from mininet.net import Mininet
from mininet.node import OVSBridge
from mininet.link import TCLink

def _count_lines(path: str) -> str:
    return f"cat {path} 2>/dev/null | wc -l"

def _to_int_safe(v: str) -> int:
    m = re.search(r"(\d+)", v)
    return int(m.group(1)) if m else 0

def run():
    repo = Path(__file__).resolve().parents[2]
    
    print("\n[1/6] Инициализация Mininet и топологии 'Звезда' с TCLink...")
    net = Mininet(controller=None, switch=OVSBridge, link=TCLink)
    s1 = net.addSwitch('s1')
    
    client = net.addHost('client', ip='10.0.0.1/24')
    pshu = net.addHost('pshu', ip='10.0.0.2/24')
    dsp1 = net.addHost('dsp1', ip='10.0.0.3/24')
    ppp1 = net.addHost('ppp1', ip='10.0.0.4/24')

    net.addLink(client, s1, delay='5ms', jitter='2ms')
    net.addLink(pshu, s1, delay='2ms', jitter='1ms')
    net.addLink(dsp1, s1, delay='10ms', jitter='3ms')
    net.addLink(ppp1, s1, delay='15ms', jitter='5ms')

    net.start()
    net.pingAll()

    pshu.cmd("rm -f /tmp/pshu.log /tmp/pshu.stdout")
    dsp1.cmd("rm -f /tmp/dsp.log /tmp/dsp_messages.jsonl")
    ppp1.cmd("rm -f /tmp/ppp.log /tmp/ppp_messages.jsonl /tmp/ppp_profile.json /tmp/ppp_recovery.log")
    client.cmd("rm -f /tmp/telemetry_sink.log /tmp/client_telemetry.jsonl /tmp/client_capture.pcap")

    print("[2/6] Запуск эмуляторов устройств и захвата трафика...")
    dsp1.cmd(f'cd {repo} && python3 scripts/mock_device_udp.py --port 9000 --out /tmp/dsp_messages.jsonl > /tmp/dsp.log 2>&1 &')
    ppp1.cmd(f'cd {repo} && python3 scripts/mock_ppp_tcp_device.py --port 9001 --out /tmp/ppp_messages.jsonl --profile-out /tmp/ppp_profile.json > /tmp/ppp.log 2>&1 &')
    client.cmd(f'cd {repo} && python3 tests/integration/telemetry_sink.py --port 9200 --out /tmp/client_telemetry.jsonl > /tmp/telemetry_sink.log 2>&1 &')
    client.cmd("tcpdump -i any -n -w /tmp/client_capture.pcap udp port 8000 or udp port 9100 or udp port 9200 > /dev/null 2>&1 &")

    print("[3/6] Запуск подсистемы шлюза управления (ПШУ)...")
    cfg = {
        "listen_ip": "0.0.0.0",
        "listen_port": 8000,
        "log_level": "INFO",
        "log_file": "/tmp/pshu.log",
        "ntp": {"enabled": False},
        "routes": [
            {"prefix": "/dsp1", "route_type": "local", "driver": {"name": "dsp1", "host": "10.0.0.3", "port": 9000, "protocol": "udp", "output_mode": "mapped_json"}},
            {"prefix": "/ppp1", "route_type": "ppp", "driver": {"name": "ppp1", "host": "10.0.0.4", "port": 9001, "protocol": "tcp", "output_mode": "osc_native", "ppp_profile": {"signing_key": "secret", "rules": {"mode": "test"}}}}
        ],
        "telemetry": {
            "enabled": True, "listen_ip": "0.0.0.0", "transport": "udp", "listen_port": 9100,
            "targets": [{"name": "client_app", "host": "10.0.0.1", "port": 9200}]
        }
    }
    (repo / 'config.e2e.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    pshu.cmd(f'cd {repo} && cp config.e2e.json config.example.json && python3 main.py > /tmp/pshu.stdout 2>&1 &')
    time.sleep(2.0)

    print("[4/6] Тест №1 и №2: Синхронизация (OSC Bundle) и Телеметрия...")
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
"""
    client.cmd(f"python3 -c \"{sync_test_script}\" > /tmp/sync_test.log")
    time.sleep(2.5) 

    client.cmd(f'cd {repo} && python3 scripts/osc_loadgen.py --host 10.0.0.2 --port 8000 --count 10 --mode message --address /ppp1/volume')
    dsp1.cmd(f'cd {repo} && python3 scripts/telemetry_gen.py --host 10.0.0.2 --port 9100 --device dsp1 --count 10 --interval 0.05 > /dev/null 2>&1 &')
    time.sleep(1.0)

    print("[5/6] Тест №3: Обрыв связи (Heartbeat) и автовосстановление ППП...")
    # Имитация потери питания ESP32 (жестко убиваем процесс)
    ppp1.cmd('pkill -f "mock_ppp_tcp_device.py" || true')
    print("      - Эмулятор ППП выключен (Имитация потери питания). Ждем детекцию обрыва...")
    time.sleep(4.0) # Даем Heartbeat время заметить обрыв (timeout = 3.0s)

    # Удаляем старый файл профиля на хосте ППП, чтобы проверить его повторное появление
    ppp1.cmd("rm -f /tmp/ppp_profile.json")

    # Включаем ESP32 обратно
    print("      - Эмулятор ППП включен обратно. Ждем TCP-реконнекта...")
    ppp1.cmd(f'cd {repo} && python3 scripts/mock_ppp_tcp_device.py --port 9001 --out /tmp/ppp_messages.jsonl --profile-out /tmp/ppp_profile.json > /tmp/ppp_recovery.log 2>&1 &')
    time.sleep(4.0) # Даем модулю Heartbeat время на установку TCP сессии

    # Отправляем тестовую команду после восстановления
    client.cmd(f'cd {repo} && python3 scripts/osc_loadgen.py --host 10.0.0.2 --port 8000 --count 1 --mode message --address /ppp1/after_recovery')
    time.sleep(1.0)

    print("[6/6] Сбор логов и расчет метрик...")
    pshu_log = pshu.cmd('cat /tmp/pshu.log 2>/dev/null || true')
    dsp_messages = dsp1.cmd('cat /tmp/dsp_messages.jsonl 2>/dev/null || true').strip().split('\n')
    ppp_messages = ppp1.cmd('cat /tmp/ppp_messages.jsonl 2>/dev/null || true')
    
    sync_success = False
    sync_delta_ms = 0.0
    for line in dsp_messages:
        if 'sync_test' in line:
            rec = json.loads(line)
            payload = json.loads(rec['payload'])
            target_ts = payload['args'][1]
            actual_receive_ts = rec['ts']
            sync_delta_ms = (actual_receive_ts - target_ts) * 1000
            if -100 < sync_delta_ms < 3000: 
                sync_success = True
            break

    dsp_count = _to_int_safe(dsp1.cmd(_count_lines('/tmp/dsp_messages.jsonl')))
    telem_count = _to_int_safe(client.cmd(_count_lines('/tmp/client_telemetry.jsonl')))

    # Анализ результатов Heartbeat
    heartbeat_dropped = 'ОБРЫВ СВЯЗИ' in pshu_log
    heartbeat_recovered = 'СВЯЗЬ ВОССТАНОВЛЕНА' in pshu_log
    profile_pushed_again = _to_int_safe(ppp1.cmd("cat /tmp/ppp_profile.json 2>/dev/null | wc -l")) > 0
    recovery_cmd_delivered = 'after_recovery' in ppp_messages

    # Красивый вывод метрик
    print("\n" + "="*60)
    print(" 📊 ОТЧЕТ О ТЕСТИРОВАНИИ ПШУ (Mininet Advanced E2E)")
    print("="*60)
    print("🌐 Параметры эмулируемой сети (TCLink):")
    print("  - Client <-> Switch : delay=5ms, jitter=2ms")
    print("  - PSHU <-> Switch   : delay=2ms, jitter=1ms")
    print("  - DSP1 <-> Switch   : delay=10ms, jitter=3ms")
    print("  - PPP1 <-> Switch   : delay=15ms, jitter=5ms\n")
    
    print("⏱️  Тест системы синхронизации (OSC Bundle +1.5 сек):")
    print(f"  - Статус отработки таймера    : {'УСПЕШНО ✅' if sync_success else 'ПРОВАЛ ❌'}")
    print(f"  - Транспортная задержка (сеть): {sync_delta_ms:.2f} мс\n")
    
    print("🔄  Тест автоматического восстановления (Heartbeat):")
    print(f"  - Детекция обрыва связи       : {'УСПЕШНО ✅' if heartbeat_dropped else 'ПРОВАЛ ❌'}")
    print(f"  - Авто-переподключение (TCP)  : {'УСПЕШНО ✅' if heartbeat_recovered else 'ПРОВАЛ ❌'}")
    print(f"  - Повторная отправка профиля  : {'УСПЕШНО ✅' if profile_pushed_again else 'ПРОВАЛ ❌'}")
    print(f"  - Доставка команды после сбоя : {'УСПЕШНО ✅' if recovery_cmd_delivered else 'ПРОВАЛ ❌'}\n")

    print("📡 Маршрутизация и Телеметрия:")
    print(f"  - Команд доставлено на DSP    : {dsp_count}")
    print(f"  - Телеметрии получено клиентом: {telem_count}")
    print("="*60 + "\n")

    result = {
        'network_delays': {'client_to_pshu_link': '5ms+2ms', 'pshu_to_dsp_link': '2ms+10ms'},
        'sync_system_test': {'success': sync_success, 'latency_ms': round(sync_delta_ms, 2)},
        'heartbeat_test': {
            'dropped_detected': heartbeat_dropped, 
            'recovered': heartbeat_recovered,
            'profile_repushed': profile_pushed_again,
            'command_delivered': recovery_cmd_delivered
        },
        'routing_and_telemetry': {'dsp_count': dsp_count, 'telem_count': telem_count}
    }
    (repo / 'mininet_advanced_report.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')

    # БЕЗОПАСНАЯ ОЧИСТКА
    pshu.cmd('pkill -f "python3 main.py" || true')
    dsp1.cmd('pkill -f "mock_device_udp.py" || true')
    ppp1.cmd('pkill -f "mock_ppp_tcp_device.py" || true')
    dsp1.cmd('pkill -f "telemetry_gen.py" || true')
    client.cmd('pkill -f "telemetry_sink.py" || true')
    client.cmd('pkill -f tcpdump || true')
    net.stop()

if __name__ == '__main__':
    run()
