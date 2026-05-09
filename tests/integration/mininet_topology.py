from mininet.net import Mininet
from mininet.node import OVSBridge


def build_net():
    net = Mininet(controller=None, switch=OVSBridge)
    s1 = net.addSwitch('s1')
    controller = net.addHost('controller')
    pshu = net.addHost('pshu')
    dsp1 = net.addHost('dsp1')

    net.addLink(controller, s1)
    net.addLink(pshu, s1)
    net.addLink(dsp1, s1)
    return net, controller, pshu, dsp1


def run_smoke():
    net, controller, pshu, dsp1 = build_net()
    net.start()
    dropped = net.pingAll()
    print(f"pingAll dropped={dropped}")

    dsp1.cmd('python3 scripts/mock_device_udp.py --port 9000 --out /tmp/device_messages.jsonl > /tmp/dsp.log 2>&1 &')
    pshu.cmd('python3 main.py > /tmp/pshu.log 2>&1 &')
    controller.cmd('python3 scripts/osc_loadgen.py --host 10.0.0.2 --port 8000 --count 20 --mode message > /tmp/loadgen.log 2>&1')

    # collect quick artifacts
    print(pshu.cmd('tail -n 20 /tmp/pshu.log'))
    print(dsp1.cmd('tail -n 20 /tmp/dsp.log'))
    print(dsp1.cmd('wc -l /tmp/device_messages.jsonl || true'))

    pshu.cmd('pkill -f "python3 main.py" || true')
    dsp1.cmd('pkill -f "mock_device_udp.py" || true')
    net.stop()


if __name__ == '__main__':
    run_smoke()
