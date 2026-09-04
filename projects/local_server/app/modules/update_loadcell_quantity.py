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
import time
import threading
import asyncio
import json
import random
from datetime import datetime

import numpy as np
from dotenv import load_dotenv
from bleak import BleakClient, BleakError
import paho.mqtt.client as mqtt
from app.modules import globals
from app.utils import ble_lock
from app.utils.loadcell_ws_utils import emit_connected_status
from app.utils.websocket_utils import emit_loadcell_update
from app.utils.database_utils import load_products_from_json
from app.utils.loadcell_utils import update_cart_with_combo_pricing
from app.utils.file_utils import write_file
from app.utils.sound_utils import play_sound, speech_text

load_dotenv()

# MQTT Client
# Create MQTT client using WebSocket
client = mqtt.Client(client_id=os.getenv("SHELF_ID"),transport="websockets")

# MQTT Callbacks
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ MQTT Connected successfully!")
    else:
        print(f"❌ MQTT Connection failed with code {rc}")

def on_disconnect(client, userdata, rc):
    if rc != 0:
        # loop_start()'s network thread reconnects on its own; calling
        # client.reconnect() from inside this callback runs on that same
        # thread and can block/deadlock it on a flaky link
        print(f"⚠️ MQTT Unexpected disconnect: {rc}. Auto-reconnect will retry...")

def on_publish(client, userdata, mid):
    pass  # Silently confirm publish

# Assign callbacks
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_publish = on_publish

# Connect to HiveMQ WebSocket broker (cloud)
try:
    client.connect(os.getenv("BROKER_URL"), int(os.getenv("BROKER_PORT")), 60)
    client.loop_start()  # Start background thread for network loop
    print("🔄 MQTT background loop started")
except Exception as e:
    print(f"❌ Error connecting to MQTT broker: {e}")
# ADDRESS UUIDs
BGM220_LOADCELL_1_ADDRESS = os.getenv("BGM220_LOADCELL_1_ADDRESS")
BGM220_LOADCELL_2_ADDRESS = os.getenv("BGM220_LOADCELL_2_ADDRESS")

LOADCELL_UUID = os.getenv("LOADCELL_UUID")
CHAR_UUID_WRITE_WEIGHT = os.getenv("CHAR_UUID_WRITE_WEIGHT")
CHAR_UUID_WRITE_SAVE_QUANTITY = os.getenv("CHAR_UUID_WRITE_SAVE_QUANTITY")
CHAR_UUID_PRODUCT_NAME = os.getenv("CHAR_UUID_PRODUCT_NAME")
CHAR_UUID_PRODUCT_PRICE = os.getenv("CHAR_UUID_PRODUCT_PRICE")

# Device addresses
DEVICES = {
    "Loadcell_1": {
        "address": BGM220_LOADCELL_1_ADDRESS,
        "queue": None
    }
    ,
    "Loadcell_2": {
        "address": BGM220_LOADCELL_2_ADDRESS,
        "queue": None
    }
}

# Store previous sensor values for comparison
previous_sensor_values = {
    "humidity": None,
    "temperature": None,
    "light": None,
    "pressure": None
}
last_heartbeat_time = 0
HEARTBEAT_INTERVAL = 300  # 5 minutes in seconds

def should_publish_sensor_data(current_data):
    """Check if sensor data has changed significantly or if heartbeat is due"""
    global previous_sensor_values, last_heartbeat_time

    # Sensors report None until the xG26 delivers its first reading; comparing
    # None against a float crashes the publish loop every 10s
    if any(v is None for v in current_data.values()):
        return False, None
    if any(previous_sensor_values.get(k) is None for k in current_data):
        previous_sensor_values.update(current_data)
        last_heartbeat_time = time.time()
        return True, "initial"

    current_time = time.time()
    
    # Heartbeat check - publish every HEARTBEAT_INTERVAL seconds
    if current_time - last_heartbeat_time >= HEARTBEAT_INTERVAL:
        last_heartbeat_time = current_time
        previous_sensor_values.update(current_data)
        return True, "heartbeat"
    
    # First time publishing
    if previous_sensor_values["temperature"] is None:
        previous_sensor_values.update(current_data)
        last_heartbeat_time = current_time
        return True, "initial"
    
    # Check each sensor value for significant changes
    temp_change = abs(current_data["temperature"] - previous_sensor_values["temperature"])
    humidity_change = abs(current_data["humidity"] - previous_sensor_values["humidity"])
    
    # Calculate percentage change for light and pressure
    light_change_percent = 0
    if previous_sensor_values["light"] != 0:
        light_change_percent = abs(current_data["light"] - previous_sensor_values["light"]) / previous_sensor_values["light"] * 100
    
    pressure_change_percent = 0
    if previous_sensor_values["pressure"] != 0:
        pressure_change_percent = abs(current_data["pressure"] - previous_sensor_values["pressure"]) / previous_sensor_values["pressure"] * 100
    
    # Thresholds
    TEMP_THRESHOLD = 0.5  # degrees
    HUMIDITY_THRESHOLD = 0.5  # percent
    LIGHT_THRESHOLD = 5  # percent
    PRESSURE_THRESHOLD = 5  # percent
    
    if temp_change >= TEMP_THRESHOLD:
        previous_sensor_values.update(current_data)
        return True, f"temperature change: {temp_change:.2f}°C"
    
    if humidity_change >= HUMIDITY_THRESHOLD:
        previous_sensor_values.update(current_data)
        return True, f"humidity change: {humidity_change:.2f}%"
    
    if light_change_percent >= LIGHT_THRESHOLD:
        previous_sensor_values.update(current_data)
        return True, f"light change: {light_change_percent:.2f}%"
    
    if pressure_change_percent >= PRESSURE_THRESHOLD:
        previous_sensor_values.update(current_data)
        return True, f"pressure change: {pressure_change_percent:.2f}%"
    
    return False, None

def send_mqtt_data():
    # Send mqtt data to broker
    while True:
        time.sleep(10)
        try:
            current_sensor_data = {
                "humidity": globals.get_humidity(),
                "temperature": globals.get_temperature(),
                "light": globals.get_light(),
                "pressure": globals.get_pressure()
            }
            
            # Check if we should publish
            should_publish, reason = should_publish_sensor_data(current_sensor_data)
            
            if should_publish:
                sensor_data = {
                    "id": os.getenv("SHELF_ID"),
                    **current_sensor_data
                }
                client.publish(os.getenv("MQTT_SENSOR_TOPIC"), json.dumps(sensor_data), retain=True)
                print(f"Published sensor data - Reason: {reason}")
            
            if globals.get_shelf_lean() or globals.get_shelf_shake():
                shelf_status = {
                    "id": os.getenv("SHELF_ID"),
                    "shelf_status_lean": globals.get_shelf_lean(),
                    "shelf_status_shake": globals.get_shelf_shake(),
                    "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                client.publish(os.getenv("MQTT_SHELF_STATUS_TOPIC"), json.dumps(shelf_status), retain=True)
                print("Sent shelf status update")
                globals.set_shelf_lean(False)
                globals.set_shelf_shake(False)
            if globals.get_unpaid_customer_warning():
                unpaid_customer = {
                    "id": os.getenv("SHELF_ID"),
                    "taken_quantity": globals.get_taken_quantity(),
                    "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                client.publish(os.getenv("MQTT_UNPAID_CUSTOMER_TOPIC"), json.dumps(unpaid_customer), retain=True)
                print("Sent unpaid customer warning")
                globals.set_unpaid_customer_warning(False)
        except Exception as e:
            print(f"⚠️ MQTT publish error in send_mqtt_data: {e}")
            # Don't disconnect - let auto-reconnect handle it

# TTS is a network round-trip (gTTS) plus an audio subprocess; it must never
# run on the BLE notification thread, and the same warning shouldn't repeat
# back-to-back while the error state persists.
_last_speech = {"text": None, "time": 0.0}

def _speak_warning_async(text, min_repeat_sec=10):
    now = time.time()
    if _last_speech["text"] == text and now - _last_speech["time"] < min_repeat_sec:
        return
    _last_speech["text"] = text
    _last_speech["time"] = now

    def _run():
        try:
            speech_text(text)
        except Exception as e:
            print(f"TTS warning failed (offline?): {e}")

    threading.Thread(target=_run, daemon=True).start()

def notification_handler_factory(device_name):
    def handler(sender, data):
        globals.last_data_reception_time = time.time()
        # Flag to reload shopping cart page when loadcell data changes
        globals.set_quantity_change_flag(True)
        new_data = globals.get_loadcell_quantity_snapshot()
        if device_name == "Loadcell_1":
            new_data[:globals.LOADCELL_NUM_1] = list(data)
            globals.set_loadcell_quantity(new_data)

        else:
            new_data[globals.LOADCELL_NUM_1:globals.LOADCELL_NUM_TOTAL] = list(data)[:globals.LOADCELL_NUM_2]
            globals.set_loadcell_quantity(new_data)

        loadcell_error_indexes = [i + 1 for i, v in enumerate(globals.get_loadcell_quantity_snapshot()) if v == 200 or v == 222]
        if loadcell_error_indexes and globals.rfid_state != 1:  # Only warn when not in adding state
            loadcell_error_indexes_str = " và ngăn ".join(map(str, loadcell_error_indexes))
            text = "Cảnh báo sản phẩm đặt tại ngăn thứ " + loadcell_error_indexes_str + " không đúng. Vui lòng đặt sản phẩm lại đúng vị trí."
            _speak_warning_async(text)
        # Overite taken quantity when loadcell data changes
        taken_quantity = np.array(globals.get_verified_quantity()) - np.array(globals.get_loadcell_quantity_snapshot())
        
        taken_quantity[taken_quantity < 0] = 0
        # Update taken quantity in globals - convert to regular int list
        taken_quantity_list = [int(x) for x in taken_quantity]
        globals.set_taken_quantity(taken_quantity_list)
        if np.any(taken_quantity > 0) and globals.get_rfid_state() != 1:
            globals.is_tracking = True
        else:
            globals.is_tracking = False

        print(f"[{device_name}] Received from {sender}: {list(data)}")
        # print("Verified Quantity:", globals.get_verified_quantity())
        # print("Current Loadcell Data:", new_data)
        # print("Taken Quantity:", taken_quantity_list)
        # print("Is Tracking:", globals.is_tracking)

        # Emit WebSocket update immediately after calculating taken_quantity
        try:
            # Import socketio_instance dynamically to avoid import timing issues
            from app.utils.loadcell_ws_utils import get_socketio_instance
            socketio_instance = get_socketio_instance()
            if socketio_instance:
                # Create cart data based on taken_quantity
                cart = []
                products = load_products_from_json()
                
                for i, qty in enumerate(taken_quantity_list):
                    if qty > 0 and i < len(products):
                        product = products[i]
                        original_price = product.get('price', 0)
                        discount = product.get('discount', 0)
                        
                        # Calculate discounted price if discount exists
                        if discount > 0:
                            discounted_price = original_price * (1 - discount / 100)
                            discounted_price = round(discounted_price)
                        else:
                            discounted_price = original_price
                        
                        cart.append({
                            'position': i,
                            'quantity': qty,
                            'product_id': product.get('product_id'),
                            'product_name': product.get('product_name'),
                            'price': discounted_price,
                            'original_price': original_price,  # Always store original
                            'discount': discount,
                            'img_url': product.get('img_url'),
                            'weight': product.get('weight')
                        })
                
                # Apply combo pricing to cart
                cart_with_combo, applied_combos = update_cart_with_combo_pricing(cart)

                # Log combo application
                if applied_combos:
                    print(f"Combo applied! {len(applied_combos)} combo(s) detected:")
                    for combo in applied_combos:
                        print(f"  - {combo.get('combo_name')}: {combo.get('savings', 0):,.0f}đ saved")

                # Emit the update with combo-applied cart; pass applied_combos
                # so the emit does not run the combo solve a second time.
                emit_loadcell_update(socketio_instance, taken_quantity_list, cart_with_combo, applied_combos)
                # print(f"WebSocket emitted: taken_quantity={taken_quantity_list}, cart_items={len(cart_with_combo)}")
                
                # Also update app cart config for API consistency
                try:
                    from flask import current_app
                    current_app.config['cart'] = cart_with_combo
                except:
                    pass  # No app context available
                    
            else:
                print("SocketIO instance not available for WebSocket emit")
        except Exception as e:
            print(f"WebSocket emit error: {e}")
            # Fallback to original logic
            try:
                from app.utils.loadcell_ws_utils import get_socketio_instance
                socketio_instance = get_socketio_instance()
                if socketio_instance:
                    cart = []
                    for i, qty in enumerate(taken_quantity_list):
                        if qty > 0:
                            cart.append({
                                'position': i,
                                'quantity': qty
                            })
                    emit_loadcell_update(socketio_instance, taken_quantity_list, cart)
                    # print(f"Fallback WebSocket emitted: taken_quantity={taken_quantity_list}, cart={cart}")
            except Exception as fallback_e:
                print(f"Fallback WebSocket emit error: {fallback_e}")

        # Send mqtt data to broker
        try:
            mqtt_data = {
                "id": os.getenv("SHELF_ID"),
                "values": new_data if isinstance(new_data, list) else [int(x) for x in new_data]
            }
            payload = json.dumps(mqtt_data)
            msg_info = client.publish(os.getenv("MQTT_LOADCELL_TOPIC"), payload, qos=1, retain=True)
            if msg_info.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"⚖️  Loadcell published (mid={msg_info.mid})")
            else:
                print(f"⚠️ Loadcell publish failed: rc={msg_info.rc}")
        except Exception as e:
            print(f"⚠️ MQTT loadcell publish error: {e}")
            # Don't disconnect - let auto-reconnect handle it

    return handler

async def connect_and_listen(device_name, address, send_queue):
    while True:
        print(f"[{device_name}] Connecting to {address}...")
        # Only ONE device may hold the adapter during the connect handshake.
        holding = await ble_lock.acquire()
        try:
            async with BleakClient(address, timeout=30.0) as client:
                if client.is_connected:
                    print(f"[{device_name}] Connected successfully.")
                    if device_name == "Loadcell_1":
                        globals.bgm_220_1_connection = True
                        threading.Thread(target=play_sound, args=(os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/connected_loadcell_1.mp3")),)).start()
                    if device_name == "Loadcell_2":
                        globals.bgm_220_2_connection = True
                        threading.Thread(target=play_sound, args=(os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/connected_loadcell_2.mp3")),)).start()
                    # Emit WebSocket event for frontend redirect
                    try:
                        emit_connected_status(device_name)
                    except Exception as e:
                        print(f"[WARN] Could not emit loadcell_connected event: {e}")
                    await client.start_notify(LOADCELL_UUID, notification_handler_factory(device_name))
                    # Handshake done — release the adapter so the other
                    # devices can connect while this link keeps streaming.
                    if holding:
                        ble_lock.release()
                        holding = False
                    while client.is_connected:
                        try:
                            char_uuid, data = await asyncio.wait_for(send_queue.get(), timeout=10)
                            await client.write_gatt_char(char_uuid, bytearray(data), response=True)
                            # print(f"[{device_name}] Sent to {char_uuid}: {data}")
                        except asyncio.TimeoutError:
                            pass
                        except Exception as e:
                            print(f"[{device_name}] Write failed: {e}")
                            await send_queue.put((char_uuid, data))  # Retry
                            break
        except asyncio.TimeoutError:
            print(f"[{device_name}] Timeout when connecting to {address}")
        except asyncio.CancelledError:
            print(f"[{device_name}] Connection to {address} was cancelled")
        except (BleakError, OSError) as e:
            print(f"[{device_name}] Connection error: {e}")
        finally:
            if holding:
                ble_lock.release()
        if device_name == "Loadcell_1":
            globals.bgm_220_1_connection = False
        elif device_name == "Loadcell_2":
            globals.bgm_220_2_connection = False
        # Jittered backoff so the devices don't retry in lockstep and collide.
        await asyncio.sleep(3 + random.uniform(0, 3))

async def main():
    # tasks = []
    # for name, info in DEVICES.items():
    #     queue = info["queue"]
    #     tasks.append(asyncio.create_task(connect_and_listen(name, info["address"], queue)))
    # await asyncio.gather(*tasks)
    
    # fix "Future attached to a different loop" bug
    loop = asyncio.get_running_loop()  
    tasks = []
    for name, info in DEVICES.items():
        queue = info["queue"]
        tasks.append(loop.create_task(connect_and_listen(name, info["address"], queue)))
    await asyncio.gather(*tasks)

def start_ble_clients(loop):
    asyncio.set_event_loop(loop)
    # Assign the correct queue to the loop
    for name in DEVICES:
        DEVICES[name]["queue"] = asyncio.Queue()
    loop.run_until_complete(main())
    # fix "Future attached to a different loop" bug
    loop.close()

# Function to send data to devices based on RFID state
def send_data_to_devices(loop):
    while True:
        time.sleep(1)
        # Update verified quantity when payment is verified
        if globals.get_payment_verified():
            globals.set_payment_verified(False)
            # Overwrite verified quantity with loadcell quantity
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
            
            globals.reset_taken_quantity()
            globals.set_is_tracking(False)
            # Save verified quantity to loadcel.json
            data = {
                "name": "verified_quantity",
                "values": globals.get_loadcell_quantity_snapshot()
                }
            if isinstance(data["values"], np.ndarray):
                data["values"] = data["values"].tolist()
            file_path = os.path.abspath(os.path.join(__file__,  "../../..","database/loadcell.json"))
            with open(file_path, "w") as f:
                json.dump(data, f, indent=4)    

            for name, dev in DEVICES.items(): 
                    future = asyncio.run_coroutine_threadsafe(
                        dev["queue"].put((CHAR_UUID_WRITE_SAVE_QUANTITY, [0])), loop)
                    try:
                        future.result(timeout=10)
                        print(f"[{name}] Queued: {0} to {CHAR_UUID_WRITE_SAVE_QUANTITY}")
                    except Exception as e:
                        print(f"[{name}] Failed to queue: {e}")
        # Update weight of one and verified quantity when employee add products
        if globals.bool_rfid: # RFID Valid
            globals.bool_rfid = False
            if globals.rfid_state == 0: # Added
                # Overwrite verified quantity with loadcell quantity
                globals.is_tracking = False
                for name, dev in DEVICES.items(): 
                    future = asyncio.run_coroutine_threadsafe(
                        dev["queue"].put((CHAR_UUID_WRITE_SAVE_QUANTITY, [globals.rfid_state])), loop)
                    try:
                        future.result(timeout=10)
                        print(f"[{name}] Queued: {globals.rfid_state} to {CHAR_UUID_WRITE_SAVE_QUANTITY}")
                    except Exception as e:
                        print(f"[{name}] Failed to queue: {e}")
                
                # Send MQTT notification when product added successfully
                try:
                    product_added_data = {
                        "id": os.getenv("SHELF_ID"),
                        "event": "product_added",
                        "rfid": globals.rfid,
                        "verified_quantity": globals.get_verified_quantity(),
                        "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    client.publish(os.getenv("MQTT_PRODUCT_ADDED_TOPIC"), 
                                   json.dumps(product_added_data), retain=True)
                    print(f"📦 Sent product added notification - RFID: {globals.rfid}")
                except Exception as e:
                    print(f"Failed to send product added MQTT: {e}")
            else: # Adding
                globals.set_is_tracking(False)
                
                # Emit WebSocket event to reload shelf page for fresh cloud data
                try:
                    from app.utils.loadcell_ws_utils import get_socketio_instance
                    socketio_instance = get_socketio_instance()
                    if socketio_instance:
                        socketio_instance.emit('reload_shelf_page', {
                            'message': 'Reloading shelf to sync cloud data'
                        })
                        print("[RFID] Emitted reload_shelf_page event to frontend")
                except Exception as e:
                    print(f"[WARN] Could not emit reload_shelf_page: {e}")
                
                for name, dev in DEVICES.items():
                    if name == "Loadcell_1":
                        weight_of_one = globals.weight_of_one[:globals.LOADCELL_NUM_1]
                        products_name = globals.products_name_decimal[:globals.products_name_char_count]
                        products_price = globals.products_price[:globals.LOADCELL_NUM_1]
                    else:
                        weight_of_one = globals.weight_of_one[globals.LOADCELL_NUM_1:globals.LOADCELL_NUM_TOTAL]
                        products_name = globals.products_name_decimal[globals.products_name_char_count:]
                        products_price = globals.products_price[globals.LOADCELL_NUM_1:globals.LOADCELL_NUM_TOTAL]
                    future = asyncio.run_coroutine_threadsafe(
                        dev["queue"].put((CHAR_UUID_WRITE_WEIGHT, weight_of_one)), loop)
                    future2 = asyncio.run_coroutine_threadsafe(
                        dev["queue"].put((CHAR_UUID_WRITE_SAVE_QUANTITY, [globals.rfid_state])), loop)
                    future3 = asyncio.run_coroutine_threadsafe(
                        dev["queue"].put((CHAR_UUID_PRODUCT_NAME, products_name)), loop)
                    future4 = asyncio.run_coroutine_threadsafe(
                        dev["queue"].put((CHAR_UUID_PRODUCT_PRICE, products_price)), loop)

                    try:
                        future.result(timeout=10)
                        #print(f"[{name}] Queued weight of one: {weight_of_one} to {CHAR_UUID_WRITE_WEIGHT}")
                    except Exception as e:
                        print(f"[{name}] Failed to queue: {e}")
                    try:
                        future2.result(timeout=10)
                        print(f"[{name}] Queued RFID state: {globals.rfid_state} to {CHAR_UUID_WRITE_SAVE_QUANTITY}")
                    except Exception as e:
                        print(f"[{name}] Failed to queue RFID: {e}")
                    try:
                        future3.result(timeout=10)
                        #print(f"[{name}] Queued product names: {products_name} to {CHAR_UUID_PRODUCT_NAME}")
                    except Exception as e:
                        print(f"[{name}] Failed to queue product names: {e}")
                    try:
                        future4.result(timeout=10)
                        #print(f"[{name}] Queued product prices: {products_price} to {CHAR_UUID_PRODUCT_PRICE}")
                    except Exception as e:
                        print(f"[{name}] Failed to queue product prices: {e}")

def start_update_loadcell_quantity():
    loop = asyncio.new_event_loop()
    # Start BLE clients in separate thread
    threading.Thread(target=start_ble_clients, args=(loop,), daemon=True).start()
    threading.Thread(target=send_mqtt_data, daemon=True).start()
    # Listen rfid to send data to devices
    send_data_to_devices(loop)