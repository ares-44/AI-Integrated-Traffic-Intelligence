import requests
import pandas as pd
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="PS06 Command Centre", page_icon="🚦", layout="wide")
API = st.sidebar.text_input("Backend API URL", "http://127.0.0.1:8000").rstrip("/")
st.title("🚦 PS06 | Integrated Traffic & Crowd Command Centre")
st.caption("Hackathon prototype · Use the demo seed button to load clearly labelled synthetic data.")


def render_detection_heatmap(frame_shape, centers, alpha=0.58, background_frame=None):
    """Return a heatmap image overlaid on a real frame from the uploaded video."""
    import cv2
    import numpy as np

    height, width = frame_shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("Invalid video frame dimensions")

    density = np.zeros((height, width), dtype=np.float32)
    radius = max(14, min(width, height) // 32)
    for x, y in centers:
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < width and 0 <= yi < height:
            cv2.circle(density, (xi, yi), radius, 1.0, -1)

    density = cv2.GaussianBlur(
        density, (0, 0), sigmaX=max(8, width / 55), sigmaY=max(8, height / 55)
    )
    max_value = float(density.max())
    if max_value > 0:
        density = density / max_value

    heat_bgr = cv2.applyColorMap((density * 255).astype(np.uint8), cv2.COLORMAP_JET)
    # Hide the low-density blue tint so the underlying sample video remains visible.
    mask = np.clip(density * 2.8, 0.0, 1.0)[..., None] * alpha
    if background_frame is not None:
        base = background_frame
        if base.shape[:2] != (height, width):
            base = cv2.resize(base, (width, height))
        if len(base.shape) == 2:
            base = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
        result = base.astype(np.float32) * (1.0 - mask) + heat_bgr.astype(np.float32) * mask
    else:
        result = heat_bgr.astype(np.float32) * mask
    return cv2.cvtColor(np.clip(result, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)

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
    try:
        import plotly.express as px
        # Zones are illustrative coordinates; this is a demo density heatmap, not GPS data.
        map_df["density"] = pd.to_numeric(map_df["people"], errors="coerce").fillna(0)
        fig = px.density_heatmap(
            map_df, x="x", y="y", z="density", nbinsx=18, nbinsy=12,
            histfunc="avg", color_continuous_scale="YlOrRd", title="Crowd intensity by zone"
        )
        fig.add_scatter(
            x=map_df["x"], y=map_df["y"], mode="markers+text",
            text=map_df["zone"] + "<br>" + map_df["people"].astype(str) + " people",
            textposition="top center", marker={"size": 13, "color": "#102a43", "line": {"color": "white", "width": 1}},
            name="Venue zones"
        )
        fig.update_layout(height=380, xaxis_title="Illustrative venue X", yaxis_title="Illustrative venue Y")
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
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
                # Live heatmap of detected people from the same uploaded video.
                heat_centers = []
                last_heatmap_frame = None
                st.markdown("**Live heatmap from this video**")
                st.caption("Hotter regions show where person detections accumulate in sampled frames; these are video-image coordinates, not GPS density.")
                heatmap_slot = st.empty()
                heatmap_update_every = 5

                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if frame_index % sample_step == 0:
                        last_heatmap_frame = frame.copy()
                        result = model.track(
                            frame, classes=[0], conf=0.35, persist=True,
                            tracker="bytetrack.yaml", verbose=False
                        )[0]
                        count = len(result.boxes) if result.boxes is not None else 0
                        sampled_frames += 1
                        total_detections += count
                        peak_count = max(peak_count, count)

                        # Accumulate detected-person centers and refresh the heatmap while the video is processed.
                        if result.boxes is not None and len(result.boxes) > 0:
                            for x1, y1, x2, y2 in result.boxes.xyxy.cpu().tolist():
                                heat_centers.append(((x1 + x2) / 2, (y1 + y2) / 2))
                        if sampled_frames % heatmap_update_every == 0 and heat_centers:
                            try:
                                heat_image = render_detection_heatmap(frame.shape, heat_centers, background_frame=frame)
                                heatmap_slot.image(heat_image, caption=f"Live crowd heatmap · {sampled_frames} sampled frames", use_container_width=True)
                            except Exception as heat_exc:
                                heatmap_slot.warning(f"Could not render crowd heatmap image: {heat_exc}")

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
                # Always render the final accumulated heatmap, including short clips.
                if heat_centers:
                    try:
                        final_base = last_heatmap_frame if last_heatmap_frame is not None else frame
                        final_heat_image = render_detection_heatmap(final_base.shape, heat_centers, background_frame=final_base)
                        heatmap_slot.image(final_heat_image, caption=f"Final crowd heatmap · {sampled_frames} sampled frames", use_container_width=True)
                    except Exception as heat_exc:
                        heatmap_slot.warning(f"Could not render final crowd heatmap image: {heat_exc}")

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


# ================= DEMO VIDEO LIVE VEHICLE MONITORING =================
st.divider()
st.subheader("🚘 Live vehicle monitoring — demo video")
st.caption(
    "Upload a traffic clip and process it frame by frame. Bounding boxes and counts update while it runs. "
    "This is video-based prototype detection, not a live road sensor feed."
)
vehicle_video = st.file_uploader(
    "Choose a traffic demo video", type=["mp4", "avi", "mov", "mkv"], key="ps06_vehicle_video"
)
if vehicle_video is not None:
    st.video(vehicle_video)
    st.caption("The original clip is shown above. Start analysis to see annotated frames and vehicle counts update below.")
    vehicle_conf = st.slider("Vehicle detection confidence", 0.15, 0.80, 0.30, 0.05, key="ps06_vehicle_conf")
    if st.button("▶ Run live vehicle detection on this video", type="primary", key="ps06_run_vehicle_video"):
        import os
        import tempfile
        cap = None
        temp_path = None
        try:
            import cv2
            from ultralytics import YOLO
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(vehicle_video.name).suffix or ".mp4") as temp_file:
                temp_file.write(vehicle_video.getvalue())
                temp_path = temp_file.name
            cap = cv2.VideoCapture(temp_path)
            if not cap.isOpened():
                raise RuntimeError("Could not open the uploaded video. Try a standard MP4 clip.")
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            model = YOLO("yolov8n.pt")
            frame_view = st.empty()
            count_view = st.empty()
            status_view = st.empty()
            progress = st.progress(0)
            # COCO classes: car=2, motorcycle=3, bus=5, truck=7
            vehicle_classes = [2, 3, 5, 7]
            class_names = {2: "Car", 3: "Motorcycle", 5: "Bus", 7: "Truck"}
            processed = 0
            peak_vehicles = 0
            class_totals = {name: 0 for name in class_names.values()}
            vehicle_centers = []
            last_vehicle_frame = None
            frame_stride = max(1, round(fps / 8))  # target ~8 processed frames/sec of source footage
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                frame_no = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                if frame_no % frame_stride != 0:
                    continue
                last_vehicle_frame = frame.copy()
                result = model.track(
                    frame, classes=vehicle_classes, conf=vehicle_conf,
                    persist=True, tracker="bytetrack.yaml", verbose=False
                )[0]
                boxes = result.boxes
                current_count = len(boxes) if boxes is not None else 0
                peak_vehicles = max(peak_vehicles, current_count)
                if boxes is not None and boxes.cls is not None:
                    for xyxy in boxes.xyxy.cpu().tolist():
                        x1, y1, x2, y2 = xyxy
                        vehicle_centers.append(((x1 + x2) / 2, (y1 + y2) / 2))
                    for cls_id in boxes.cls.int().cpu().tolist():
                        name = class_names.get(cls_id, "Vehicle")
                        class_totals[name] = class_totals.get(name, 0) + 1
                annotated = result.plot()
                annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                frame_view.image(annotated_rgb, caption=f"Processed video frame {frame_no}", use_container_width=True)
                with count_view.container():
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Vehicles in current frame", current_count)
                    c2.metric("Peak vehicles in one frame", peak_vehicles)
                    c3.metric("Frames processed", processed + 1)
                    st.write("Per-frame detections by class")
                    st.dataframe(pd.DataFrame([{"Vehicle type": k, "Detections across processed frames": v} for k, v in class_totals.items()]), hide_index=True, use_container_width=True)
                processed += 1
                if total_frames > 0:
                    progress.progress(min(1.0, frame_no / total_frames))
                status_view.caption(f"Analysing video… frame {frame_no:,} / {total_frames:,}" if total_frames else f"Analysing video… frame {frame_no:,}")
            cap.release()
            cap = None
            progress.progress(1.0)
            status_view.success(f"Analysis complete: {processed} frames processed. Vehicle counts are detections across frames, not unique vehicle totals.")
            st.markdown("### Traffic heatmap from the same demo video")
            st.caption("Hotter areas show where vehicle detections accumulated in the sampled video frames; image coordinates are not GPS coordinates.")
            if vehicle_centers:
                try:
                    vehicle_base = last_vehicle_frame if last_vehicle_frame is not None else frame
                    vehicle_heat_image = render_detection_heatmap(vehicle_base.shape, vehicle_centers, background_frame=vehicle_base)
                    st.image(vehicle_heat_image, caption="Vehicle detection heatmap generated from the uploaded video", use_container_width=True)
                except Exception as heat_exc:
                    st.warning(f"Could not render vehicle heatmap image: {heat_exc}")
            else:
                st.info("No vehicles were detected in the sampled frames, so no heatmap was generated.")
            st.download_button(
                "Download vehicle detection summary (CSV)",
                data=pd.DataFrame([{"vehicle_type": k, "detections_across_processed_frames": v} for k, v in class_totals.items()]).to_csv(index=False).encode("utf-8"),
                file_name="ps06_vehicle_detection_summary.csv", mime="text/csv", key="ps06_vehicle_summary_download"
            )
        except Exception as exc:
            st.error(f"Vehicle video analysis failed: {exc}. Ensure opencv-python and ultralytics are installed and the model can be downloaded.")
        finally:
            if cap is not None:
                cap.release()
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
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
