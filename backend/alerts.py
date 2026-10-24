from datetime import datetime, timezone

def derive_alerts(crowd: dict, traffic: dict, existing: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    active_keys = {(a["source_type"], a["source_id"], a["title"]) for a in existing if a["status"] == "ACTIVE"}
    candidates = []
    for zone_id, m in crowd.items():
        if m["risk"] in ("HIGH", "CRITICAL"):
            candidates.append(("crowd", zone_id, f"{m['risk']} crowd risk at {zone_id}", m["risk"],
                              f"People: {m['people_count']}; occupancy: {m['occupancy_pct']}%. Inspect zone and assess alternate gate."))
    for road_id, m in traffic.items():
        if m["congestion"] in ("HEAVY", "SEVERE"):
            sev = "CRITICAL" if m["congestion"] == "SEVERE" else "HIGH"
            candidates.append(("traffic", road_id, f"{m['congestion']} congestion on {road_id}", sev,
                              f"Relative speed: {m['relative_speed_pct']}% of baseline; queue: {m['queue_seconds']}s. Review diversion options."))
    created = []
    for source_type, source_id, title, severity, message in candidates:
        key = (source_type, source_id, title)
        if key in active_keys:
            continue
        alert = {"id": f"AL-{len(existing)+len(created)+1:04d}", "source_type": source_type,
                 "source_id": source_id, "title": title, "severity": severity,
                 "message": message, "status": "ACTIVE", "created_at": now,
                 "acknowledged_at": None, "resolved_at": None, "operator_note": ""}
        created.append(alert)
        active_keys.add(key)
    return created
