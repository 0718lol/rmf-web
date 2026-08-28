import unittest

from server import LiveStore, normalize_rmf, to_millis


class NormalizeRmfTests(unittest.TestCase):
    def test_iso_timestamp(self):
        self.assertEqual(to_millis("2026-08-28T09:40:00Z"), 1787910000000)

    def test_ros_timestamp(self):
        self.assertEqual(to_millis({"sec": 1787910000, "nanosec": 500_000_000}), 1787910000500)

    def test_merges_timestamped_samples(self):
        result = normalize_rmf({
            "samples": [
                {"timestamp": "2026-08-28T09:40:00Z", "fleet_states": [{"name": "r1", "fleet_name": "delivery", "location": {"x": 1, "y": 2}}]},
                {"timestamp": "2026-08-28T09:40:03Z", "fleet_states": [{"name": "r1", "fleet_name": "delivery", "location": {"x": 7, "y": 2}}]},
            ]
        })
        self.assertEqual(len(result["routes"]["r1"]), 2)
        self.assertEqual(result["routes"]["r1"][1]["t"] - result["routes"]["r1"][0]["t"], 3000)
        self.assertEqual(result["meta"]["start_time"], 1787910000000)
        self.assertEqual(result["meta"]["end_time"], 1787910003000)

    def test_accepts_unix_seconds(self):
        result = normalize_rmf({
            "timestamp": 1787910000,
            "fleet_states": [{"robot_id": "r2", "position": [3, 4], "battery_percent": 70}],
        })
        self.assertEqual(result["routes"]["r2"][0]["t"], 1787910000000)
        self.assertEqual(result["robots"][0]["battery"], 70)

    def test_event_extends_replay_window(self):
        result = normalize_rmf({
            "timestamp": 1787910000,
            "fleet_states": [{"name": "r1", "position": [3, 4]}],
            "events": [{"timestamp": 1787910010, "type": "task_finished"}],
        })
        self.assertEqual(result["meta"]["end_time"] - result["meta"]["start_time"], 10_000)

    def test_rejects_invalid_point(self):
        with self.assertRaises(ValueError):
            normalize_rmf({"timestamp": 1787910000, "fleet_states": [{"name": "r1", "path": [None]}]})

    def test_nested_fleet_state_and_live_accumulation(self):
        store = LiveStore()
        first = normalize_rmf({"timestamp": 1787910000, "fleet_states": [{"name": "fleet-a", "robots": [{"name": "r1", "mode": {"mode": 2}, "location": {"x": 1, "y": 2}}]}]}, "live")
        second = normalize_rmf({"timestamp": 1787910001, "fleet_states": [{"name": "fleet-a", "robots": [{"name": "r1", "mode": {"mode": 2}, "location": {"x": 2, "y": 2}}]}]}, "live")
        store.put(first)
        store.put(second)
        result = store.get()
        self.assertEqual(result["robots"][0]["fleet"], "fleet-a")
        self.assertEqual(result["robots"][0]["status"], "moving")
        self.assertEqual(len(result["routes"]["r1"]), 2)
        self.assertEqual(result["meta"]["end_time"] - result["meta"]["start_time"], 1000)

    def test_rosbridge_envelope_prefers_current_location(self):
        result = normalize_rmf({
            "op": "publish",
            "topic": "/fleet_states",
            "msg": {
                "name": "delivery",
                "robots": [{
                    "name": "r1",
                    "mode": {"mode": 10, "mode_request_id": 7, "performing_action": "delivery"},
                    "location": {"t": {"sec": 1787910000, "nanosec": 0}, "x": 4, "y": 5},
                    "path": [{"t": {"sec": 1787910010, "nanosec": 0}, "x": 20, "y": 5}],
                }],
            },
        })
        self.assertEqual(result["robots"][0]["status"], "working")
        self.assertEqual(result["routes"]["r1"][0]["x"], 4)
        self.assertEqual(result["meta"]["topic"], "/fleet_states")


if __name__ == "__main__":
    unittest.main()
