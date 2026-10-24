from threading import RLock
from .config import load_venue

class AppState:
    def __init__(self):
        self.lock = RLock()
        self.venue = load_venue()
        self.zones = {z["id"]: {**z, "metrics": None} for z in self.venue["zones"]}
        self.roads = {r["id"]: {**r, "metrics": {
            "road_id": r["id"], "vehicle_count": 0, "relative_speed_pct": 100,
            "queue_seconds": 0, "closed": False, "congestion": "FREE",
            "congestion_score": 0, "source": "demo"
        }} for r in self.venue["roads"]}
        self.alerts = []
        self.emergency_events = []
        self.event_log = []
        self.demo_mode = True

    def snapshot(self):
        with self.lock:
            return {
                "venue": self.venue,
                "zones": {k: {**v, "metrics": v["metrics"]} for k, v in self.zones.items()},
                "roads": {k: {**v, "metrics": v["metrics"]} for k, v in self.roads.items()},
                "alerts": list(self.alerts),
                "emergency_events": list(self.emergency_events),
                "event_log": list(self.event_log[-100:]),
                "demo_mode": self.demo_mode
            }

state = AppState()
