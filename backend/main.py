from datetime import datetime, timezone
from pathlib import Path
import tempfile
import os

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from .models import ZoneObservation, TrafficObservation, EmergencyRequest, AlertAction
from .analytics import crowd_metrics, traffic_metrics, flow_recommendation
from .routing import recommend_route
from .alerts import derive_alerts
from .state import state

app = FastAPI(title="PS06 Integrated Traffic & Crowd Management API", version="0.1.0",
              description="Hackathon prototype. Recommendations only; no real traffic-signal control.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def update_alerts():
    new_alerts = derive_alerts(
        {k: v["metrics"] for k, v in state.zones.items() if v["metrics"]},
        {k: v["metrics"] for k, v in state.roads.items() if v.get("metrics")},
        state.alerts
    )
    state.alerts.extend(new_alerts)

@app.get("/")
def root():
    return {"project": "PS06", "status": "running", "docs": "/docs", "mode": "prototype"}

@app.get("/api/health")
def health():
    return {"status": "ok", "demo_mode": state.demo_mode}

@app.get("/api/dashboard")
def dashboard():
    snap = state.snapshot()
    return {
        "venue": snap["venue"]["name"],
        "zones": list(snap["zones"].values()),
        "roads": list(snap["roads"].values()),
        "alerts": snap["alerts"],
        "emergency_events": snap["emergency_events"],
        "event_log": snap["event_log"],
        "demo_mode": snap["demo_mode"]
    }

@app.post("/api/crowd/observe")
def observe_crowd(obs: ZoneObservation):
    with state.lock:
        if obs.zone_id not in state.zones:
            raise HTTPException(404, f"Unknown zone_id: {obs.zone_id}")
        cfg = state.zones[obs.zone_id]
        metrics = crowd_metrics(obs.model_dump(), cfg)
        cfg["metrics"] = metrics
        cfg["recommendation"] = flow_recommendation(metrics)
        state.event_log.append({"type": "crowd_update", "zone_id": obs.zone_id, "at": metrics["updated_at"]})
        update_alerts()
        return {"metrics": metrics, "recommendation": cfg["recommendation"]}

@app.post("/api/traffic/observe")
def observe_traffic(obs: TrafficObservation):
    with state.lock:
        if obs.road_id not in state.roads:
            raise HTTPException(404, f"Unknown road_id: {obs.road_id}")
        metrics = traffic_metrics(obs.model_dump())
        state.roads[obs.road_id]["metrics"] = metrics
        state.event_log.append({"type": "traffic_update", "road_id": obs.road_id, "at": metrics["updated_at"]})
        update_alerts()
        return {"metrics": metrics}

@app.post("/api/demo/seed")
def seed_demo():
    """Seed repeatable demo observations. All values are synthetic."""
    crowd_samples = [
        {"zone_id":"GATE_A","people_count":205,"incoming_per_min":28,"outgoing_per_min":9,"movement_score":0.42},
        {"zone_id":"MAIN_WALKWAY","people_count":310,"incoming_per_min":34,"outgoing_per_min":18,"movement_score":0.32},
        {"zone_id":"STAGE_ZONE","people_count":260,"incoming_per_min":12,"outgoing_per_min":16,"movement_score":0.7},
        {"zone_id":"PARKING","people_count":90,"incoming_per_min":4,"outgoing_per_min":5,"movement_score":0.9},
        {"zone_id":"EMERGENCY_GATE","people_count":20,"incoming_per_min":1,"outgoing_per_min":1,"movement_score":0.95}
    ]
    traffic_samples = [
        {"road_id":"R1","vehicle_count":45,"relative_speed_pct":32,"queue_seconds":135},
        {"road_id":"R2","vehicle_count":58,"relative_speed_pct":18,"queue_seconds":210},
        {"road_id":"R3","vehicle_count":20,"relative_speed_pct":68,"queue_seconds":55},
        {"road_id":"R4","vehicle_count":18,"relative_speed_pct":82,"queue_seconds":20},
        {"road_id":"R5","vehicle_count":12,"relative_speed_pct":90,"queue_seconds":15},
        {"road_id":"R6","vehicle_count":30,"relative_speed_pct":48,"queue_seconds":75},
        {"road_id":"R7","vehicle_count":5,"relative_speed_pct":95,"queue_seconds":0}
    ]
    for sample in crowd_samples:
        obs = ZoneObservation(**sample, source="demo")
        observe_crowd(obs)
    for sample in traffic_samples:
        obs = TrafficObservation(**sample, source="demo")
        observe_traffic(obs)
    state.event_log.append({"type":"demo_seeded", "at":datetime.now(timezone.utc).isoformat(), "note":"Synthetic data"})
    return {"status":"seeded", "message":"Synthetic demo observations loaded. Not live data."}

@app.get("/api/routes/recommend")
def route(origin: str = "J1", destination: str = "VENUE"):
    snap = state.snapshot()
    traffic = {k: v.get("metrics", {}) for k, v in snap["roads"].items()}
    result = recommend_route(snap["venue"], traffic, origin, destination)
    if not result["available"]:
        raise HTTPException(422, result["reason"])
    return result

@app.post("/api/emergency/route")
def emergency_route(req: EmergencyRequest):
    snap = state.snapshot()
    traffic = {k: v.get("metrics", {}) for k, v in snap["roads"].items()}
    result = recommend_route(snap["venue"], traffic, req.origin, req.destination)
    event = {
        "vehicle_id": req.vehicle_id, "emergency_type": req.emergency_type,
        "origin": req.origin, "destination": req.destination, "route": result,
        "signal_priority": [{"intersection": n, "action": "SIMULATED PRIORITY REQUEST"}
                            for n in result.get("nodes", [])[1:-1]],
        "mode": "SIMULATION_ONLY",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    with state.lock:
        state.emergency_events.insert(0, event)
        state.event_log.append({"type":"emergency_route", "vehicle_id":req.vehicle_id, "at":event["created_at"]})
    return event

@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, action: AlertAction):
    with state.lock:
        for alert in state.alerts:
            if alert["id"] == alert_id and alert["status"] == "ACTIVE":
                alert["status"] = "ACKNOWLEDGED"
                alert["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
                alert["operator_note"] = action.note
                return alert
    raise HTTPException(404, "Active alert not found")

@app.post("/api/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str, action: AlertAction):
    with state.lock:
        for alert in state.alerts:
            if alert["id"] == alert_id and alert["status"] != "RESOLVED":
                alert["status"] = "RESOLVED"
                alert["resolved_at"] = datetime.now(timezone.utc).isoformat()
                alert["operator_note"] = action.note
                return alert
    raise HTTPException(404, "Alert not found")

@app.post("/api/video/analyze")
async def analyze_video(file: UploadFile = File(...)):
    """Optional YOLO adapter. Requires requirements-video.txt and a local model weight."""
    if not file.filename or Path(file.filename).suffix.lower() not in {".mp4", ".avi", ".mov", ".mkv"}:
        raise HTTPException(400, "Upload an MP4, AVI, MOV, or MKV video.")
    try:
        from ultralytics import YOLO
        import cv2
    except ImportError:
        raise HTTPException(501, "Video analysis is optional. Install requirements-video.txt first.")
    model_path = os.getenv("YOLO_MODEL", str(Path(__file__).resolve().parents[1] / "models" / "yolo11n.pt"))
    if not Path(model_path).exists():
        raise HTTPException(501, f"YOLO model weights not found at {model_path}. Set YOLO_MODEL or place weights there.")
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=Path(file.filename).suffix, delete=False) as tmp:
        tmp.write(content)
        video_path = tmp.name
    try:
        model = YOLO(model_path)
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise HTTPException(400, "Could not open the uploaded video.")
        frame_counts, sampled = [], 0
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        stride = max(1, int(fps))  # sample roughly one frame per second
        while sampled < 60:
            ok, frame = cap.read()
            if not ok:
                break
            frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            if frame_idx % stride:
                continue
            result = model.predict(frame, verbose=False, classes=[0])[0]
            frame_counts.append(int(len(result.boxes)))
            sampled += 1
        cap.release()
        return {
            "source": "uploaded_video",
            "warning": "Per-frame detections are not unique-person counts. Density is not inferred without calibrated zone area.",
            "sampled_frames": sampled, "video_frames": total_frames,
            "average_people_detections_per_sampled_frame": round(sum(frame_counts)/len(frame_counts), 2) if frame_counts else 0,
            "max_people_detections_in_sampled_frame": max(frame_counts, default=0),
            "sample_counts": frame_counts
        }
    finally:
        try: os.unlink(video_path)
        except OSError: pass
