import copy
import json
import mimetypes
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
HOST = "0.0.0.0"
COLORS = ["#0f766e", "#d97706", "#2563eb", "#7c3aed", "#c2410c"]
STALE_AFTER_MS = 15_000


def to_millis(value, fallback=None):
    if value is None:
        return fallback
    if isinstance(value, dict):
        seconds = value.get("sec", value.get("secs"))
        nanoseconds = value.get("nanosec", value.get("nsecs", 0))
        if seconds is None:
            raise ValueError(f"invalid ROS timestamp: {value}")
        return round(float(seconds) * 1000 + float(nanoseconds) / 1_000_000)
    if isinstance(value, (int, float)):
        return round(value * 1000) if value < 10_000_000_000 else round(value)
    text = str(value).strip()
    if text.isdigit():
        return to_millis(int(text), fallback)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return round(parsed.timestamp() * 1000)
    except ValueError as error:
        raise ValueError(f"invalid timestamp: {value}") from error


def point_from(value, timestamp):
    if isinstance(value, dict):
        return {
            "x": float(value.get("x", 0)),
            "y": float(value.get("y", 0)),
            "t": to_millis(value.get("t", value.get("timestamp")), timestamp),
        }
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        point_time = value[2] if len(value) > 2 else timestamp
        return {"x": float(value[0]), "y": float(value[1]), "t": to_millis(point_time, timestamp)}
    raise ValueError("trajectory point must contain x and y")


def robot_from(state, index, fleet_name=None):
    robot_id = str(state.get("robot_id") or state.get("id") or state.get("name") or f"robot-{index + 1}")
    battery = state.get("battery", state.get("battery_percent", 100))
    raw_mode = state.get("status", state.get("mode", "idle"))
    if isinstance(raw_mode, dict):
        raw_mode = raw_mode.get("mode", "idle")
    mode_names = {0: "idle", 1: "charging", 2: "moving", 3: "paused", 4: "waiting", 5: "warning", 6: "moving", 7: "docking", 8: "warning", 9: "cleaning", 10: "working", 11: "idle"}
    status = mode_names.get(raw_mode, str(raw_mode).lower())
    return {
        "id": robot_id,
        "name": str(state.get("name") or robot_id),
        "fleet": str(state.get("fleet_name") or state.get("fleet") or fleet_name or "RMF fleet"),
        "color": state.get("color") or COLORS[index % len(COLORS)],
        "battery": max(0, min(100, round(float(battery)))),
        "status": status,
        "task": str(state.get("task_id") or state.get("task") or "无任务"),
    }


def normalize_event(event):
    timestamp = to_millis(event.get("timestamp", event.get("t")), None)
    normalized = dict(event)
    if timestamp is not None:
        normalized["timestamp"] = timestamp
        normalized.setdefault("time", datetime.fromtimestamp(timestamp / 1000, timezone.utc).strftime("%H:%M:%S"))
    normalized.setdefault("type", "RMF 事件")
    normalized.setdefault("robot", event.get("robot_id", "RMF"))
    normalized.setdefault("detail", "")
    return normalized


def finalize(data, source="import"):
    routes = {}
    all_times = []
    for robot_id, values in data.get("routes", {}).items():
        fallback = to_millis(data.get("meta", {}).get("updated"), int(time.time() * 1000))
        points = [point_from(value, fallback + index * 1000) for index, value in enumerate(values)]
        points.sort(key=lambda item: item["t"])
        routes[str(robot_id)] = points
        all_times.extend(point["t"] for point in points)

    events = [normalize_event(event) for event in data.get("events", data.get("task_events", []))]
    all_times.extend(event["timestamp"] for event in events if event.get("timestamp") is not None)
    meta = dict(data.get("meta", {}))
    now = int(time.time() * 1000)
    start = to_millis(meta.get("start_time"), min(all_times) if all_times else now)
    end = to_millis(meta.get("end_time", meta.get("updated")), max(all_times) if all_times else start)
    if end < start:
        start, end = end, start
    tasks = list(data.get("tasks", []))
    robots = list(data.get("robots", []))
    running = sum(1 for robot in robots if robot.get("task") not in {None, "", "无任务", "待命"})
    delays = [float(task.get("delay_seconds", 0)) for task in tasks if task.get("delay_seconds") is not None]
    replans = sum(1 for event in events if "重规划" in str(event.get("type", "")) or event.get("type") == "replan")
    meta.update({
        "start_time": start,
        "end_time": end,
        "updated": end,
        "source": meta.get("source", source),
        "connected": bool(meta.get("connected", source == "live")),
        "robot_count": len(robots),
        "online_robots": sum(1 for robot in robots if robot.get("status") not in {"offline", "disconnected"}),
        "tasks": meta.get("tasks", len(tasks) or running),
        "running_tasks": meta.get("running_tasks", running),
        "average_delay_seconds": round(sum(delays) / len(delays)) if delays else int(meta.get("average_delay_seconds", 0)),
        "replans": meta.get("replans", replans),
    })
    return {
        "schema_version": "1.0",
        "map": data.get("map", {"name": "RMF map", "width": 100, "height": 64}),
        "robots": robots,
        "routes": routes,
        "zones": list(data.get("zones", [])),
        "events": events,
        "tasks": tasks,
        "meta": meta,
    }


def normalize_rmf(payload, source="import"):
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    if isinstance(payload.get("msg"), dict):
        envelope = payload
        payload = copy.deepcopy(payload["msg"])
        payload.setdefault("meta", {})["transport"] = envelope.get("op", "rosbridge")
        payload["meta"]["topic"] = envelope.get("topic")
    if "samples" in payload:
        robots_by_id = {}
        routes = {}
        for sample_index, sample in enumerate(payload["samples"]):
            timestamp = to_millis(sample.get("timestamp", sample.get("t")))
            if timestamp is None:
                raise ValueError(f"samples[{sample_index}] is missing timestamp")
            groups = sample.get("fleet_states", sample.get("robots", []))
            states = []
            for group in groups:
                if isinstance(group, dict) and "robots" in group:
                    states.extend((robot, group.get("name", group.get("fleet_name"))) for robot in group["robots"])
                else:
                    states.append((group, sample.get("fleet_name")))
            for state_index, (robot_state, fleet_name) in enumerate(states):
                robot = robot_from(robot_state, state_index, fleet_name)
                robots_by_id[robot["id"]] = robot
                position = robot_state.get("location", robot_state.get("position"))
                if position is not None:
                    routes.setdefault(robot["id"], []).append(point_from(position, timestamp))
                else:
                    for value in robot_state.get("path", robot_state.get("trajectory", [])):
                        routes.setdefault(robot["id"], []).append(point_from(value, timestamp))
        projected = dict(payload)
        projected["robots"] = list(robots_by_id.values())
        projected["routes"] = routes
        projected["events"] = payload.get("events", payload.get("task_events", []))
        return finalize(projected, source)

    if "map" in payload and "robots" in payload and "routes" in payload:
        projected = copy.deepcopy(payload)
        projected["robots"] = [robot_from(robot, index) for index, robot in enumerate(payload["robots"])]
        return finalize(projected, source)

    groups = payload.get("fleet_states", payload.get("robots", []))
    states = []
    for group in groups:
        if isinstance(group, dict) and "robots" in group:
            states.extend((robot, group.get("name", group.get("fleet_name"))) for robot in group["robots"])
        else:
            states.append((group, payload.get("name", payload.get("fleet_name"))))
    timestamp = to_millis(payload.get("timestamp", payload.get("t")), int(time.time() * 1000))
    robots = []
    routes = {}
    for index, (state, fleet_name) in enumerate(states):
        robot = robot_from(state, index, fleet_name)
        robots.append(robot)
        position = state.get("location", state.get("position"))
        path = [position] if position is not None else state.get("path", state.get("trajectory", []))
        routes[robot["id"]] = [point_from(point, timestamp) for point in path]
    return finalize({
        "map": payload.get("map", {"name": "RMF map", "width": 100, "height": 64}),
        "robots": robots,
        "routes": routes,
        "zones": payload.get("zones", []),
        "events": payload.get("events", payload.get("task_events", [])),
        "tasks": payload.get("tasks", []),
        "meta": payload.get("meta", {}),
    }, source)


def demo_data():
    start = datetime(2026, 8, 28, 9, 29, 23, tzinfo=timezone.utc).timestamp() * 1000
    raw_routes = {
        "amr-07": [[9, 50], [17, 50], [17, 42], [29, 42], [29, 32], [41, 32], [41, 23], [55, 23], [55, 14], [72, 14], [72, 9]],
        "amr-12": [[12, 55], [24, 55], [24, 47], [36, 47], [36, 38], [48, 38], [48, 31], [63, 31], [63, 24]],
        "clean-03": [[84, 53], [84, 43], [74, 43], [74, 34], [86, 34], [86, 23], [76, 23], [76, 13]],
        "lift-02": [[52, 57], [52, 48], [63, 48], [63, 39], [73, 39], [73, 29]],
    }
    routes = {}
    for route_index, (robot_id, points) in enumerate(raw_routes.items()):
        routes[robot_id] = [{"x": point[0], "y": point[1], "t": start + index * (48_000 + route_index * 9_000)} for index, point in enumerate(points)]
    data = {
        "map": {"name": "HQ-01 / 一层物流区", "width": 100, "height": 64},
        "robots": [
            {"id": "amr-07", "name": "AMR-07", "fleet": "delivery", "color": "#0f766e", "battery": 86, "status": "moving", "task": "配送任务 #1842"},
            {"id": "amr-12", "name": "AMR-12", "fleet": "delivery", "color": "#d97706", "battery": 64, "status": "paused", "task": "配送任务 #1845"},
            {"id": "clean-03", "name": "Clean-03", "fleet": "cleaning", "color": "#2563eb", "battery": 92, "status": "idle", "task": "待命"},
            {"id": "lift-02", "name": "Lift-02", "fleet": "lift", "color": "#7c3aed", "battery": 41, "status": "warning", "task": "充电排队"},
        ],
        "routes": routes,
        "events": [
            {"timestamp": start + 768_000, "robot": "AMR-07", "type": "任务完成", "detail": "到达 B-12 / 交付货物", "tone": "ok"},
            {"timestamp": start + 733_000, "robot": "AMR-12", "type": "等待", "detail": "前方路段被占用，预计 18 秒", "tone": "warn"},
            {"timestamp": start + 695_000, "robot": "Lift-02", "type": "电量告警", "detail": "剩余 41%，已加入充电队列", "tone": "danger"},
            {"timestamp": start + 659_000, "robot": "Clean-03", "type": "任务开始", "detail": "清洁路线 C-03", "tone": "info"},
            {"timestamp": start + 624_000, "robot": "AMR-07", "type": "路径重规划", "detail": "避让行人区域 P-02", "tone": "info"},
        ],
        "tasks": [
            {"id": "#1842", "name": "配送至 B-12", "robot": "AMR-07", "route": "装卸区 A → B-12", "duration_seconds": 392, "status": "done"},
            {"id": "#1845", "name": "配送至 C-04", "robot": "AMR-12", "route": "装卸区 A → C-04", "duration_seconds": 258, "status": "running"},
            {"id": "#1847", "name": "清洁路线", "robot": "Clean-03", "route": "C-03 环线", "duration_seconds": 481, "status": "queued"},
        ],
        "zones": [
            {"name": "装卸区 A", "x": 5, "y": 6, "w": 20, "h": 13, "class": "dock"},
            {"name": "电梯厅", "x": 45, "y": 3, "w": 16, "h": 13, "class": "lift"},
            {"name": "充电区", "x": 72, "y": 47, "w": 22, "h": 12, "class": "charge"},
            {"name": "行人缓冲区", "x": 60, "y": 20, "w": 15, "h": 16, "class": "people"},
        ],
        "meta": {"tasks": 18, "running_tasks": 6, "average_delay_seconds": 134, "replans": 7, "source": "demo", "connected": False},
    }
    return finalize(data, "demo")


class LiveStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = None
        self.received_at = None

    def put(self, data):
        with self.lock:
            if self.data is None or self.data.get("map", {}).get("name") != data.get("map", {}).get("name"):
                self.data = copy.deepcopy(data)
            else:
                merged = copy.deepcopy(self.data)
                merged["map"] = copy.deepcopy(data["map"])
                merged["zones"] = copy.deepcopy(data["zones"] or merged.get("zones", []))
                robots = {robot["id"]: robot for robot in merged.get("robots", [])}
                robots.update({robot["id"]: robot for robot in data.get("robots", [])})
                merged["robots"] = list(robots.values())
                for robot_id, points in data.get("routes", {}).items():
                    combined = merged.setdefault("routes", {}).get(robot_id, []) + points
                    unique = {(point["t"], point["x"], point["y"]): point for point in combined}
                    merged["routes"][robot_id] = sorted(unique.values(), key=lambda point: point["t"])[-5000:]
                event_key = lambda event: (event.get("timestamp"), event.get("type"), event.get("robot"), event.get("detail"))
                events = {event_key(event): event for event in merged.get("events", [])}
                events.update({event_key(event): event for event in data.get("events", [])})
                merged["events"] = sorted(events.values(), key=lambda event: event.get("timestamp", 0), reverse=True)[:500]
                tasks = {str(task.get("id")): task for task in merged.get("tasks", [])}
                tasks.update({str(task.get("id")): task for task in data.get("tasks", [])})
                merged["tasks"] = list(tasks.values())
                merged["meta"].update(data.get("meta", {}))
                merged["meta"].pop("start_time", None)
                merged["meta"].pop("end_time", None)
                self.data = finalize(merged, "live")
            self.received_at = int(time.time() * 1000)

    def get(self):
        with self.lock:
            if self.data is None:
                fallback = demo_data()
                fallback["meta"].update({"source": "demo-fallback", "connected": False, "message": "等待 RMF 实时数据"})
                return fallback
            result = copy.deepcopy(self.data)
            age = int(time.time() * 1000) - self.received_at
            result["meta"].update({"received_at": self.received_at, "age_ms": age, "connected": age <= STALE_AFTER_MS})
            if age > STALE_AFTER_MS:
                result["meta"]["message"] = "实时数据已延迟"
            return result

    def status(self):
        with self.lock:
            age = None if self.received_at is None else int(time.time() * 1000) - self.received_at
            return {"has_live_data": self.data is not None, "age_ms": age, "connected": age is not None and age <= STALE_AFTER_MS}


STORE = LiveStore()


class Handler(BaseHTTPRequestHandler):
    server_version = "RMFTrajectory/0.2"

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.send_json(200, {"ok": True, "service": "rmf-trajectory", "version": "0.2", "live": STORE.status()})
        if path == "/api/trajectory/demo":
            return self.send_json(200, demo_data())
        if path == "/api/trajectory/live":
            return self.send_json(200, STORE.get())
        if path in {"/", "/index.html", "/styles.css", "/app.js"}:
            return self.static(path)
        return self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in {"/api/trajectory/import", "/api/trajectory/live"}:
            return self.send_json(404, {"error": "API route not found"})
        if path.endswith("/live") and not self.authorized():
            return self.send_json(401, {"error": "invalid ingest token"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 20 * 1024 * 1024:
                raise ValueError("payload must be between 1 byte and 20 MB")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            data = normalize_rmf(payload, "live" if path.endswith("/live") else "import")
            if path.endswith("/live"):
                data["meta"]["connected"] = True
                STORE.put(data)
            return self.send_json(200, data)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            return self.send_json(400, {"error": str(error)})

    def authorized(self):
        token = os.environ.get("RMF_INGEST_TOKEN")
        return not token or self.headers.get("Authorization") == f"Bearer {token}"

    def static(self, path):
        target = ROOT / ("index.html" if path == "/" else path.lstrip("/"))
        if not target.exists() or target.parent != ROOT:
            return self.send_json(404, {"error": "Not found"})
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer((HOST, port), Handler).serve_forever()
