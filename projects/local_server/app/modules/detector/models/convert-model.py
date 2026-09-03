import os

from ultralytics import YOLO

# Run this ONCE on the Jetson Nano (TensorRT engines are GPU/TensorRT-version
# specific, so the .engine cannot be committed and reused across machines):
#   cd app/modules/detector/models && python3 convert-model.py
#
# Output: yolo11n-person-640.engine — the exact filename loaded by
# tracking_customer_behavior.py.

MODEL_DIR = os.path.dirname(os.path.abspath(__file__))

model = YOLO(os.path.join(MODEL_DIR, "yolo11n-person-640.pt"))

# half=True  -> FP16: ~2x faster than FP32 on Jetson Nano (Maxwell), no
#               meaningful accuracy loss for person detection.
# imgsz=416  -> smaller network input: person-in-ROI detection does not need
#               640; ~2.4x fewer pixels through the network.
# workspace=2 -> cap TensorRT build workspace (GB) so the 4GB Nano can build
#               the engine without OOM.
model.export(format="engine", half=True, imgsz=416, workspace=2, batch=1)

# Quick smoke test: load the engine the same way the app does.
trt_model = YOLO(os.path.join(MODEL_DIR, "yolo11n-person-640.engine"), task="detect")
print("Engine exported and loaded OK:", trt_model.predictor is None or "ready")
