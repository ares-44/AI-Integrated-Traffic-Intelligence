import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="PS06 Command Centre", page_icon="🚦", layout="wide")
API = st.sidebar.text_input("Backend API URL", "http://127.0.0.1:8000").rstrip("/")
st.title("🚦 PS06 | Integrated Traffic & Crowd Command Centre")
st.caption("Hackathon prototype · Use the demo seed button to load clearly labelled synthetic data.")
col_a, col_b = st.columns([1, 4])
with col_a:
    if st.button("Load demo scenario", type="primary", width="stretch"):
        try:
            r = requests.post(f"{API}/api/demo/seed", timeout=20)
            r.raise_for_status()
            st.success(r.json().get("message", "Demo loaded"))
            st.rerun()
        except requests.RequestException as e:
            st.error(f"Could not reach API: {e}")
try:
    response = requests.get(f"{API}/api/dashboard", timeout=5)
    response.raise_for_status()
    data = response.json()
except requests.RequestException as e:
    st.error(f"Backend unavailable at {API}. Start it with: uvicorn backend.main:app --reload --port 8000")
    st.stop()

zones = data["zones"]
roads = data["roads"]
alerts = data["alerts"]


def submit_crowd_observation(zone_name, people_count, movement_score, source):
    """Send measured video/camera counts to the backend crowd-observation API."""
    zone = next((z for z in zones if z.get("name") == zone_name), None)
    if zone is None:
        raise ValueError(f"Unknown venue zone: {zone_name}")
    payload = {
        "zone_id": zone["id"],
        "people_count": max(0, int(people_count)),
        "zone_area_m2": zone.get("area_m2"),
        "incoming_per_min": 0,
        "outgoing_per_min": 0,
        "movement_score": max(0.0, min(1.0, float(movement_score))),
        "source": source,
    }
    response = requests.post(f"{API}/api/crowd/observe", json=payload, timeout=10)
    response.raise_for_status()
    return response.json()
zone_metrics = [z["metrics"] for z in zones if z.get("metrics")]
road_metrics = [r["metrics"] for r in roads if r.get("metrics")]
critical_crowd = sum(m["risk"] == "CRITICAL" for m in zone_metrics)
high_traffic = sum(m["congestion"] in ("HEAVY", "SEVERE") for m in road_metrics)
active_alerts = sum(a["status"] == "ACTIVE" for a in alerts)
k1, k2, k3, k4 = st.columns(4)
k1.metric("Zones reporting", f"{len(zone_metrics)}/{len(zones)}")
k2.metric("Critical crowd zones", critical_crowd)
k3.metric("Heavy/severe roads", high_traffic)
k4.metric("Active alerts", active_alerts)
if data.get("demo_mode"):
    st.info("Prototype mode. Any row with source=demo is synthetic, not a live sensor observation.")

st.subheader("Live venue risk map")
st.caption("Schematic map: positions are illustrative, not GPS coordinates.")
map_df = pd.DataFrame([{
    "x": z.get("x", 50), "y": z.get("y", 50),
    "zone": z["name"], "risk": (z.get("metrics") or {}).get("risk", "NO DATA"),
    "people": (z.get("metrics") or {}).get("people_count", 0)
} for z in zones])
if not map_df.empty:
    st.scatter_chart(map_df, x="x", y="y", color="risk", size="people", height=300)

st.subheader("Crowd monitoring")
crowd_rows = []
for z in zones:
    m = z.get("metrics") or {}
    crowd_rows.append({
        "Zone": z["name"], "Count": m.get("people_count", "—"),
        "Density (people/m²)": m.get("density_people_m2", "—"),
        "Occupancy %": m.get("occupancy_pct", "—"), "Risk": m.get("risk", "NO DATA"),
        "Source": m.get("source", "—"),
        "Flow/min (in-out)": m.get("flow_imbalance_per_min", "—")
    })
st.dataframe(pd.DataFrame(crowd_rows), width="stretch", hide_index=True)

st.subheader("Traffic congestion")
traffic_rows = []
for r in roads:
    m = r.get("metrics") or {}
    traffic_rows.append({
        "Road": r["name"], "Vehicles": m.get("vehicle_count", 0),
        "Relative speed %": m.get("relative_speed_pct", 100),
        "Queue seconds": m.get("queue_seconds", 0), "Congestion": m.get("congestion", "NO DATA"),
        "Score": m.get("congestion_score", 0), "Closed": m.get("closed", False),
        "Source": m.get("source", "—")
    })
st.dataframe(pd.DataFrame(traffic_rows), width="stretch", hide_index=True)

st.subheader("Route recommendation")
r1, r2 = st.columns(2)
with r1:
    origin = st.selectbox("Origin intersection", ["J1", "J2", "J3", "J4", "VENUE"], index=0)
with r2:
    destination = st.selectbox("Destination", ["VENUE", "J1", "J2", "J3", "J4"], index=0)
if st.button("Calculate best available route"):
    try:
        route = requests.get(f"{API}/api/routes/recommend",
                             params={"origin": origin, "destination": destination}, timeout=5)
        route.raise_for_status()
        result = route.json()
        st.success(f"Route: {' → '.join(result['nodes'])} | estimated {result['estimated_minutes']} min (prototype estimate)")
        st.write("Road segments:", ", ".join(x["name"] for x in result["roads"]))
        st.caption(result["note"])
    except requests.RequestException as e:
        st.warning(f"Route unavailable: {e}")

st.subheader("Emergency route simulation")
with st.form("emergency_form"):
    vehicle_id = st.text_input("Emergency vehicle ID", "AMB-01")
    emergency_type = st.selectbox("Type", ["ambulance", "fire", "police", "other"])
    ec1, ec2 = st.columns(2)
    with ec1:
        eorigin = st.selectbox("Emergency origin", ["J1", "J2", "J3", "J4"], key="eo")
    with ec2:
        edest = st.selectbox("Emergency destination", ["VENUE", "J1", "J2", "J3", "J4"], key="ed")
    submitted = st.form_submit_button("Simulate priority route")
if submitted:
    try:
        res = requests.post(f"{API}/api/emergency/route",
                            json={"vehicle_id": vehicle_id, "emergency_type": emergency_type,
                                  "origin": eorigin, "destination": edest}, timeout=5)
        res.raise_for_status()
        ev = res.json()
        st.success(f"SIMULATION ONLY · Route: {' → '.join(ev['route'].get('nodes', []))}")
        st.write(ev["signal_priority"])
    except requests.RequestException as e:
        st.error(f"Could not calculate emergency route: {e}")

st.subheader("Alerts")
if not alerts:
    st.write("No alerts yet. Load the demo scenario to test alert logic.")
for alert in sorted(alerts, key=lambda a: {"CRITICAL": 0, "HIGH": 1, "WARNING": 2, "INFO": 3}.get(a["severity"], 4)):
    with st.expander(f"{alert['severity']} · {alert['title']} · {alert['status']}"):
        st.write(alert["message"])
        st.caption(f"Created: {alert['created_at']}")
        if alert["status"] == "ACTIVE":
            note = st.text_input("Operator note", key=f"note_{alert['id']}")
            ca, cr = st.columns(2)
            if ca.button("Acknowledge", key=f"ack_{alert['id']}"):
                try:
                    requests.post(f"{API}/api/alerts/{alert['id']}/acknowledge",
                                  json={"note": note}, timeout=5).raise_for_status()
                    st.rerun()
                except requests.RequestException as e:
                    st.error(str(e))
            if cr.button("Resolve", key=f"resolve_{alert['id']}"):
                try:
                    requests.post(f"{API}/api/alerts/{alert['id']}/resolve",
                                  json={"note": note}, timeout=5).raise_for_status()
                    st.rerun()
                except requests.RequestException as e:
                    st.error(str(e))

# ================= VIDEO-BASED CROWD DETECTION =================
st.subheader("Video-based crowd detection")
st.caption("Prototype YOLO tracking estimates movement between sampled frames. Results depend on camera angle and video quality.")

uploaded_video = st.file_uploader("Upload a crowd video", type=["mp4", "avi", "mov", "mkv"],
                                  key="ps06_crowd_video")

if uploaded_video is not None:
    zone_names = [z["name"] for z in zones]
    if not zone_names:
        st.warning("No venue zones are configured in the backend.")
    else:
        video_zone = st.selectbox("Select venue zone", zone_names, key="ps06_video_zone")
        if st.button("Analyze uploaded video", key="ps06_analyze_video"):
            import os
            import tempfile
            input_path = output_path = None
            cap = writer = None
            try:
                import cv2
                from ultralytics import YOLO

                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_in:
                    temp_in.write(uploaded_video.getvalue())
                    input_path = temp_in.name

                cap = cv2.VideoCapture(input_path)
                if not cap.isOpened():
                    raise ValueError("Could not open this video. Try another MP4 file.")

                fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if width <= 0 or height <= 0:
                    raise ValueError("The video has invalid dimensions.")

                sample_step = max(1, total_frames // 300) if total_frames > 0 else 1
                model = YOLO("yolov8n.pt")

                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_out:
                    output_path = temp_out.name
                writer = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*"mp4v"),
                                         max(1.0, fps / sample_step), (width, height))
                if not writer.isOpened():
                    raise RuntimeError("Could not create annotated video output.")

                progress = st.progress(0)
                status = st.empty()
                sampled_frames = total_detections = peak_count = frame_index = 0
                track_positions = {}
                track_displacements = {}
                direction_counts = {"left": 0, "right": 0, "up": 0, "down": 0}
                tracked_ids_seen = set()

                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if frame_index % sample_step == 0:
                        result = model.track(
                            frame, classes=[0], conf=0.35, persist=True,
                            tracker="bytetrack.yaml", verbose=False
                        )[0]
                        count = len(result.boxes)
                        sampled_frames += 1
                        total_detections += count
                        peak_count = max(peak_count, count)

                        # Track center points between sampled frames.
                        if result.boxes is not None and result.boxes.id is not None:
                            ids = result.boxes.id.int().cpu().tolist()
                            boxes = result.boxes.xyxy.cpu().tolist()
                            for track_id, box in zip(ids, boxes):
                                x1, y1, x2, y2 = box
                                center = ((x1 + x2) / 2, (y1 + y2) / 2)
                                tracked_ids_seen.add(track_id)
                                previous = track_positions.get(track_id)
                                if previous is not None:
                                    dx = center[0] - previous[0]
                                    dy = center[1] - previous[1]
                                    distance = (dx * dx + dy * dy) ** 0.5
                                    track_displacements[track_id] = (
                                        track_displacements.get(track_id, 0.0) + distance
                                    )
                                    if abs(dx) >= abs(dy) and abs(dx) > 2:
                                        direction_counts["right" if dx > 0 else "left"] += 1
                                    elif abs(dy) > 2:
                                        direction_counts["down" if dy > 0 else "up"] += 1
                                track_positions[track_id] = center

                        writer.write(result.plot())
                        if total_frames > 0:
                            progress.progress(min(1.0, frame_index / total_frames))
                        status.write(f"Analyzed frame {frame_index + 1} of {total_frames}")
                    frame_index += 1

                cap.release()
                cap = None
                writer.release()
                writer = None
                progress.progress(1.0)
                status.success("Video analysis complete.")

                average_count = total_detections / sampled_frames if sampled_frames else 0

                # Push the peak observed count into the selected zone's backend metrics.
                # This is a sampled-frame peak, not a unique-person count.
                video_track_count = len(tracked_ids_seen)
                moving_tracks = sum(distance > 12 for distance in track_displacements.values())
                video_movement_score = (
                    min(1.0, moving_tracks / max(1, video_track_count))
                    if video_track_count else 0.0
                )
                try:
                    observation_result = submit_crowd_observation(
                        video_zone, peak_count, video_movement_score, "video"
                    )
                    st.success(
                        f"Backend updated for {video_zone}: peak count {peak_count} "
                        f"(source=video). Refresh the dashboard metrics to verify."
                    )
                    with st.expander("Backend observation response"):
                        st.json(observation_result)
                except (requests.RequestException, ValueError) as api_exc:
                    st.error(
                        "Video analysis succeeded, but the backend zone update failed: "
                        f"{api_exc}"
                    )

                c1, c2, c3 = st.columns(3)
                c1.metric("Peak people detected", peak_count)
                c2.metric("Average per sampled frame", f"{average_count:.1f}")
                c3.metric("Frames analyzed", sampled_frames)

                st.markdown("**Crowd movement analysis (image-coordinate estimate)**")
                m1, m2, m3 = st.columns(3)
                m1.metric("Track IDs observed", len(tracked_ids_seen))
                moving_tracks = sum(distance > 12 for distance in track_displacements.values())
                m2.metric("Tracks with movement", moving_tracks)
                dominant_direction = max(direction_counts, key=direction_counts.get)
                direction_total = sum(direction_counts.values())
                m3.metric(
                    "Most observed direction",
                    dominant_direction.title() if direction_total else "Insufficient movement"
                )
                if direction_total:
                    st.caption(
                        "Direction is relative to the camera image, not compass direction. "
                        f"Direction observations: {direction_counts}."
                    )
                video_report = pd.DataFrame([
                    {"metric": "zone", "value": video_zone},
                    {"metric": "peak_people_detected", "value": peak_count},
                    {"metric": "average_detections_per_sampled_frame", "value": round(average_count, 2)},
                    {"metric": "frames_analyzed", "value": sampled_frames},
                    {"metric": "track_ids_observed", "value": len(tracked_ids_seen)},
                    {"metric": "tracks_with_movement", "value": moving_tracks},
                    {"metric": "dominant_direction_image_coordinates", "value": dominant_direction if direction_total else "insufficient movement"},
                    {"metric": "direction_observations", "value": str(direction_counts)},
                    {"metric": "threshold_note", "value": "30 detections is illustrative, not a validated safety limit"},
                ])
                st.download_button(
                    "Download crowd analysis report (CSV)",
                    data=video_report.to_csv(index=False).encode("utf-8"),
                    file_name="ps06_video_crowd_report.csv",
                    mime="text/csv",
                    key="ps06_video_report_csv",
                )
                if peak_count >= 30 and moving_tracks < max(1, len(track_displacements) // 4):
                    st.warning(
                        f"Possible crowd bottleneck in {video_zone}: high detected count "
                        "with limited observed movement. Review the footage; this is an "
                        "experimental indicator, not a validated safety alert."
                    )
                elif peak_count >= 30:
                    st.warning(f"Potential high crowd count in {video_zone}. Review footage and verify a venue-specific threshold.")
                else:
                    st.success(f"No high-count flag triggered for {video_zone}. This does not guarantee the area is safe.")

                with open(output_path, "rb") as result_file:
                    annotated_bytes = result_file.read()
                st.markdown("**Annotated video**")
                st.video(annotated_bytes)
                st.download_button("Download annotated video", data=annotated_bytes,
                                   file_name="ps06_annotated_crowd.mp4", mime="video/mp4")
            except Exception as exc:
                st.error(f"Video analysis failed: {exc}")
            finally:
                if cap is not None:
                    cap.release()
                if writer is not None:
                    writer.release()
                for path in (input_path, output_path):
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except OSError:
                            pass


# ================= LIVE CAMERA CROWD MONITORING =================
st.divider()
st.subheader("Live camera crowd monitoring")
st.caption(
    "Bounded camera sampling prototype. The camera is accessed by the machine running Streamlit. "
    "Counts are per sampled frame, not unique people; direction is relative to the image."
)

camera_mode = st.radio(
    "Camera source",
    ["Local webcam", "IP / RTSP camera"],
    horizontal=True,
    key="ps06_live_camera_mode",
)
camera_url = ""
if camera_mode == "IP / RTSP camera":
    camera_url = st.text_input(
        "Camera stream URL",
        placeholder="rtsp://your-camera-address/stream",
        help="Use only a camera stream you are authorized to access. Avoid sharing URLs containing passwords.",
        key="ps06_live_camera_url",
    )
capture_seconds = st.slider(
    "Capture duration (seconds)", min_value=5, max_value=20, value=10,
    key="ps06_live_camera_duration",
)
if st.button("Start camera capture and analyze", type="primary", key="ps06_start_camera_analysis"):
    import time
    import cv2
    from ultralytics import YOLO

    cap = None
    try:
        if camera_mode == "IP / RTSP camera":
            if not camera_url.strip():
                st.warning("Enter the authorized camera stream URL first.")
                st.stop()
            source = camera_url.strip()
            cap = cv2.VideoCapture(source)
        else:
            # DirectShow is usually more reliable for local webcams on Windows.
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(0)

        if not cap.isOpened():
            raise RuntimeError(
                "Could not open the camera. Check camera permissions, close apps using it, "
                "or verify the IP/RTSP stream URL."
            )

        model = YOLO("yolov8n.pt")
        frame_slot = st.empty()
        status_slot = st.empty()
        progress_slot = st.progress(0)
        total_detections = peak_count = sampled_frames = 0
        track_positions = {}
        track_displacements = {}
        tracked_ids_seen = set()
        direction_counts = {"left": 0, "right": 0, "up": 0, "down": 0}
        started = time.monotonic()
        last_frame = None

        while time.monotonic() - started < capture_seconds and sampled_frames < 250:
            ok, frame = cap.read()
            if not ok:
                # Avoid an unbounded loop if an RTSP feed disconnects.
                if sampled_frames == 0:
                    raise RuntimeError("Camera opened but no frames were received.")
                break

            # Process every second frame to keep CPU use manageable.
            if sampled_frames % 2 == 0:
                result = model.track(
                    frame, classes=[0], conf=0.35, persist=True,
                    tracker="bytetrack.yaml", verbose=False
                )[0]
                count = len(result.boxes)
                sampled_frames += 1
                total_detections += count
                peak_count = max(peak_count, count)

                if result.boxes is not None and result.boxes.id is not None:
                    ids = result.boxes.id.int().cpu().tolist()
                    boxes = result.boxes.xyxy.cpu().tolist()
                    for track_id, box in zip(ids, boxes):
                        x1, y1, x2, y2 = box
                        center = ((x1 + x2) / 2, (y1 + y2) / 2)
                        tracked_ids_seen.add(track_id)
                        previous = track_positions.get(track_id)
                        if previous is not None:
                            dx = center[0] - previous[0]
                            dy = center[1] - previous[1]
                            distance = (dx * dx + dy * dy) ** 0.5
                            track_displacements[track_id] = (
                                track_displacements.get(track_id, 0.0) + distance
                            )
                            if abs(dx) >= abs(dy) and abs(dx) > 2:
                                direction_counts["right" if dx > 0 else "left"] += 1
                            elif abs(dy) > 2:
                                direction_counts["down" if dy > 0 else "up"] += 1
                        track_positions[track_id] = center

                last_frame = result.plot()
                frame_slot.image(cv2.cvtColor(last_frame, cv2.COLOR_BGR2RGB),
                                 channels="RGB", caption="Annotated camera sample",
                                 width="stretch")
                elapsed = time.monotonic() - started
                progress_slot.progress(min(1.0, elapsed / capture_seconds))
                status_slot.write(
                    f"Capturing and analyzing… {min(capture_seconds, int(elapsed))}s / "
                    f"{capture_seconds}s · sampled frames: {sampled_frames}"
                )
            else:
                sampled_frames += 1

        cap.release()
        cap = None
        progress_slot.progress(1.0)
        status_slot.success("Camera sampling complete.")

        # Count metrics are based only on processed frames.
        c1, c2, c3 = st.columns(3)
        c1.metric("Peak people detected", peak_count)
        processed_frames = max(1, (sampled_frames + 1) // 2)
        c2.metric(
            "Average detections / processed frame",
            f"{total_detections / processed_frames:.1f}",
        )
        c3.metric("Track IDs observed", len(tracked_ids_seen))

        moving_tracks = sum(distance > 12 for distance in track_displacements.values())
        dominant_direction = max(direction_counts, key=direction_counts.get)

        camera_zone = st.selectbox(
            "Venue zone for this camera observation",
            [z["name"] for z in zones],
            key="ps06_camera_zone",
        )
        camera_track_count = len(tracked_ids_seen)
        camera_movement_score = (
            min(1.0, moving_tracks / max(1, camera_track_count))
            if camera_track_count else 0.0
        )
        try:
            observation_result = submit_crowd_observation(
                camera_zone, peak_count, camera_movement_score, "live"
            )
            st.success(
                f"Backend updated for {camera_zone}: peak count {peak_count} "
                "(source=live). Refresh the dashboard metrics to verify."
            )
            with st.expander("Backend observation response"):
                st.json(observation_result)
        except (requests.RequestException, ValueError) as api_exc:
            st.error(
                "Camera analysis succeeded, but the backend zone update failed: "
                f"{api_exc}"
            )
        direction_total = sum(direction_counts.values())
        d1, d2 = st.columns(2)
        d1.metric("Tracks with movement", moving_tracks)
        d2.metric(
            "Most observed direction",
            dominant_direction.title() if direction_total else "Insufficient movement",
        )
        if direction_total:
            st.caption(
                "Movement direction is relative to the camera image, not compass direction. "
                f"Direction observations: {direction_counts}."
            )
        camera_report = pd.DataFrame([
            {"metric": "camera_source_type", "value": camera_mode},
            {"metric": "peak_people_detected", "value": peak_count},
            {"metric": "average_detections_per_processed_frame", "value": round(total_detections / processed_frames, 2)},
            {"metric": "frames_processed", "value": processed_frames},
            {"metric": "track_ids_observed", "value": len(tracked_ids_seen)},
            {"metric": "tracks_with_movement", "value": moving_tracks},
            {"metric": "dominant_direction_image_coordinates", "value": dominant_direction if direction_total else "insufficient movement"},
            {"metric": "direction_observations", "value": str(direction_counts)},
            {"metric": "threshold_note", "value": "30 detections is illustrative, not a validated safety limit"},
        ])
        st.download_button(
            "Download camera analysis report (CSV)",
            data=camera_report.to_csv(index=False).encode("utf-8"),
            file_name="ps06_camera_crowd_report.csv",
            mime="text/csv",
            key="ps06_camera_report_csv",
        )
        if peak_count >= 30 and moving_tracks < max(1, len(track_displacements) // 4):
            st.warning(
                "Possible crowd bottleneck: high detected count with limited observed movement. "
                "Review the footage; this is an experimental indicator, not a validated safety alert."
            )
        elif peak_count >= 30:
            st.warning(
                "Potential high crowd count. Verify against a venue-specific threshold and review the footage."
            )
        else:
            st.info(
                "No high-count flag triggered by the illustrative threshold. This does not guarantee the area is safe."
            )
    except Exception as exc:
        st.error(f"Live camera analysis failed: {exc}")
    finally:
        if cap is not None:
            cap.release()


# ================= EMERGENCY EVENT LOG =================
st.subheader("Emergency event log")
if data["emergency_events"]:
    st.dataframe(pd.DataFrame([{
        "Vehicle": e["vehicle_id"], "Type": e["emergency_type"],
        "Route": " → ".join(e["route"].get("nodes", [])),
        "Mode": e["mode"], "Created": e["created_at"]
    } for e in data["emergency_events"]]), width="stretch", hide_index=True)
# ================= UNIFIED MAP SIMULATION =================
import math
import folium
from streamlit_folium import st_folium

st.divider()
st.header("🗺️ Integrated OpenStreetMap & Emergency Corridor Simulation")
st.caption("Combined with the existing crowd, thermal/video analysis, vehicle monitoring, alerts and emergency event dashboard.")

# Approximate campus/landmark coordinates for Greater Noida.
# Verify each pin before using it for real-world dispatch.
PLACES = {
    "ITS Engineering College": (28.469195, 77.488792),
    "Dronacharya Group of Institutions": (28.4755, 77.4845),
    "KCC Institute of Technology & Management": (28.4770, 77.4905),
    "Accurate Institute of Management & Technology": (28.4730, 77.4960),
    "Amity University Greater Noida": (28.4725, 77.4825),
    "Sharda University": (28.4744, 77.4830),
    "GL Bajaj Institute": (28.4750, 77.4920),
    "Greater Noida Institute of Technology (GNIOT)": (28.4770, 77.4935),
    "NIMT Greater Noida": (28.4565, 77.5010),
    "Knowledge Park II Metro": (28.4600, 77.5000),
    "Knowledge Park III": (28.4785, 77.4814),
    "Pari Chowk": (28.4670, 77.5130),
    "India Expo Centre": (28.4525, 77.5005),
}

SCENARIO_FACTOR = {
    "Normal traffic": 0.25,
    "College rush": 0.65,
    "Metro passenger surge": 0.70,
    "Festival / mass gathering": 0.85,
    "Road blockage / accident": 0.80,
    "Emergency response": 0.55,
}

COLLEGE_NAMES = [
    name for name in PLACES
    if name not in {
        "Knowledge Park II Metro",
        "Knowledge Park III",
        "Pari Chowk",
        "India Expo Centre",
    }
]


def clamp(value, low=0.0, high=1.0):
    return min(high, max(low, value))


@st.cache_data(ttl=60, show_spinner=False)
def get_routes(origin, destination):
    """Get real road-following geometry from the public OSRM router."""
    coordinates = (
        f"{origin[1]},{origin[0]};"
        f"{destination[1]},{destination[0]}"
    )
    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{coordinates}"
    )

    response = requests.get(
        url,
        params={
            "overview": "full",
            "geometries": "geojson",
            "alternatives": "3",
            "steps": "true",
        },
        timeout=15,
        headers={"User-Agent": "PS06-Traffic-Crowd-Simulator/1.0"},
    )
    response.raise_for_status()
    data = response.json()

    if data.get("code") != "Ok":
        return []

    return data.get("routes", [])


def risk_for_place(
    is_hotspot,
    density_norm,
    traffic_norm,
    flow_norm,
    demand_norm,
):
    """
    Transparent illustrative risk score in [0, 1].
    Without live sensor feeds, this is a scenario estimate, not
    a measured real-world traffic risk.
    """
    local_density = density_norm if is_hotspot else 0.0
    local_flow = flow_norm if is_hotspot else 0.5 * flow_norm

    return clamp(
        0.5 * local_density
        + 0.3 * max(traffic_norm, demand_norm)
        + 0.2 * local_flow
    )


# ---------------- Sidebar controls ----------------
with st.sidebar:
    st.header("Scenario configuration")

    scenario = st.selectbox("Scenario", list(SCENARIO_FACTOR))

    journey_options = list(PLACES)
    origin_name = st.selectbox(
        "Journey start",
        journey_options,
        index=0,
    )
    destination_name = st.selectbox(
        "Final destination",
        journey_options,
        index=journey_options.index("Pari Chowk"),
    )
    crowd_name = st.selectbox(
        "Crowd hotspot",
        journey_options,
        index=journey_options.index("Knowledge Park III"),
    )

    crowd_count = st.number_input(
        "Estimated people at hotspot",
        min_value=0,
        max_value=200000,
        value=1200,
        step=100,
    )
    usable_area = st.number_input(
        "Usable crowd area (m²)",
        min_value=1.0,
        max_value=1000000.0,
        value=600.0,
        step=50.0,
    )
    traffic_demand = st.slider("Traffic demand (%)", 0, 100, 45)
    crowd_flow = st.slider("Crowd-flow / bottleneck (%)", 0, 100, 35)
    reference_speed = st.slider(
        "Reference free-flow speed (km/h)", 10, 80, 40
    )
    measured_speed = st.slider(
        "Scenario average speed (km/h)", 0, 80, 25
    )

    block_road = st.checkbox(
        "Simulate road closure",
        value=(scenario == "Road blockage / accident"),
    )
    emergency_priority = st.checkbox(
        "Highlight emergency corridor",
        value=(scenario == "Emergency response"),
    )

    show_all_places = st.checkbox("Show all campus/landmark pins", value=True)
    zoom = st.slider("Map zoom", 11, 18, 14)

    st.caption("Internet is required for map tiles and OSRM routes.")
    run = st.button(
        "Run / refresh simulation",
        type="primary",
        use_container_width=True,
    )

# Prevent a previously checked emergency toggle from coloring normal journeys.
# Emergency highlighting is active only for the Emergency response scenario.
emergency_priority_active = emergency_priority and scenario == "Emergency response"

# ---------------- Mathematical scenario model ----------------
scenario_factor = SCENARIO_FACTOR[scenario]
demand_norm = clamp(traffic_demand / 100.0)
demand = max(demand_norm, scenario_factor)

flow = max(
    crowd_flow / 100.0,
    scenario_factor if "gathering" in scenario.lower() else 0.0,
)

congestion = (
    clamp(1.0 - measured_speed / reference_speed)
    if reference_speed > 0
    else 1.0
)

density = crowd_count / usable_area
density_norm = clamp(density / 4.0)
traffic_norm = clamp(max(congestion, demand))
flow_norm = clamp(flow)

zone_risk = clamp(
    0.5 * density_norm
    + 0.3 * traffic_norm
    + 0.2 * flow_norm
)

origin = PLACES[origin_name]
destination = PLACES[destination_name]

# ---------------- Retrieve mapped-road routes ----------------
routes = []
routing_error = None

if origin_name == destination_name:
    routing_error = "Select different start and destination locations."
else:
    try:
        with st.spinner("Finding routes along mapped roads..."):
            routes = get_routes(origin, destination)

        # Normal routing always prioritizes the shortest returned route.
        # Crowd overlay is visual-only and must not keep a previous route active.
        routes = sorted(
            routes,
            key=lambda r: r.get("distance", float("inf")),
        )

        if not routes:
            routing_error = "No route returned. Try again or select another place."

    except requests.exceptions.Timeout:
        routing_error = "Routing timed out. The map will still load."
    except requests.exceptions.RequestException as exc:
        routing_error = f"Routing service unavailable: {exc}"
    except (ValueError, KeyError) as exc:
        routing_error = f"Could not read routing response: {exc}"

# Emergency corridor: choose the fastest returned road route.
# This is a simulated priority selection, not emergency dispatch.
emergency_route = (
    min(routes, key=lambda r: r.get("duration", float("inf")))
    if routes else None
)

# ---------------- Dashboard layout ----------------
left, right = st.columns([1, 2])

with left:
    st.subheader("Live scenario indicators")

    a, b = st.columns(2)
    a.metric("Crowd density", f"{density:.2f} people/m²")
    b.metric("Congestion index", f"{congestion:.2f}")

    a, b = st.columns(2)
    a.metric("Zone risk", f"{zone_risk:.3f} / 1.0")
    b.metric("Traffic demand", f"{traffic_demand}%")

    st.markdown("#### Route results")

    if routes:
        shortest = routes[0]
        st.write(
            f"**Shortest returned route:** "
            f"{shortest['distance'] / 1000:.2f} km"
        )
        st.write(
            f"**Estimated time:** {shortest['duration'] / 60:.1f} min"
        )

        if len(routes) > 1:
            alt = routes[1]
            st.write(
                f"**Alternative:** {alt['distance'] / 1000:.2f} km"
                f" · {alt['duration'] / 60:.1f} min"
            )
        else:
            st.caption("Only one route was returned by OSRM.")

        if emergency_priority_active and emergency_route:
            st.write(
                f"**Emergency corridor estimate:** "
                f"{emergency_route['distance'] / 1000:.2f} km"
                f" · {emergency_route['duration'] / 60:.1f} min"
            )
    elif routing_error:
        st.warning(routing_error)

    st.markdown("#### R-risk scoring method")
    st.code(
        "Density = people / usable_area\n"
        "D_norm = min(1, Density / 4)\n"
        "C = clamp(1 - speed / reference_speed)\n"
        "R = 0.5*D_norm + 0.3*T_norm + 0.2*F_norm\n"
        "R is clamped to [0, 1]",
        language="text",
    )

    st.caption(
        "T_norm uses the larger of scenario congestion and selected "
        "traffic demand. F_norm represents the selected crowd-flow "
        "bottleneck. These are configurable demonstration assumptions."
    )

    if block_road:
        st.warning(
            "Closure scenario is enabled. OSRM does not receive a specific "
            "blocked road in this version, so a displayed route may still "
            "pass through the simulated closure."
        )

    if emergency_priority_active:
        st.info(
            "Magenta highlights the fastest route returned by the routing "
            "service as a simulated emergency corridor. Real ambulance or "
            "government dispatch requires verified road access, live closures, "
            "and authorized operational data."
        )


with right:
    st.subheader("OpenStreetMap • Traffic-risk & emergency map")

    m = folium.Map(
        location=CENTER if "CENTER" in globals() else PLACES["ITS Engineering College"],
        zoom_start=zoom,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    # Campus/landmark pins.
    for name, coord in PLACES.items():
        if show_all_places or name in {
            origin_name, destination_name, crowd_name
        }:
            folium.CircleMarker(
                location=coord,
                radius=5,
                color="#eab308",
                weight=2,
                fill=True,
                fill_color="#facc15",
                fill_opacity=0.9,
                tooltip=name,
                popup=name,
            ).add_to(m)

    # Calculate risk scores for the table only; no red R markers are drawn.
    risk_rows = []
    for name, coord in PLACES.items():
        is_hotspot = name == crowd_name
        score = risk_for_place(
            is_hotspot,
            density_norm,
            traffic_norm,
            flow_norm,
            demand_norm,
        )

        if is_hotspot:
            reason = (
                f"Selected crowd hotspot: {crowd_count:,} people over "
                f"{usable_area:,.0f} m² ({density:.2f} people/m²)"
            )
        else:
            reason = (
                f"Scenario-wide traffic demand {traffic_demand}%, "
                f"congestion index {congestion:.2f}; no local crowd "
                f"count supplied for this location"
            )

        risk_rows.append({
            "Place": name,
            "R score": round(score, 3),
            "Reason": reason,
        })

    # Show crowd hotspot radius as an illustrative zone.
    crowd_coord = PLACES[crowd_name]
    folium.Circle(
        location=crowd_coord,
        radius=max(20, min(500, math.sqrt(usable_area / math.pi))),
        color="#dc2626",
        weight=2,
        fill=True,
        fill_color="#ef4444",
        fill_opacity=0.18,
        tooltip=(
            f"Crowd zone: {crowd_count:,} people; "
            f"density {density:.2f} people/m²"
        ),
    ).add_to(m)

    # Start and destination markers.
    folium.Marker(
        origin,
        tooltip=f"START: {origin_name}",
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(m)

    folium.Marker(
        destination,
        tooltip=f"DESTINATION: {destination_name}",
        icon=folium.Icon(color="blue", icon="flag"),
    ).add_to(m)

    # Real road-following route geometry returned by OSRM.
    route_colors = ["#1685ff", "#00a86b", "#f59e0b"]

    if emergency_priority_active and emergency_route:
        geometry = emergency_route.get("geometry", {}).get("coordinates", [])
        if geometry:
            coords = [(lat, lon) for lon, lat in geometry]
            folium.PolyLine(
                coords,
                color="#d946ef",
                weight=9,
                opacity=0.95,
                tooltip=(
                    "EMERGENCY PRIORITY CORRIDOR (simulated) | "
                    f"{emergency_route['distance'] / 1000:.2f} km"
                ),
            ).add_to(m)

    # Display shortest route and alternatives.
    for index, route in enumerate(routes[:3]):
        geometry = route.get("geometry", {}).get("coordinates", [])
        if not geometry:
            continue

        coords = [(lat, lon) for lon, lat in geometry]
        color = route_colors[index % len(route_colors)]

        # If the emergency route is already drawn, avoid covering it
        # with an identical route line.
        if emergency_priority_active and route is emergency_route:
            continue

        folium.PolyLine(
            coords,
            color=color,
            weight=6 if index == 0 else 4,
            opacity=0.88,
            tooltip=(
                f"{'Shortest returned route' if index == 0 else f'Alternative {index}'}"
                f" | {route['distance'] / 1000:.2f} km"
                f" | {route['duration'] / 60:.1f} min"
            ),
        ).add_to(m)

    # RED CROWD ACCESS ROUTE:
    # Do not color the entire journey red. Find the nearest point on the
    # selected blue route, then ask OSRM for the short road route from that
    # point to the selected crowded hotspot. This creates the red spur shown
    # in the intended design (the road one would take to reach the crowd).
    # It appears only while the hotspot has a non-zero simulated crowd.
    if crowd_count > 0 and routes:
        crowd_coord = PLACES[crowd_name]
        main_geometry = routes[0].get("geometry", {}).get("coordinates", [])

        if main_geometry:
            # OSRM GeoJSON points are [longitude, latitude].
            main_route_points = [(lat, lon) for lon, lat in main_geometry]

            # Find the nearest point on the selected route to the hotspot.
            def distance_metres(a, b):
                lat1, lon1 = map(math.radians, a)
                lat2, lon2 = map(math.radians, b)
                dlat = lat2 - lat1
                dlon = lon2 - lon1
                h = (
                    math.sin(dlat / 2) ** 2
                    + math.cos(lat1) * math.cos(lat2)
                    * math.sin(dlon / 2) ** 2
                )
                return 2 * 6371000 * math.asin(math.sqrt(min(1.0, h)))

            nearest_route_point = min(
                main_route_points,
                key=lambda point: distance_metres(point, crowd_coord),
            )
            nearest_distance = distance_metres(nearest_route_point, crowd_coord)

            # Avoid drawing a misleading connector if the selected journey
            # is too far from the hotspot. A 1.2 km threshold is illustrative.
            if nearest_distance <= 1200:
                try:
                    access_routes = get_routes(nearest_route_point, crowd_coord)
                    if access_routes:
                        # Use the shortest returned road route for the red spur.
                        access_route = min(
                            access_routes,
                            key=lambda route: route.get("distance", float("inf")),
                        )
                        access_geometry = access_route.get("geometry", {}).get("coordinates", [])

                        if len(access_geometry) >= 2:
                            folium.PolyLine(
                                [(lat, lon) for lon, lat in access_geometry],
                                color="#ef2929",
                                weight=8,
                                opacity=0.98,
                                tooltip=(
                                    f"SIMULATED CROWD ACCESS ROUTE to {crowd_name} "
                                    f"| {crowd_count:,} people"
                                ),
                            ).add_to(m)
                except requests.exceptions.RequestException:
                    st.warning(
                        "Could not fetch the red crowd-access route. "
                        "The main journey route is still displayed."
                    )
            else:
                st.info(
                    f"The selected journey passes about {nearest_distance:.0f} m "
                    f"from {crowd_name}. No red access route is drawn because "
                    "the hotspot is too far from this journey."
                )

    folium.LayerControl().add_to(m)

    st_folium(
        m,
        height=650,
        use_container_width=True,
        returned_objects=[],
    )

st.subheader("Traffic-risk locations")
st.dataframe(
    risk_rows,
    use_container_width=True,
    hide_index=True,
)

st.caption(
    "Map base and route geometry use OpenStreetMap and OSRM. Campus "
    "coordinates are approximate and must be verified. R scores are "
    "scenario calculations, not live traffic observations. This version "
    "does not automatically detect congestion, crowds, blocked roads, "
    "or provide a verified emergency dispatch route."
)
