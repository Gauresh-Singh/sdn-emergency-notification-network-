"""
UDP Emergency Notification Server (Notification Hub)
- Maintains thread-safe subscriber list via REGISTER packets
- Sends NORMAL alerts to UDP port 8888 (fire-and-forget)
- Sends EMERGENCY alerts to UDP port 9999 with ACK tracking & retry logic
- Logs timestamps and computes latency (ms) and packet loss (%) to results/
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
SERVER_CTRL_PORT = 9000


class NotificationServer:
    def __init__(self, mode_label="sdn_on", ack_timeout=0.3, max_retries=1):
        self.mode_label = mode_label
        self.ack_timeout = ack_timeout
        self.max_retries = max_retries
        self.clients = {}  # {client_id: ip_address}
        self.lock = threading.Lock()

        # Tracking emergency ACKs: {(msg_id, client_id): {"sent_ts": float, "ack_event": Event, "rtt_ms": float}}
        self.pending_acks = {}
        self.msg_counter = 0
        self.running = True

        os.makedirs("results", exist_ok=True)
        self.log_path = f"results/server_{self.mode_label}_log.csv"
        with open(self.log_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "msg_id", "client_id", "type", "event", "latency_ms", "attempt"])

        # Control socket for REGISTER and ACK messages
        self.ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ctrl_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ctrl_sock.bind(("0.0.0.0", SERVER_CTRL_PORT))

        # Dedicated sending sockets
        self.send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _log(self, msg_id, client_id, msg_type, event, latency_ms="", attempt=1):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with open(self.log_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([ts, msg_id, client_id, msg_type, event, latency_ms, attempt])

    def _listen_control(self):
        while self.running:
            try:
                data, addr = self.ctrl_sock.recvfrom(4096)
                payload = json.loads(data.decode("utf-8"))
                action = payload.get("action")
                client_id = payload.get("client_id", addr[0])

                if action == "REGISTER":
                    with self.lock:
                        self.clients[client_id] = addr[0]
                    print(f"[SERVER] Registered subscriber '{client_id}' at {addr[0]}", flush=True)
                    self._log(0, client_id, "CONTROL", "CLIENT_REGISTERED")

                elif action == "ACK":
                    msg_id = payload.get("msg_id")
                    key = (msg_id, client_id)
                    with self.lock:
                        entry = self.pending_acks.get(key)
                        if entry and not entry["ack_event"].is_set():
                            rtt_ms = round((time.perf_counter() - entry["sent_ts"]) * 1000.0, 2)
                            entry["rtt_ms"] = rtt_ms
                            entry["ack_event"].set()
                            self._log(msg_id, client_id, "EMERGENCY", "ACK_RECEIVED", rtt_ms, entry["attempt"])
            except Exception:
                pass

    def broadcast_normal(self, text):
        with self.lock:
            self.msg_counter += 1
            msg_id = self.msg_counter
            targets = list(self.clients.items())

        payload = json.dumps({"msg_id": msg_id, "type": "NORMAL", "text": text}).encode("utf-8")
        for cid, ip in targets:
            self.send_sock.sendto(payload, (ip, NORMAL_PORT))
            self._log(msg_id, cid, "NORMAL", "SENT")
        print(f"[SERVER] Broadcast NORMAL #{msg_id} to {len(targets)} clients (port 8888)", flush=True)

    def _deliver_emergency_to_client(self, msg_id, cid, ip, text, results_list):
        payload = json.dumps({"msg_id": msg_id, "type": "EMERGENCY", "text": text}).encode("utf-8")
        key = (msg_id, cid)
        ack_event = threading.Event()

        for attempt in range(1, self.max_retries + 2):
            with self.lock:
                self.pending_acks[key] = {
                    "sent_ts": time.perf_counter(),
                    "ack_event": ack_event,
                    "rtt_ms": None,
                    "attempt": attempt
                }
            self.send_sock.sendto(payload, (ip, EMERGENCY_PORT))
            self._log(msg_id, cid, "EMERGENCY", "SENT", "", attempt)

            if ack_event.wait(timeout=self.ack_timeout):
                rtt = self.pending_acks[key]["rtt_ms"]
                results_list.append((True, rtt))
                return
            else:
                if attempt <= self.max_retries:
                    print(f"[SERVER] Timeout for #{msg_id} -> {cid} (attempt {attempt}), retrying...", flush=True)
                    self._log(msg_id, cid, "EMERGENCY", "RETRY_TIMEOUT", "", attempt)

        self._log(msg_id, cid, "EMERGENCY", "FAILED_DROPPED", "", self.max_retries + 1)
        results_list.append((False, None))

    def broadcast_emergency(self, text, quiet=False):
        with self.lock:
            self.msg_counter += 1
            msg_id = self.msg_counter
            targets = list(self.clients.items())

        if not targets:
            print("[SERVER] Warning: No clients registered yet!")
            return []

        results = []
        threads = []
        for cid, ip in targets:
            t = threading.Thread(
                target=self._deliver_emergency_to_client,
                args=(msg_id, cid, ip, text, results)
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        if not quiet:
            acked = [r[1] for r in results if r[0]]
            print(
                f"[SERVER] EMERGENCY #{msg_id} complete: {len(acked)}/{len(targets)} ACKed "
                f"| Avg RTT: {round(sum(acked)/len(acked), 2) if acked else 'N/A'} ms",
                flush=True
            )
        return results

    def run_benchmark(self, count=50, interval=0.15):
        print(f"\n=== STARTING BENCHMARK ({self.mode_label.upper()}): {count} Emergency Alerts ===", flush=True)
        all_results = []
        for i in range(1, count + 1):
            res = self.broadcast_emergency(f"CRITICAL ALERT #{i}: Evacuate Sector 4", quiet=True)
            all_results.extend(res)
            time.sleep(interval)

        total = len(all_results)
        acked_latencies = [r[1] for r in all_results if r[0] and r[1] is not None]
        delivered = len(acked_latencies)
        loss_pct = round(((total - delivered) / total) * 100.0, 2) if total > 0 else 100.0
        avg_lat = round(sum(acked_latencies) / delivered, 2) if delivered > 0 else 0.0

        summary = (
            f"\n========================================\n"
            f"BENCHMARK SUMMARY [{self.mode_label.upper()}]\n"
            f"Total Emergency Packets Sent : {total}\n"
            f"Total ACKed Delivered        : {delivered}\n"
            f"Packet Loss (%)              : {loss_pct}%\n"
            f"Average Latency (ms)         : {avg_lat} ms\n"
            f"Saved CSV Log                : {self.log_path}\n"
            f"========================================\n"
        )
        print(summary, flush=True)
        with open(f"results/summary_{self.mode_label}.txt", "w") as f:
            f.write(summary)

    def start_interactive(self):
        t = threading.Thread(target=self._listen_control, daemon=True)
        t.start()
        print("[SERVER] Listening on UDP 9000. Waiting for clients to register...", flush=True)
        print("Commands:  n <message>  (send NORMAL) |  e <message>  (send EMERGENCY) |  bench  (50-msg test) |  quit")
        while True:
            try:
                cmd = input("> ").strip()
                if cmd.startswith("n "):
                    self.broadcast_normal(cmd[2:])
                elif cmd.startswith("e "):
                    self.broadcast_emergency(cmd[2:])
                elif cmd == "bench":
                    self.run_benchmark(count=50)
                elif cmd == "quit":
                    break
            except (EOFError, KeyboardInterrupt):
                break
        self.running = False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UDP Emergency Notification Server")
    parser.add_argument("--mode", default="sdn_on", help="Label for log files (e.g., sdn_on or sdn_off)")
    parser.add_argument("--auto-bench", type=int, default=0, help="Wait 5s for clients then run N emergency alerts")
    args = parser.parse_args()

    srv = NotificationServer(mode_label=args.mode)
    if args.auto_bench > 0:
        t = threading.Thread(target=srv._listen_control, daemon=True)
        t.start()
        print("[SERVER] Waiting 5 seconds for clients to register before auto-benchmark...", flush=True)
        time.sleep(5)
        srv.run_benchmark(count=args.auto_bench)
    else:
        srv.start_interactive()
