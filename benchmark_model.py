from pathlib import Path
import time
import cv2
from ultralytics import YOLO

root = Path(__file__).resolve().parent
image_path = root / "benchmark_frame.jpg"

cap = cv2.VideoCapture("http://127.0.0.1:8081")
if not cap.isOpened():
    raise SystemExit("Cannot open phone camera. Ensure the PS06 Camera app is running.")

ok, frame = cap.read()
cap.release()

if not ok:
    raise SystemExit("Camera opened but no frame arrived. Restart the phone camera app.")

cv2.imwrite(str(image_path), frame)
print("Captured test frame:", image_path)

model = YOLO(str(root / "yolo11s.pt"))
print("Warming up model...")
model.predict(source=frame, imgsz=640, conf=0.25, device="cpu", verbose=False)

start = time.perf_counter()
for _ in range(5):
    results = model.predict(source=frame, imgsz=640, conf=0.25, device="cpu", verbose=False)
print(f"Average inference: {(time.perf_counter() - start) / 5:.2f} seconds/frame")

print("Detected objects:")
for r in results:
    if r.boxes is not None:
        for cls, conf in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist()):
            print(f"  {r.names[int(cls)]}: {conf:.2f}")
