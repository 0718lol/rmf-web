#!/usr/bin/env python3
import argparse
import json
import math
import os
import time
from urllib.request import Request, urlopen


def fleet_state(step):
    now = time.time()
    seconds = int(now)
    nanoseconds = int((now - seconds) * 1_000_000_000)
    robots = []
    specs = [
        ("deliveryRobot_1", 16, 22, 0.0, 86),
        ("deliveryRobot_2", 38, 34, 1.6, 72),
        ("cleanRobot_1", 68, 42, 3.1, 91),
    ]
    for index, (name, origin_x, origin_y, phase, battery) in enumerate(specs):
        angle = step * 0.08 + phase
        x = origin_x + math.cos(angle) * (7 + index * 2)
        y = origin_y + math.sin(angle) * (5 + index * 2)
        robots.append({
            "name": name,
            "model": "mock-amr",
            "task_id": f"simulation-{index + 1}",
            "seq": step,
            "mode": {"mode": 2, "mode_request_id": 1, "performing_action": ""},
            "battery_percent": max(20, battery - step * 0.01),
            "location": {
                "t": {"sec": seconds, "nanosec": nanoseconds},
                "x": round(x, 3),
                "y": round(y, 3),
                "yaw": round(angle, 3),
                "obey_approach_speed_limit": False,
                "approach_speed_limit": 0.0,
                "level_name": "L1",
                "index": index,
            },
            "path": [],
        })
    return {"name": "delivery", "robots": robots, "map": {"name": "L1 / RMF 模拟场", "width": 100, "height": 64}}


def push(url, payload, token):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url.rstrip("/") + "/api/trajectory/live", data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"ingest returned HTTP {response.status}")


def main():
    parser = argparse.ArgumentParser(description="Push hardware-free Open-RMF FleetState samples")
    parser.add_argument("--url", required=True, help="RMF trajectory product root URL")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between snapshots")
    parser.add_argument("--count", type=int, default=0, help="Snapshots to send; 0 runs until interrupted")
    args = parser.parse_args()
    token = os.environ.get("RMF_INGEST_TOKEN")
    step = 0
    while args.count == 0 or step < args.count:
        push(args.url, fleet_state(step), token)
        step += 1
        print(f"pushed FleetState #{step}", flush=True)
        if args.count == 0 or step < args.count:
            time.sleep(max(0.1, args.interval))


if __name__ == "__main__":
    main()
