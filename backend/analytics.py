from datetime import datetime, timezone
from typing import Any

def crowd_metrics(obs: dict, zone_cfg: dict) -> dict:
    count = int(obs.get("people_count", 0))
    area = obs.get("zone_area_m2") or zone_cfg.get("area_m2")
    capacity = max(int(zone_cfg.get("capacity_people", 1)), 1)
    density = (count / area) if area and area > 0 else None
    occupancy = count / capacity
    incoming = float(obs.get("incoming_per_min", 0))
    outgoing = float(obs.get("outgoing_per_min", 0))
    movement = float(obs.get("movement_score", 1))
    # Configurable prototype heuristics, not public-safety standards.
    if occupancy >= 1.0 or (density is not None and density >= 3.0):
        level = "CRITICAL"
    elif occupancy >= 0.80 or (density is not None and density >= 2.0) or movement < 0.25:
        level = "HIGH"
    elif occupancy >= 0.55 or (density is not None and density >= 1.0):
        level = "MODERATE"
    else:
        level = "LOW"
    flow_imbalance = incoming - outgoing
    return {
        "zone_id": obs["zone_id"], "people_count": count,
        "density_people_m2": round(density, 2) if density is not None else None,
        "occupancy_pct": round(occupancy * 100, 1), "risk": level,
        "incoming_per_min": incoming, "outgoing_per_min": outgoing,
        "flow_imbalance_per_min": round(flow_imbalance, 1),
        "movement_score": movement, "source": obs.get("source", "demo"),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

def traffic_metrics(obs: dict) -> dict:
    speed = float(obs.get("relative_speed_pct", 100))
    queue = float(obs.get("queue_seconds", 0))
    vehicles = int(obs.get("vehicle_count", 0))
    closed = bool(obs.get("closed", False))
    if closed or speed < 20 or queue >= 180:
        level = "SEVERE"
    elif speed < 40 or queue >= 120:
        level = "HEAVY"
    elif speed < 70 or queue >= 60:
        level = "MODERATE"
    else:
        level = "FREE"
    # Higher score means worse congestion; simple transparent MVP score.
    score = 100 if closed else min(100, round((100 - speed) * 0.65 + min(queue / 180, 1) * 25 + min(vehicles / 80, 1) * 10, 1))
    return {
        "road_id": obs["road_id"], "vehicle_count": vehicles,
        "relative_speed_pct": speed, "queue_seconds": queue,
        "closed": closed, "congestion": level, "congestion_score": score,
        "source": obs.get("source", "demo"),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

def flow_recommendation(metrics: dict) -> str:
    if metrics["risk"] in ("HIGH", "CRITICAL"):
        if metrics["flow_imbalance_per_min"] > 5:
            return "Consider metering entry and opening an alternate gate; operator review required."
        if metrics["movement_score"] < 0.25:
            return "Possible pedestrian bottleneck: inspect the zone and separate opposing flows."
        return "Deploy staff to assess the zone and consider controlled redistribution."
    if metrics["risk"] == "MODERATE":
        return "Monitor trend and prepare an alternate pedestrian route."
    return "No immediate crowd-flow action suggested."
