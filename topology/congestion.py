"""
Adjustable UDP Congestion Generator
Floods NORMAL traffic (UDP port 8888) across the switch to simulate network overload.
Supports single-host or multi-host heavy congestion modes.
"""

import argparse
import socket
import time


def run_flood(target_ip, port, rate_pps, duration, payload_size):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    payload = b"X" * payload_size
    interval = 1.0 / rate_pps if rate_pps > 0 else 0.0
    end_time = time.time() + duration
    sent = 0

    print(f"[CONGESTION] Flooding {target_ip}:{port} at {rate_pps} pps ({payload_size}B) for {duration}s...")
    while time.time() < end_time:
        loop_start = time.time()
        try:
            sock.sendto(payload, (target_ip, port))
            sent += 1
        except Exception:
            pass
        if interval > 0:
            elapsed = time.time() - loop_start
            if elapsed < interval:
                time.sleep(interval - elapsed)

    sock.close()
    print(f"[CONGESTION] Completed. Total normal packets flooded: {sent}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UDP Normal Traffic Congestion Generator")
    parser.add_argument("--target", default="10.0.0.1", help="Target host IP (default: 10.0.0.1)")
    parser.add_argument("--port", type=int, default=8888, help="UDP port (default: 8888 NORMAL)")
    parser.add_argument("--rate", type=int, default=1500, help="Packets per second (default: 1500)")
    parser.add_argument("--duration", type=int, default=30, help="Flood duration in seconds (default: 30)")
    parser.add_argument("--size", type=int, default=1200, help="Payload bytes per packet (default: 1200)")
    args = parser.parse_args()

    run_flood(args.target, args.port, args.rate, args.duration, args.size)
