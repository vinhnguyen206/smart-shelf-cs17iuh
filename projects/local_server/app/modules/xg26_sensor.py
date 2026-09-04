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
import asyncio
import random
from bleak import BleakClient, BleakScanner, BleakError
import struct
import os
from dotenv import load_dotenv
from app.modules import globals
from app.utils import ble_lock
from app.utils.sound_utils import play_sound
import threading
from collections import deque
from threading import Lock
# Load environment variables
load_dotenv()

# BLE address of the XG26 sensor device
XG26_SENSOR_ADDRESS = os.getenv("XG26_SENSOR_ADDRESS")

# UUIDs for various sensor characteristics
IMU_UUID = os.getenv("IMU_UUID")
CHAR_UUID_PRESSURE    = os.getenv("CHAR_UUID_PRESSURE")
CHAR_UUID_TEMPERATURE = os.getenv("CHAR_UUID_TEMPERATURE")
CHAR_UUID_HUMIDITY    = os.getenv("CHAR_UUID_HUMIDITY")
CHAR_UUID_LIGHT       = os.getenv("CHAR_UUID_LIGHT")
CHAR_UUID_SOUND       = os.getenv("CHAR_UUID_SOUND")
CHAR_UUID_MAGNETIC    = os.getenv("CHAR_UUID_MAGNETIC")

# Mapping from characteristic UUID to (label, format, scale, is_notify)
CHAR_MAP = {
    CHAR_UUID_PRESSURE: ("Pressure (hPa)", "<I", 1000.0, False),
    CHAR_UUID_TEMPERATURE: ("Temperature (°C)", "<h", 100.0, False),
    CHAR_UUID_HUMIDITY: ("Humidity (%)", "<H", 100.0, False),
    CHAR_UUID_LIGHT: ("Light (lux)", "<I", 1.0, False),
    CHAR_UUID_SOUND: ("Sound (dB)", "<H", 1.0, False),
    CHAR_UUID_MAGNETIC: ("Magnetic Field (µT)", "<I", 1.0, False),
    IMU_UUID: ("IMU (X, Y, Z)", "<hhh", 1.0, True)
}

# Global variables for shake and lean detection
delay_count_lean = 0
delay_threshold_lean = 30

delay_count_shake = 0
delay_threshold_shake = 10
windows_length = 5
windows = deque([0] * windows_length, maxlen=windows_length)
pre_x, pre_y, pre_z = (0,0,0)
imu_lock = Lock()  # Lock to protect global variables
sound_file_path_lean = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/imu_alert.mp3"))
sound_file_path_shake = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/imu_alert_2.mp3"))

def compute_shake(x,y,z,pre_x, pre_y, pre_z, windows):
    dx = abs(x - pre_x)
    dy = abs(y - pre_y)
    dz = abs(z - pre_z)
    total_d = dx + dy + dz
    pre_x, pre_y, pre_z = x, y, z
    windows.append(total_d)
    return sum(windows)

def compute_lean(x,y,z):
    x_init, y_init, z_init = globals.get_imu_data_init()
    delta_x = abs(x - x_init)
    delta_y = abs(y - y_init)
    delta_z = abs(z - z_init)
    total_lean = delta_x + delta_y + delta_z
    return total_lean

def imu_processing(x,y,z):
    global delay_count_lean, delay_threshold_lean, delay_count_shake, delay_threshold_shake, windows, windows_length, pre_x, pre_y, pre_z, sound_file_path_lean, sound_file_path_shake
    total_lean = compute_lean(x,y,z)
    total_shake = compute_shake(x,y,z, pre_x, pre_y, pre_z, windows)

    # Check for lean detection
    if total_lean > globals.get_threatshold_imu_lean():
        delay_count_lean += 1
        if delay_count_lean >= delay_threshold_lean: 
            print(f"[ALERT] Significant lean detected! Total={total_lean}")
            threading.Thread(target=play_sound, args=(sound_file_path_lean,)).start()
            delay_count_lean = 0
            delay_threshold_lean = 50
            globals.set_shelf_lean(True)
    else:
        delay_count_lean = 0
        delay_threshold_lean = 30

    # Check for shake detection
    if total_shake > (globals.get_threatshold_imu_shake() * windows_length):
        delay_count_shake += 1
        if delay_count_shake >= delay_threshold_shake: 
            print(f"[ALERT] Significant shake detected! Total={total_shake}")
            threading.Thread(target=play_sound, args=(sound_file_path_shake,)).start()
            delay_count_shake = 0
            delay_threshold_shake = 30
            globals.set_shelf_shake(True)
    else:
        delay_count_shake = 0
        delay_threshold_shake = 10

# Create handler to receive IMU notifications
def create_notify_handler(uuid):
    def handler(sender, data):
        try:
            if uuid == IMU_UUID and len(data) == 6:
                x, y, z = struct.unpack("<hhh", data)
                with imu_lock:  # Thread-safe access
                    global pre_x, pre_y, pre_z
                    if globals.get_imu_data_init() is None:
                        globals.set_imu_data_init((x, y, z))
                        pre_x, pre_y, pre_z = x, y, z
                    else:
                        imu_processing(x, y, z)
        except Exception as e:
            print(f"⚠ Error in notification handler: {e}")
    return handler

# Main BLE connection and reading loop
async def connect_and_monitor():
    max_connection_retries = 5
    connection_retry_count = 0
    # Startup stagger: let the two loadcells (real-time critical) grab the
    # single adapter first, then the sensor joins.
    await asyncio.sleep(6)

    while True:
        holding = False
        try:
            # Serialize scan+connect on the shared adapter; release the gate
            # the moment the link is up (or on failure) so it is never held
            # during a backoff sleep that would block the loadcells.
            holding = await ble_lock.acquire()
            print("Searching for xg26 sensor device...")
            device = await BleakScanner.find_device_by_address(XG26_SENSOR_ADDRESS, timeout=20.0)  # Increased timeout
            if not device:
                print("xg26 sensor not found. Retrying...")
                ble_lock.release()
                holding = False
                await asyncio.sleep(5 + random.uniform(0, 3))
                continue

            print(f"Found xg26 sensor, attempting to connect (attempt {connection_retry_count + 1}/{max_connection_retries})...")

            # Connect with explicit timeout (BleakClient handles timeout internally)
            async with BleakClient(
                device,
                disconnected_callback=lambda c: print("Disconnected xg26 sensor device."),
                timeout=30.0  # 30 second timeout for connection
            ) as client:
                print("✓ Connected to xg26 sensor device.")
                connection_retry_count = 0  # Reset retry count on successful connection

                sound_file_path = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/connect-sensor.mp3"))
                threading.Thread(target=play_sound, args=(sound_file_path,), daemon=True).start()
                globals.set_imu_data_init(None)  # Reset IMU initial data on new connection

                # Enable notifications with retry
                for uuid, (label, _, _, is_notify) in CHAR_MAP.items():
                    if is_notify:
                        try:
                            await client.start_notify(uuid, create_notify_handler(uuid))
                            print(f"✓ Notifications enabled for {label}")
                        except Exception as notify_error:
                            print(f"⚠ Failed to enable notifications for {label}: {notify_error}")

                # Handshake done — free the adapter for the other devices.
                ble_lock.release()
                holding = False

                # Main read loop with improved stability
                read_cycle_count = 0
                while client.is_connected:
                    try:
                        for uuid, (label, fmt, scale, is_notify) in CHAR_MAP.items():
                            if not is_notify:  # Only read non-notify characteristics
                                # Check connection state before each read
                                if not client.is_connected:
                                    print("⚠ Connection lost during read cycle")
                                    break
                                    
                                try:
                                    data = await asyncio.wait_for(client.read_gatt_char(uuid), timeout=10.0)
                                    if len(data) == struct.calcsize(fmt):
                                        value = struct.unpack(fmt, data)[0] / scale

                                        # Assign to global variable
                                        if uuid == CHAR_UUID_PRESSURE:
                                            globals.set_pressure(value)
                                        elif uuid == CHAR_UUID_TEMPERATURE:
                                            globals.set_temperature(value)
                                        elif uuid == CHAR_UUID_HUMIDITY:
                                            globals.set_humidity(value)
                                        elif uuid == CHAR_UUID_LIGHT:
                                            globals.set_light(value)
                                        elif uuid == CHAR_UUID_SOUND:
                                            globals.set_sound(value)
                                        elif uuid == CHAR_UUID_MAGNETIC:
                                            globals.set_magnetic(value)
                                    else:
                                        print(f"{label}: Invalid data length.")
                                except asyncio.TimeoutError:
                                    print(f"{label}: Read timeout, skipping...")
                                except Exception as e:
                                    print(f"{label}: Read error - {e}")
                                
                                # Add delay between characteristic reads to avoid BLE stack overload
                                await asyncio.sleep(0.2)
                        
                        # Keepalive: send a read request periodically to maintain connection
                        read_cycle_count += 1
                        if read_cycle_count % 6 == 0:  # Every 6th cycle (~1 minute)
                            try:
                                await client.read_gatt_char(CHAR_UUID_TEMPERATURE)  # Lightweight keepalive
                            except:
                                pass
                        
                        await asyncio.sleep(10)  # Increased delay between read cycles (was 5s)
                        
                    except Exception as read_loop_error:
                        print(f"Error in read loop: {read_loop_error}")
                        await asyncio.sleep(3)
                        if not client.is_connected:
                            break

        except asyncio.TimeoutError:
            connection_retry_count += 1
            print(f"⚠ Connection timeout (attempt {connection_retry_count}/{max_connection_retries})")
        except asyncio.CancelledError:
            print("XG26 sensor connection cancelled")
            connection_retry_count += 1
        except (BleakError, OSError) as e:
            connection_retry_count += 1
            print(f"⚠ Xg26 sensor connection error (attempt {connection_retry_count}/{max_connection_retries}): {e}")
        except Exception as e:
            print(f"⚠ Unexpected error in XG26 sensor: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Never hold the adapter gate into a backoff sleep.
            if holding:
                ble_lock.release()
                holding = False

        # Unified jittered backoff, OUTSIDE the adapter gate.
        if connection_retry_count >= max_connection_retries:
            print("⚠ Max retries reached. Waiting before next cycle...")
            connection_retry_count = 0
            await asyncio.sleep(25 + random.uniform(0, 5))
        else:
            await asyncio.sleep(8 + random.uniform(0, 4))

def start_xg26_sensor():
    # Create a new event loop for this thread to avoid "Future attached to a different loop" error
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(connect_and_monitor())
    finally:
        loop.close()