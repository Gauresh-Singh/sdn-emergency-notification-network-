# SDN-Socket Programming: Emergency Notification Network

A three-layer Software-Defined Networking (SDN) emergency alert system built with **Mininet**, **Ryu (OpenFlow 1.3)**, and **Python UDP Sockets**. Normal notifications use UDP port `8888`, while emergency alerts use UDP port `9999`—allowing the Ryu controller to dynamically detect urgent traffic and install high-priority OpenFlow forwarding rules (`priority=100` + strict QoS Queue 0) ahead of congested background traffic.

## Three-Layer System Architecture

```text
+-------------------------------------------------------------------+
|                   Layer 2: Ryu SDN Controller                     |
|         (controller/emergency_controller.py — OpenFlow 1.3)       |
|  - Port 8888 (NORMAL): Default L2 forwarding (priority=10, Q1)    |
|  - Port 9999 (EMERGENCY): Dynamic rule install (priority=100, Q0) |
+---------------------------------+---------------------------------+
                                  | OpenFlow 1.3 (127.0.0.1:6633)
                                  v
+-------------------------------------------------------------------+
|                  Layer 1: Mininet Virtual Network                 |
|             (topology/topology.py — 10 Mbps TCLinks)              |
|                                                                   |
|        [h1: Server] -------- [Switch s1] -------- [h2: Client 1]  |
|        (10.0.0.1)             (OVS 1.3)     \---- [h3: Client 2]  |
|                                              \--- [h4: Client 3]  |
+-------------------------------------------------------------------+
                                  ^
                                  | UDP Sockets (Ports 8888 / 9999)
+---------------------------------+---------------------------------+
|                Layer 3: UDP Notification Application              |
|                  (app/server.py & app/client.py)                  |
|  - Subscribers register on port 9000                              |
|  - Server sends NORMAL (8888) & EMERGENCY (9999) with ACK/Retry   |
+-------------------------------------------------------------------+
