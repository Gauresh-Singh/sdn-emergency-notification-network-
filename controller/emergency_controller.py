"""
Ryu OpenFlow 1.3 SDN Controller for Emergency Notification Prioritization
- Normal L2 forwarding: OpenFlow priority = 10 (Queue 1 - standard traffic)
- Emergency UDP (port 9999): Dynamically detected on Packet-In and installed
  with OpenFlow priority = 100 (Queue 0 - strict high-priority queue)
- Toggle mode via environment variable:
    SDN_PRIORITY=1 ruy-manager controller/emergency_controller.py  (ON - default)
    SDN_PRIORITY=0 ryu-manager controller/emergency_controller.py  (OFF - baseline)
"""

import os
import subprocess
from datetime import datetime

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, ipv4, udp

EMERGENCY_PORT = 9999
NORMAL_PORT = 8888
LOG_FILE = "results/controller_events.log"


class EmergencySDNController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(EmergencySDNController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.priority_enabled = os.environ.get("SDN_PRIORITY", "1") == "1"
        os.makedirs("results", exist_ok=True)
        mode_str = "ON (Dynamic Port 9999 Priority Active)" if self.priority_enabled else "OFF (Plain L2 Forwarding Only)"
        self._log(f"Controller started | SDN Priority Mode: {mode_str}")

    def _log(self, msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")

    def _configure_ovs_queues(self):
        """
        Attaches strict priority QoS queues to all s1 switch interfaces:
          Queue 0: High-priority emergency queue (guaranteed full bandwidth)
          Queue 1: Best-effort normal queue (throttled under contention)
        """
        try:
            ports = subprocess.check_output(["ovs-vsctl", "list-ports", "s1"], text=True).split()
            for port in ports:
                subprocess.run(
                    [
                        "ovs-vsctl", "--", "set", "Port", port, "qos=@newqos",
                        "--", "--id=@newqos", "create", "QoS", "type=linux-htb",
                        "other-config:max-rate=10000000", "queues=0=@q0,1=@q1",
                        "--", "--id=@q0", "create", "Queue",
                        "other-config:min-rate=8000000", "other-config:max-rate=10000000", "other-config:priority=0",
                        "--", "--id=@q1", "create", "Queue",
                        "other-config:min-rate=500000", "other-config:max-rate=3000000", "other-config:priority=10"
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            self._log(f"Configured OpenFlow QoS priority queues on switch ports: {ports}")
        except Exception as e:
            self._log(f"Warning: Could not attach OVS QoS queues ({e}); using OpenFlow flow priority only.")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Table-miss flow entry: send unmatched packets to controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, priority=0, match=match, actions=actions)

        if self.priority_enabled:
            self._configure_ovs_queues()

    def add_flow(self, datapath, priority, match, actions, buffer_id=None, idle_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        if buffer_id is not None and buffer_id != ofproto.OFP_NO_BUFFER:
            mod = parser.OFPFlowMod(
                datapath=datapath, buffer_id=buffer_id, priority=priority,
                match=match, instructions=inst, idle_timeout=idle_timeout
            )
        else:
            mod = parser.OFPFlowMod(
                datapath=datapath, priority=priority,
                match=match, instructions=inst, idle_timeout=idle_timeout
            )
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)

        # Inspect IPv4 + UDP headers dynamically
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        udp_pkt = pkt.get_protocol(udp.udp)

        is_emergency = False
        if udp_pkt and (udp_pkt.dst_port == EMERGENCY_PORT or udp_pkt.src_port == EMERGENCY_PORT):
            is_emergency = True

        if out_port != ofproto.OFPP_FLOOD:
            if self.priority_enabled and is_emergency and ip_pkt:
                # Dynamic high-priority OpenFlow rule + Queue 0 for Emergency UDP 9999
                match = parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_IP,
                    ip_proto=17,
                    ipv4_src=ip_pkt.src,
                    ipv4_dst=ip_pkt.dst,
                    udp_dst=udp_pkt.dst_port
                )
                actions = [parser.OFPActionSetQueue(0), parser.OFPActionOutput(out_port)]
                self.add_flow(datapath, priority=100, match=match, actions=actions, idle_timeout=60)
                self._log(
                    f"DYNAMIC PRIORITY RULE INSTALLED | flow={ip_pkt.src}->{ip_pkt.dst} "
                    f"UDP dst_port={udp_pkt.dst_port} | OF_Priority=100 | Queue=0 (HIGH)"
                )
            else:
                # Standard L2 forwarding rule + Queue 1 (Normal traffic)
                match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
                if self.priority_enabled:
                    actions = [parser.OFPActionSetQueue(1), parser.OFPActionOutput(out_port)]
                else:
                    actions = [parser.OFPActionOutput(out_port)]
                self.add_flow(datapath, priority=10, match=match, actions=actions, idle_timeout=30)
                if is_emergency:
                    self._log(
                        f"SDN PRIORITY OFF | Emergency packet forwarded as normal traffic "
                        f"({ip_pkt.src}->{ip_pkt.dst} port={udp_pkt.dst_port}) | OF_Priority=10"
                    )
        else:
            actions = [parser.OFPActionOutput(out_port)]

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(
            datapath=datapath, buffer_id=msg.buffer_id,
            in_port=in_port, actions=actions, data=data
        )
        datapath.send_msg(out)
