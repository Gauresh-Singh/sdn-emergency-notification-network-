"""
UDP Emergency Notification Client (Subscriber)
- Registers with server (10.0.0.1) on startup
- Listens simultaneously on:
    Port 8888 = NORMAL notifications
    Port 9999 = EMERGENCY notifications (immediately sends ACK back to server)
- Logs every received message and ACK to results/client_<id>_log.csv
"""

import argparse
import csv
import json
import os
import socket
import threading
import time
from datetime import datetime

NORMAL_PORT = 8888
EMERGENCY_PORT = 9999


class NotificationClient:
    def __init__(self, client_id, server_ip, server_reg_port=9000):
        self.client_id = client_id
        self.server_ip = server_ip
        self.server_reg_port = server_reg_port
        self.running = True

        os.makedirs("results", exist_ok=True)
        self.log_path = f"results/client_{self.client_id}_log.csv"
        with open(self.log_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "client_id", "msg_id", "type", "event", "content"])

        self.sock_normal = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_normal.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock_normal.bind(("0.0.0.0", NORMAL_PORT))

        self.sock_emerg = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_emerg.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock_emerg.bind(("0.0.0.0", EMERGENCY_PORT))

    def _log(self, msg_id, msg_type, event, content):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with open(self.log_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([ts, self.client_id, msg_id, msg_type, event, content])

    def register(self):
        reg_payload = json.dumps({
            "action": "REGISTER",
            "client_id": self.client_id,
            "normal_port": NORMAL_PORT,
            "emergency_port": EMERGENCY_PORT
        }).encode("utf-8")
        self.sock_emerg.sendto(reg_payload, (self.server_ip, self.server_reg_port))
        print(f"[{self.client_id}] Sent REGISTER to {self.server_ip}:{self.server_reg_port}", flush=True)
        self._log("0", "CONTROL", "REGISTER_SENT", f"Server {self.server_ip}")

    def _listen_normal(self):
        while self.running:
            try:
                data, addr = self.sock_normal.recvfrom(4096)
                msg = json.loads(data.decode("utf-8"))
                msg_id = msg.get("msg_id", "?")
                text = msg.get("text", "")
                print(f"[{self.client_id}] [NORMAL | Port 8888] #{msg_id}: {text}", flush=True)
                self._log(msg_id, "NORMAL", "RECEIVED", text)
            except Exception:
                pass

    def _listen_emergency(self):
        while self.running:
            try:
                data, addr = self.sock_emerg.recvfrom(4096)
                msg = json.loads(data.decode("utf-8"))
                msg_id = msg.get("msg_id", "?")
                text = msg.get("text", "")
                print(f"[{self.client_id}] [EMERGENCY | Port 9999] #{msg_id}: {text} -> SENDING ACK", flush=True)
                self._log(msg_id, "EMERGENCY", "RECEIVED", text)

                # Immediately send ACK back via emergency socket (port 9999)
                ack = json.dumps({
                    "action": "ACK",
                    "msg_id": msg_id,
                    "client_id": self.client_id
                }).encode("utf-8")
                self.sock_emerg.sendto(ack, (self.server_ip, self.server_reg_port))
                self._log(msg_id, "EMERGENCY", "ACK_SENT", text)
            except Exception:
                pass

    def start(self):
        self.register()
        t1 = threading.Thread(target=self._listen_normal, daemon=True)
        t2 = threading.Thread(target=self._listen_emergency, daemon=True)
        t1.start()
        t2.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.running = False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UDP Emergency Notification Client")
    parser.add_argument("--id", required=True, help="Client identifier (e.g., h2, h3, h4)")
    parser.add_argument("--server", default="10.0.0.1", help="Server IP (default: 10.0.0.1)")
    args = parser.parse_args()

    client = NotificationClient(client_id=args.id, server_ip=args.server)
    client.start()
