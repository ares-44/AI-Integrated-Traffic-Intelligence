# PS06 — AI-Powered Integrated Traffic and Crowd Management Platform

A hackathon starter MVP for an integrated event traffic and crowd command centre.

## Current implementation
- FastAPI backend with a shared system state and REST endpoints.
- Crowd analytics using person detections supplied to the analytics engine; optional YOLO/OpenCV video adapter.
- Traffic congestion scoring from vehicle count, relative speed, and queue persistence.
- Demo venue map represented as a configurable road graph.
- Dynamic route recommendations using NetworkX shortest paths.
- Emergency route requests with simulated signal-priority decisions.
- Rule-based alerts with persistence, duplicate suppression, acknowledgement, and resolution.
- Crowd-flow indicators from zone movement inputs.
- Streamlit dashboard consuming the backend API.
- Clearly labelled demo data so simulated inputs are not mistaken for live sensor readings.

## Important limitations
This is a prototype, not a certified public-safety system. Density and speed metrics require calibration. Video detections can be inaccurate under occlusion, low light, or dense crowds. Emergency routes and signal-priority actions are recommendations/simulations only; do not connect this prototype to real traffic infrastructure.

## Setup (Windows PowerShell)
```powershell
cd PS06_Traffic_Crowd_Platform
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Terminal 1 — API:
```powershell
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — dashboard:
```powershell
streamlit run dashboard/app.py
```

API docs: http://127.0.0.1:8000/docs
Dashboard: Streamlit prints its local URL, usually http://localhost:8501.

## Video input
The first MVP supports demo data and an optional uploaded video analysis endpoint. To use YOLO:
1. Install the packages in `requirements-video.txt`.
2. Place a compatible Ultralytics model at `models/yolo11n.pt` or set `YOLO_MODEL`.
3. Use `/api/video/analyze` with a video file.
The detector is optional so the rest of the platform runs without downloading model weights.

## Project layout
- `backend/` API and analytics modules
- `dashboard/` Streamlit command-centre UI
- `config/venue.json` demo venue and road graph
- `tests/` basic logic tests
