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
import time
import os
from app.modules import globals
import keyboard
import numpy as np
import threading
from app.modules.cloud_sync import sync_all_from_cloud, post_history_added_products_to_cloud
from app.utils.file_utils import write_file
from app.utils.sound_utils import play_sound
from dotenv import load_dotenv

def start_listen_rfid():
    load_dotenv()
    rfid = ""
    print("Listening for RFID input...")
    sound_file_path_1 = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/adding-item.mp3"))
    sound_file_path_2 = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/added-item.mp3"))
    sound_file_path_3 = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/rfid_not_found.mp3"))
    sound_file_path_4 = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/loadcell_1_connection_error.mp3"))
    sound_file_path_5 = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/loadcell_2_connection_error.mp3"))
    pre_product_ids = [item["product_id"] for item in globals.get_products_data()]
    pre_verified_quantity = globals.get_verified_quantity()
    while True:
        event = keyboard.read_event()
        if event.event_type == keyboard.KEY_DOWN and event.name != 'enter':
            rfid += event.name
        elif keyboard.is_pressed('enter'):
            if rfid in globals.rfids:
                if not globals.bgm_220_1_connection:
                    print("BGM_220_1 connections are not established!")
                    threading.Thread(target=play_sound, args=(sound_file_path_4,)).start()
                    continue
                elif not globals.bgm_220_2_connection:
                    print("BGM_220_2 connections are not established!")
                    threading.Thread(target=play_sound, args=(sound_file_path_5,)).start()
                    continue
                else:
                    globals.rfid = rfid
                    rfid_state = globals.get_rfid_state()
                    rfid_state = 1 - rfid_state
                    globals.set_rfid_state(rfid_state) # swap state between 0 and 1
                    if rfid_state == 1: # adding
                        globals.set_is_tracking(False)  # stop tracking when adding products
                        threading.Thread(target=play_sound, args=(sound_file_path_1,)).start()
                        print("Load data from cloud")
                        try:
                            # All five requests run concurrently: worst case
                            # ~5s instead of 5 sequential timeouts (~25s)
                            sync_all_from_cloud()
                        except Exception as e:
                            print(f"Error loading data from cloud: {e}")
                    else : # added
                        threading.Thread(target=play_sound, args=(sound_file_path_2,)).start()
                        print("Save verified quantity to file")
                        verified_quantity = globals.get_verified_quantity()
                        loadcell_quantity = globals.get_loadcell_quantity_snapshot()
                        for i, q in enumerate(loadcell_quantity):
                            if q < 200:
                                verified_quantity[i] = q
                        globals.set_verified_quantity(verified_quantity)

                        verified_quantity_data = {
                            "name": "verified_quantity",
                            "values": verified_quantity
                        }
                        if isinstance(verified_quantity_data["values"], np.ndarray):
                            verified_quantity_data["values"] = verified_quantity_data["values"].tolist()
                        loadcell_file_path = os.path.abspath(os.path.join(__file__, "../../..", "database/loadcell.json"))
                        write_file(loadcell_file_path, verified_quantity_data)
                        # Post added product data to cloud
                        added_products_data = {
                            "shelf": os.getenv("SHELF_ID_CLOUD"),
                            "user_rfid": rfid,
                            "pre_products": pre_product_ids,
                            "post_products": [item["product_id"] for item in globals.get_products_data()],
                            "pre_verified_quantity": pre_verified_quantity,
                            "post_verified_quantity": verified_quantity,
                        }
                        pre_product_ids = [item["product_id"] for item in globals.get_products_data()]
                        pre_verified_quantity = verified_quantity
                        # Post in the background — the payload is already
                        # snapshotted, and the scan handler shouldn't wait on
                        # the network
                        def _post_history(data=added_products_data):
                            try:
                                post_history_added_products_to_cloud(data)
                            except Exception as e:
                                print(f"Error posting history added data to cloud: {e}")
                        threading.Thread(target=_post_history, daemon=True).start()

                    globals.bool_rfid_devices = True # send weight data and rfid state to devices, if rfid_state is 1 => send weight data
                    globals.bool_rfid = True
                    if rfid_state == 1:
                        print(f"RFID state 1 - Adding products")
                    else:
                        print(f"RFID state 0 - Added products")

            else:
                print("RFID not found!")
                print(globals.get_rfids())
                print(rfid)
                threading.Thread(target=play_sound, args=(sound_file_path_3,)).start()

            time.sleep(1)
            rfid = ""