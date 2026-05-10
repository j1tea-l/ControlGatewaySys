from mininet.net import Mininet
from mininet.node import OVSBridge


def build_net():
    net = Mininet(controller=None, switch=OVSBridge)
    s1 = net.addSwitch('s1')
    controller = net.addHost('controller')
    pshu = net.addHost('pshu')
    dsp1 = net.addHost('dsp1')
    ppp1 = net.addHost('ppp1')

    for host in (controller, pshu, dsp1, ppp1):
        net.addLink(host, s1)
    return net, controller, pshu, dsp1, ppp1


def run_smoke():
    net, controller, pshu, dsp1, ppp1 = build_net()
    net.start()
    dropped = net.pingAll()
    print(f"pingAll dropped={dropped}")

    controller.cmd('python3 tests/integration/telemetry_sink.py --port 9200 --out /tmp/controller_telemetry.jsonl > /tmp/telemetry_sink.log 2>&1 &')
    pshu.cmd('python3 main.py > /tmp/pshu.log 2>&1 &')
    dsp1.cmd('python3 scripts/telemetry_gen.py --host 10.0.0.2 --port 9100 --device dsp1 --count 10 --interval 0.05 > /tmp/dsp_telem.log 2>&1')
    ppp1.cmd('python3 scripts/telemetry_gen.py --host 10.0.0.2 --port 9100 --device ppp1 --count 10 --interval 0.05 > /tmp/ppp_telem.log 2>&1')

    print(pshu.cmd('tail -n 30 /tmp/pshu.log'))
    print(controller.cmd('tail -n 30 /tmp/telemetry_sink.log'))
    print(controller.cmd('wc -l /tmp/controller_telemetry.jsonl || true'))

    controller.cmd('pkill -f "telemetry_sink.py" || true')
    pshu.cmd('pkill -f "python3 main.py" || true')
    net.stop()


if __name__ == '__main__':
    run_smoke()
