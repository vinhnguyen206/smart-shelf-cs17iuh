'''
* Copyright 2025 Vo Duong Khang [C]
*
* Licensed under the Apache License, Version 2.0 (the "License");
* you may not use this file except in compliance with the License.
* You may obtain a copy of the License at
*
*     http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS,
* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
* See the License for the specific language governing permissions and
* limitations under the License.
'''
import os
# Keep ultralytics fully offline: no version checks, no telemetry, and no
# model auto-download attempts — these hang for a long time with no internet.
os.environ.setdefault("YOLO_OFFLINE", "1")

from ultralytics import YOLO
import cv2
import numpy as np
from app.modules import globals
import time
import threading
from app.utils.sound_utils import play_sound
from app.modules.cloud_sync import post_order_data_to_cloud

def start_tracking_customer_behavior():
    customer_frame = None
    sound_file_path_1 = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/camera-connected.mp3"))
    sound_file_path_2 = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/init-model-success.mp3"))
    sound_file_path_3 = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/unpaid_warning.mp3"))
    sound_file_path_4 = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/warning-2.mp3"))
    frame_file_path = os.path.abspath(os.path.join(__file__, "../../..", "app/static/img/customer_frame/frame.jpg"))
    frame_box_file_path = os.path.abspath(os.path.join(__file__, "../../..", "app/static/img/customer_frame/frame_box.jpg"))
    frame_crop_file_path = os.path.abspath(os.path.join(__file__, "../../..", "app/static/img/customer_frame"))
    
    # ROI calibrated on the real shelf for the 640x480 capture below
    roi_x1, roi_y1 = 50, 0
    roi_x2, roi_y2 = 590, 480

    # No-person timeouts in wall-clock seconds. The old code counted loop
    # iterations (40/80/120), so the real duration changed whenever the
    # frame rate changed.
    NO_PERSON_WARN1_SEC = 20
    NO_PERSON_WARN2_SEC = 40
    NO_PERSON_UNPAID_SEC = 60
    ################# PC config #################
    # model_file_path = os.path.abspath(os.path.join(__file__, "../../..", "app/modules/detector/models/yolo11n-person-416-ver2.pt"))
    # model = YOLO(model_file_path)
    # model.overrides['verbose'] = False
    # cap = cv2.VideoCapture(0)
    # cap.set(cv2.CAP_PROP_FRAME_WIDTH, 416)
    # cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 416)

    ################# Jetson nano config #################
    model_file_path = os.path.abspath(os.path.join(__file__, "../../..", "app/modules/detector/models/yolo11n-person-640.engine"))
    if not os.path.exists(model_file_path):
        # Fail loudly instead of letting ultralytics try to download the
        # missing file from the internet
        print(f"ERROR: TensorRT engine not found: {model_file_path}")
        print("Build it on the Jetson: cd app/modules/detector/models && python3 convert-model.py")
        return
    model = YOLO(model_file_path)
    model.overrides['verbose'] = False
    # gst_pipeline = (
    #         "nvarguscamerasrc ! "
    #         "video/x-raw(memory:NVMM), width=416, height=416, framerate=30/1 ! "
    #         "nvvidconv ! "
    #         "video/x-raw, format=BGRx ! "
    #         "videoconvert ! "
    #         "video/x-raw, format=BGR ! appsink"
    #     )
    # cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
    ########################################################
    cap = cv2.VideoCapture("/dev/video0")  # for Jetson Nano with USB camera
    # Explicit capture mode: MJPG 640x480@30 keeps USB bandwidth and CPU
    # decode low; buffer size 1 (honored by V4L2) so cap.read() returns the
    # newest frame instead of a stale queued one.
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        print("Error: Could not open camera.")
        exit()

    ret, frame = cap.read()
    if ret:
        # init the model (load weights)
        model(frame)
        # threading.Thread(target=play_sound, args=(sound_file_path_2,)).start()

    no_person_since = None
    warn_stage = 0
    while True:
        if not globals.get_is_tracking():
            no_person_since = None
            warn_stage = 0
            customer_frame = None

            time.sleep(1)
            continue

        # cap.read() blocks until the camera delivers the next frame, so it
        # paces the loop by itself — no artificial sleep needed.
        ret, frame = cap.read()
        if not ret:
            print("Error: Can't read frame!")
            time.sleep(0.05)
            continue

        # classes=[0]: only "person"; conf=0.5 matches the old post-filter.
        results = model(frame, conf=0.5, classes=[0], verbose=False)

        person_detected = False

        # One batched GPU->CPU transfer instead of one sync per box field.
        for x1, y1, x2, y2 in results[0].boxes.xyxy.cpu().numpy():
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2

            # Check if person is in ROI
            if roi_x1 <= cx <= roi_x2 and roi_y1 <= cy <= roi_y2:
                person_detected = True

                if customer_frame is None:
                    customer_frame = frame.copy()
                    customer_frame_box = frame.copy()

                    label = "Customer"
                    x1, y1, x2, y2 = map(int, [x1, y1, x2, y2])
                    cv2.rectangle(customer_frame_box, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(customer_frame_box, label, (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                    cv2.imwrite(frame_box_file_path, customer_frame_box)
                break  # Only process first person in ROI

        if person_detected:
            no_person_since = None
            warn_stage = 0
        else:
            now = time.monotonic()
            if no_person_since is None:
                no_person_since = now
            elapsed = now - no_person_since

            if warn_stage == 0 and elapsed >= NO_PERSON_WARN1_SEC:
                warn_stage = 1
                threading.Thread(target=play_sound, args=(sound_file_path_3,), daemon=True).start()
            elif warn_stage == 1 and elapsed >= NO_PERSON_WARN2_SEC:
                warn_stage = 2
                threading.Thread(target=play_sound, args=(sound_file_path_3,), daemon=True).start()
            elif warn_stage == 2 and elapsed >= NO_PERSON_UNPAID_SEC:
                threading.Thread(target=play_sound, args=(sound_file_path_4,), daemon=True).start()
                globals.set_unpaid_customer_warning(True)

                # post order data with unpaid status
                order_id = str("HD"+str(int(time.time() * 1000)))
                shelf_id = os.getenv("SHELF_ID_CLOUD")

                order_details = []
                total_bill = 0

                for p, qty in zip(globals.get_products_data(), globals.get_taken_quantity()):
                    if qty > 0:
                        # Apply discount if exists
                        original_price = p.get("price", 0)
                        discount = p.get("discount", 0)

                        if discount > 0:
                            # Calculate discounted price
                            discounted_price = original_price * (1 - discount / 100)
                            discounted_price = round(discounted_price)
                        else:
                            discounted_price = original_price

                        total_price = qty * discounted_price

                        order_details.append({
                            "product_id": p.get("product_id", p.get("_id", "")),
                            "quantity": qty,
                            "price": discounted_price,  # Use discounted price
                            "total_price": total_price
                        })
                        total_bill += total_price

                order_data = {
                    'status': 'unpaid',
                    'order_code': order_id,
                    'shelf_id': shelf_id,
                    'total_bill': total_bill,
                    'orderDetails': order_details
                }
                #
                if customer_frame is None:
                    cv2.imwrite(frame_box_file_path, frame)
                # Try to post order data to cloud with error handling
                try:
                    print(f"Attempting to send unpaid order {order_id} to cloud...")
                    post_order_data_to_cloud(order_data)
                    print(f"Successfully sent unpaid order {order_id} to cloud")
                except Exception as e:
                    print(f"WARNING: Failed to send unpaid order to cloud: {e}")
                    print("Continuing without cloud sync...")

                no_person_since = None
                warn_stage = 0
                customer_frame = None

                globals.set_is_tracking(False)
                globals.set_payment_verified(True)

    cap.release()