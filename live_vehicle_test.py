import cv2
import time
import threading
from pathlib import Path
from ultralytics import YOLO

URL = "http://127.0.0.1:8081/"
ROOT = Path(__file__).resolve().parent
OBJECTS = {
    0: "person",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck"
}

lock = threading.Lock()
latest_frame = None
latest_annotated = None
frame_id = 0
processed_id = -1
running = True
last_error = ""

def capture_worker():
    global latest_frame, frame_id, running, last_error
    cap = cv2.VideoCapture(URL)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        last_error = "Cannot open phone stream"
        running = False
        return
    while running:
        ok, frame = cap.read()
        if not ok:
            last_error = "Camera read failed; reconnecting..."
            cap.release()
            time.sleep(0.5)
            cap = cv2.VideoCapture(URL)
            continue
        # Reduce the frame before inference to lower CPU load.
        frame = cv2.resize(frame, (640, 640), interpolation=cv2.INTER_AREA)
        with lock:
            latest_frame = frame
            frame_id += 1
            last_error = ""
    cap.release()

def inference_worker():
    global latest_annotated, processed_id, running, last_error
    try:
        model = YOLO(str(ROOT / "yolov8n.pt"))
        tracker = "bytetrack.yaml"
        while running:
            with lock:
                frame = None if latest_frame is None else latest_frame.copy()
                current_id = frame_id

            if frame is None or current_id == processed_id:
                time.sleep(0.01)
                continue

            try:
                result = model.track(
                    frame,
                    persist=True,
                    tracker=tracker,
                    classes=list(OBJECTS),
                    conf=0.30,
                    imgsz=640,
                    device="cpu",
                    verbose=False
                )[0]

                counts = {name: 0 for name in OBJECTS.values()}
                if result.boxes is not None:
                    for cls in result.boxes.cls.int().tolist():
                        name = OBJECTS.get(cls)
                        if name:
                            counts[name] += 1

                annotated = result.plot()
                summary = "  ".join(
                    f"{name}: {count}" for name, count in counts.items()
                )
                cv2.putText(
                    annotated, summary, (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2
                )
                with lock:
                    latest_annotated = annotated
                    processed_id = current_id
                    last_error = ""
            except Exception as exc:
                last_error = f"Inference error: {exc}"
                time.sleep(0.2)
    except Exception as exc:
        last_error = f"Model startup failed: {exc}"
        running = False

threading.Thread(target=capture_worker, daemon=True).start()
threading.Thread(target=inference_worker, daemon=True).start()

print("PS06 live tracking started. Press Q in the video window to stop.")
try:
    while running:
        with lock:
            display = None if latest_annotated is None else latest_annotated.copy()
            error = last_error

        if display is not None:
            if error:
                cv2.putText(
                    display, error[:75], (12, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2
                )
            cv2.imshow("PS06 Live Vehicle Tracking", display)
        elif error:
            print(error)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
        time.sleep(0.01)
finally:
    running = False
    cv2.destroyAllWindows()




