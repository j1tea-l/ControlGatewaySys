"""Mininet topology for PSHU tests in WSL2.
Uses controller=none and ovsbr switch to avoid 100% ping loss issue.
"""
from mininet.net import Mininet
from mininet.node import OVSBridge
from mininet.cli import CLI


def run() -> None:
    net = Mininet(controller=None, switch=OVSBridge)

    s1 = net.addSwitch('s1')
    controller = net.addHost('controller')
    pshu = net.addHost('pshu')
    dsp1 = net.addHost('dsp1')
    ppp1 = net.addHost('ppp1')

    net.addLink(controller, s1)
    net.addLink(pshu, s1)
    net.addLink(dsp1, s1)
    net.addLink(ppp1, s1)

    net.start()
    print('Network started (controller=none, switch=OVSBridge)')
    net.pingAll()
    CLI(net)
    net.stop()


if __name__ == '__main__':
    run()
