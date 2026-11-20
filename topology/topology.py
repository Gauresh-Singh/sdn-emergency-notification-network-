"""
Mininet Topology for Problem 16: Emergency Notification Network
Creates 1 OpenFlow 1.3 switch (s1) connected to 4 hosts:
  h1 (10.0.0.1) = Notification Server
  h2 (10.0.0.2) = Client 1 / Congestion Generator
  h3 (10.0.0.3) = Client 2
  h4 (10.0.0.4) = Client 3 / Secondary Congestion Generator
"""

from mininet.topo import Topo
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel


class EmergencyTopo(Topo):
    def build(self):
        # Single OpenFlow 1.3 switch
        s1 = self.addSwitch('s1', protocols='OpenFlow13')

        # Server host (h1) and Client hosts (h2, h3, h4)
        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
        h3 = self.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')
        h4 = self.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04')

        # Constrained 10 Mbps links with small queues so congestion is measurable
        link_opts = dict(cls=TCLink, bw=10, delay='2ms', max_queue_size=50)
        self.addLink(h1, s1, **link_opts)
        self.addLink(h2, s1, **link_opts)
        self.addLink(h3, s1, **link_opts)
        self.addLink(h4, s1, **link_opts)


topos = {'mytopo': (lambda: EmergencyTopo())}

if __name__ == '__main__':
    setLogLevel('info')
    net = Mininet(
        topo=EmergencyTopo(),
        switch=OVSKernelSwitch,
        controller=lambda name: RemoteController(name, ip='127.0.0.1', port=6633),
        autoSetMacs=True
    )
    net.start()
    print("*** Network started. Run 'pingall' to verify connectivity.")
    CLI(net)
    net.stop()
