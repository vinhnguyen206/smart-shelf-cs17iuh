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
import subprocess
import time
import threading
import logging
import sys
import shutil
import os
import dotenv
from dotenv import load_dotenv
from app.utils.sound_utils import play_sound

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
HOTSPOT_SSID = os.getenv("HOTSPOT_SSID")
HOTSPOT_PASSWORD = os.getenv("HOTSPOT_PASSWORD")
CHECK_INTERVAL = 15  # seconds - Tăng lên để tránh check quá nhanh
NMCLI_TIMEOUT = 10  # seconds - Timeout cho các lệnh nmcli

# Kiểm tra platform và nmcli
IS_LINUX = sys.platform.startswith('linux')
HAS_NMCLI = shutil.which('nmcli') is not None

wifi_status = {
    'connected': False,
    'ssid': None,
    'hotspot_active': False,
    'error': None
}

# Cache cho kết quả scan WiFi
last_scan_time = 0
last_scan_results = []
SCAN_COOLDOWN = 10  # giây - thời gian tối thiểu giữa các lần scan
is_scanning = False  # Flag để tránh race condition với wifi_monitor
is_connecting = False  # Flag khi đang kết nối WiFi
stop_wifi_monitor = False  # Flag để dừng wifi_monitor khi đã connected

# Event để báo hiệu khi WiFi đã kết nối (dùng để sync với main thread)
wifi_ready_event = threading.Event()

# Callback để gọi khi WiFi kết nối thành công từ hotspot mode
on_wifi_connected_callback = None

def check_system_requirements():
    """Kiểm tra xem hệ thống có đủ yêu cầu không"""
    if not IS_LINUX:
        logger.warning("WiFi Manager chỉ hoạt động trên Linux. Platform hiện tại: " + sys.platform)
        wifi_status['error'] = f"Không hỗ trợ platform {sys.platform}. Chỉ hoạt động trên Linux/Jetson Nano."
        return False
    
    if not HAS_NMCLI:
        logger.error("nmcli không tìm thấy. Vui lòng cài đặt NetworkManager:")
        logger.error("  sudo apt-get update")
        logger.error("  sudo apt-get install network-manager")
        wifi_status['error'] = "nmcli không tìm thấy. Cài đặt: sudo apt-get install network-manager"
        return False
    
    return True

def check_wifi_connection():
    """Kiểm tra xem Jetson có kết nối WiFi không"""
    try:
        # Kiểm tra kết nối WiFi qua device status với timeout dài hơn
        result = subprocess.run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'dev'],
                              capture_output=True, text=True, timeout=NMCLI_TIMEOUT)
        
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                parts = line.split(':')
                if len(parts) >= 4:
                    device, dev_type, state, connection = parts[0], parts[1], parts[2], parts[3]
                    # Kiểm tra xem có WiFi device nào đang connected không (và không phải hotspot)
                    if dev_type == 'wifi' and state == 'connected' and connection and 'Hotspot' not in connection:
                        # Lấy SSID
                        ssid_result = subprocess.run(['nmcli', '-t', '-f', 'active,ssid', 'dev', 'wifi'],
                                                    capture_output=True, text=True, timeout=NMCLI_TIMEOUT)
                        
                        for ssid_line in ssid_result.stdout.split('\n'):
                            if ssid_line.startswith('yes:'):
                                ssid = ssid_line.split(':', 1)[1]
                                wifi_status['connected'] = True
                                wifi_status['ssid'] = ssid
                                logger.debug(f"WiFi connected to: {ssid}")
                                return True
        
        wifi_status['connected'] = False
        wifi_status['ssid'] = None
        return False
    except Exception as e:
        logger.error(f"Error checking WiFi connection: {e}")
        return False

def scan_wifi_networks():
    """Quét các mạng WiFi khả dụng"""
    global last_scan_time, last_scan_results, is_scanning
    
    if not HAS_NMCLI or not IS_LINUX:
        logger.error("Cannot scan WiFi: nmcli not available")
        return []
    
    # Kiểm tra xem có quá sớm để scan lại không
    current_time = time.time()
    time_since_last_scan = current_time - last_scan_time
    
    if time_since_last_scan < SCAN_COOLDOWN and last_scan_results:
        logger.info(f"Using cached WiFi scan results (scanned {int(time_since_last_scan)}s ago)")
        return last_scan_results
    
    # Đánh dấu đang scan để wifi_monitor không can thiệp
    is_scanning = True
    
    try:
        # Kiểm tra xem wlan0 có đang ở chế độ AP không
        device_result = subprocess.run(
            ['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'dev'],
            capture_output=True, text=True, timeout=5
        )
        
        hotspot_was_active = False
        for line in device_result.stdout.split('\n'):
            if 'wlan0' in line and 'wifi' in line:
                # Kiểm tra xem có connection nào đang active trên wlan0 không
                active_check = subprocess.run(
                    ['nmcli', '-t', '-f', 'NAME,DEVICE', 'connection', 'show', '--active'],
                    capture_output=True, text=True, timeout=5
                )
                if 'wlan0' in active_check.stdout:
                    hotspot_was_active = True
                    break
        
        if hotspot_was_active:
            logger.info("Temporarily stopping hotspot to scan WiFi networks...")
            stop_hotspot()
            time.sleep(3)  # Đợi interface chuyển chế độ
        
        # Force rescan để lấy danh sách mới nhất
        try:
            subprocess.run(['nmcli', 'dev', 'wifi', 'rescan'], 
                          capture_output=True, timeout=5, check=False)
            time.sleep(3)  # Đợi scan hoàn tất
        except Exception as e:
            logger.warning(f"Rescan warning: {e}")
        
        # Lấy danh sách WiFi
        result = subprocess.run(['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'dev', 'wifi', 'list'],
                              capture_output=True, text=True, timeout=10)
        
        networks = []
        seen_ssids = set()
        
        for line in result.stdout.split('\n'):
            if line.strip():
                parts = line.split(':')
                if len(parts) >= 3:
                    ssid = parts[0]
                    signal = parts[1]
                    security = parts[2]
                    
                    # Bỏ qua SSID của hotspot của chính mình
                    if ssid == HOTSPOT_SSID:
                        continue
                    
                    # Bỏ qua SSID trống hoặc trùng lặp
                    if ssid and ssid not in seen_ssids:
                        seen_ssids.add(ssid)
                        networks.append({
                            'ssid': ssid,
                            'signal': int(signal) if signal.isdigit() else 0,
                            'security': security if security else 'Open'
                        })
        
        # Bật lại hotspot nếu trước đó nó đang bật
        if hotspot_was_active:
            logger.info("Restarting hotspot after scan...")
            time.sleep(1)
            start_hotspot()
        
        # Sắp xếp theo cường độ tín hiệu
        networks.sort(key=lambda x: x['signal'], reverse=True)
        
        # Cập nhật cache
        last_scan_time = current_time
        last_scan_results = networks
        
        logger.info(f"Found {len(networks)} WiFi networks")
        return networks
    except FileNotFoundError:
        logger.error("nmcli command not found. Install NetworkManager: sudo apt-get install network-manager")
        return []
    except Exception as e:
        logger.error(f"Error scanning WiFi networks: {e}")
        return []
    finally:
        # Luôn reset flag khi hoàn thành scan
        is_scanning = False

def connect_to_wifi(ssid, password=None):
    """Kết nối tới mạng WiFi"""
    global is_connecting
    
    if not HAS_NMCLI or not IS_LINUX:
        error_msg = "Cannot connect: nmcli not available. Install NetworkManager on Linux/Jetson Nano."
        logger.error(error_msg)
        return False, error_msg
    
    # Đánh dấu đang kết nối để wifi_monitor không can thiệp
    is_connecting = True
    logger.info("Setting is_connecting flag to prevent wifi_monitor interference")
    time.sleep(1)  # Đợi wifi_monitor nhận flag
    
    try:
        logger.info(f"Attempting to connect to WiFi: {ssid}")
        
        # Tắt hotspot nếu đang bật
        if wifi_status['hotspot_active']:
            stop_hotspot()
            # Đợi interface chuyển chế độ
            time.sleep(3)
        
        # Scan lại để NetworkManager có thông tin WiFi mới nhất
        logger.info("Scanning for WiFi networks before connecting...")
        try:
            subprocess.run(['nmcli', 'dev', 'wifi', 'rescan'], 
                          capture_output=True, timeout=5, check=False)
            time.sleep(3)  # Đợi scan hoàn tất
        except Exception as e:
            logger.warning(f"Rescan warning: {e}")
        
        # Xóa kết nối cũ nếu có (bỏ qua lỗi nếu không tồn tại)
        subprocess.run(['nmcli', 'connection', 'delete', ssid], 
                      capture_output=True, timeout=5, check=False)
        
        # Kết nối WiFi
        if password:
            cmd = ['nmcli', 'dev', 'wifi', 'connect', ssid, 'password', password]
        else:
            cmd = ['nmcli', 'dev', 'wifi', 'connect', ssid]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            logger.info(f"Successfully connected to {ssid}")
            wifi_status['connected'] = True
            wifi_status['ssid'] = ssid
            wifi_status['hotspot_active'] = False
            
            # Phát âm thanh thành công
            try:
                sound_path = "app/static/sounds/wifi_connection_success.mp3"
                threading.Thread(target=play_sound, args=(sound_path,), daemon=True).start()
                logger.info("Playing WiFi connection success sound")
            except Exception as e:
                logger.warning(f"Could not play success sound: {e}")
            
            # Đợi kết nối ổn định - tăng thời gian
            logger.info("Waiting for connection to stabilize...")
            time.sleep(10)  # Tăng từ 5s lên 10s
            
            # Verify connection nhiều lần
            for i in range(3):
                if check_wifi_connection():
                    logger.info(f"Connection verified (attempt {i+1}/3)")
                    break
                time.sleep(2)
            
            logger.info("Connection established and stable")
            
            # Dừng wifi_monitor vì đã kết nối thành công
            global stop_wifi_monitor
            stop_wifi_monitor = True
            logger.info("WiFi monitor will be stopped")
            
            # Báo hiệu rằng WiFi đã sẵn sàng
            wifi_ready_event.set()
            
            # Gọi callback nếu có (cho main.py biết để start services)
            if on_wifi_connected_callback:
                logger.info("Calling on_wifi_connected callback...")
                threading.Thread(target=on_wifi_connected_callback, daemon=True).start()
            
            return True, "Connected successfully"
        else:
            error_msg = result.stderr.strip()
            logger.error(f"Failed to connect: {error_msg}")
            
            # Nếu lỗi "No network found", thử với BSSID
            if "No network" in error_msg or "not found" in error_msg.lower():
                logger.info("Trying alternative connection method...")
                # List lại WiFi để lấy thông tin
                list_result = subprocess.run(
                    ['nmcli', '-t', '-f', 'SSID,BSSID', 'dev', 'wifi', 'list'],
                    capture_output=True, text=True, timeout=5
                )
                
                # Tìm BSSID của SSID cần kết nối
                for line in list_result.stdout.split('\n'):
                    if line.startswith(ssid + ':'):
                        parts = line.split(':')
                        if len(parts) >= 2:
                            bssid = parts[1]
                            logger.info(f"Found BSSID: {bssid}, trying to connect via BSSID...")
                            
                            if password:
                                cmd_bssid = ['nmcli', 'dev', 'wifi', 'connect', bssid, 'password', password]
                            else:
                                cmd_bssid = ['nmcli', 'dev', 'wifi', 'connect', bssid]
                            
                            result2 = subprocess.run(cmd_bssid, capture_output=True, text=True, timeout=30)
                            if result2.returncode == 0:
                                logger.info(f"Successfully connected via BSSID")
                                wifi_status['connected'] = True
                                wifi_status['ssid'] = ssid
                                wifi_status['hotspot_active'] = False
                                
                                # Phát âm thanh thành công
                                try:
                                    sound_path = "app/static/sounds/wifi_connection_success.mp3"
                                    threading.Thread(target=play_sound, args=(sound_path,), daemon=True).start()
                                    logger.info("Playing WiFi connection success sound")
                                except Exception as e:
                                    logger.warning(f"Could not play success sound: {e}")
                                
                                # Đợi kết nối ổn định - tăng thời gian
                                logger.info("Waiting for connection to stabilize...")
                                time.sleep(10)
                                
                                # Verify connection nhiều lần
                                for i in range(3):
                                    if check_wifi_connection():
                                        logger.info(f"Connection verified (attempt {i+1}/3)")
                                        break
                                    time.sleep(2)
                                
                                logger.info("Connection established and stable")
                                return True, "Connected successfully"
                            break
            
            return False, error_msg
    except FileNotFoundError:
        error_msg = "nmcli not found. Install: sudo apt-get install network-manager"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        logger.error(f"Error connecting to WiFi: {e}")
        return False, str(e)
    finally:
        # Luôn reset flag khi hoàn thành
        is_connecting = False

def start_hotspot():
    """Khởi động hotspot WiFi"""
    try:
        logger.info("Starting WiFi hotspot...")
        
        # Kiểm tra xem hotspot connection đã tồn tại chưa
        check_result = subprocess.run(['nmcli', 'connection', 'show', HOTSPOT_SSID],
                                     capture_output=True, timeout=5)
        
        if check_result.returncode == 0:
            # Hotspot connection đã tồn tại, chỉ cần bật lên
            result = subprocess.run(['nmcli', 'connection', 'up', HOTSPOT_SSID],
                                  capture_output=True, text=True, timeout=10)
        else:
            # Tạo hotspot mới
            result = subprocess.run([
                'nmcli', 'dev', 'wifi', 'hotspot',
                'ifname', 'wlan0',
                # con-name MUST equal the SSID: the existence check above
                # looks up a profile by that name. Without it NM named each
                # new profile 'Hotspot-N', the check never matched, and a
                # fresh profile was created on every call (100+ found).
                'con-name', HOTSPOT_SSID,
                'ssid', HOTSPOT_SSID,
                'password', HOTSPOT_PASSWORD
            ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            logger.info(f"Hotspot started: {HOTSPOT_SSID}")
            wifi_status['hotspot_active'] = True
            wifi_status['connected'] = False
            wifi_status['ssid'] = None
            return True
        else:
            logger.error(f"Failed to start hotspot: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error starting hotspot: {e}")
        return False

def stop_hotspot():
    """Tắt hotspot WiFi"""
    try:
        logger.info("Stopping WiFi hotspot...")
        
        # Tìm tất cả các connection đang active trên wlan0
        active_result = subprocess.run(
            ['nmcli', '-t', '-f', 'NAME,DEVICE', 'connection', 'show', '--active'],
            capture_output=True, text=True, timeout=5
        )
        
        hotspot_stopped = False
        
        # Tắt tất cả connection trên wlan0
        for line in active_result.stdout.split('\n'):
            if 'wlan0' in line:
                conn_name = line.split(':')[0]
                logger.info(f"Stopping connection: {conn_name}")
                result = subprocess.run(['nmcli', 'connection', 'down', conn_name],
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    hotspot_stopped = True
        
        # Nếu không tìm thấy connection nào, thử tắt theo tên
        if not hotspot_stopped:
            result = subprocess.run(['nmcli', 'connection', 'down', HOTSPOT_SSID],
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                hotspot_stopped = True
        
        if hotspot_stopped:
            logger.info("Hotspot stopped")
            wifi_status['hotspot_active'] = False
            return True
        else:
            # Không coi đây là lỗi nếu không có hotspot đang chạy
            logger.info("No active hotspot to stop")
            wifi_status['hotspot_active'] = False
            return True
    except Exception as e:
        logger.error(f"Error stopping hotspot: {e}")
        wifi_status['hotspot_active'] = False
        return False

def wifi_monitor():
    """Luồng giám sát WiFi - tự động bật hotspot nếu mất kết nối"""
    global is_scanning, is_connecting, stop_wifi_monitor
    logger.info("WiFi monitor started")
    
    # Kiểm tra yêu cầu hệ thống trước
    if not check_system_requirements():
        logger.error("WiFi Manager disabled: System requirements not met")
        return
    
    # Đợi một chút để các module khác khởi động và kiểm tra kết nối hiện tại
    logger.info("Checking current WiFi connection status...")
    time.sleep(3)
    
    # Kiểm tra ngay xem đã có WiFi chưa
    if check_wifi_connection():
        logger.info(f"Already connected to WiFi: {wifi_status['ssid']}")
        logger.info("WiFi connection stable - stopping monitor to avoid interference")
        # Báo hiệu rằng WiFi đã sẵn sàng
        wifi_ready_event.set()
        # Nếu đã kết nối WiFi, dừng monitor để tránh can thiệp
        logger.info("WiFi monitor stopped: Already connected to WiFi")
        return
    
    while True:
        try:
            # Kiểm tra nếu được yêu cầu dừng
            if stop_wifi_monitor:
                logger.info("WiFi monitor stopped: WiFi connected successfully")
                break
            
            # Bỏ qua nếu đang scan WiFi hoặc đang kết nối
            if is_scanning:
                logger.debug("Skipping wifi_monitor: is_scanning=True")
                time.sleep(3)
                continue
            
            if is_connecting:
                logger.info("Skipping wifi_monitor: WiFi connection in progress...")
                time.sleep(5)  # Đợi lâu hơn khi đang connect
                continue
            
            connected = check_wifi_connection()
            
            # Nếu đã kết nối WiFi thành công, dừng monitor
            if connected:
                logger.info(f"WiFi stable on {wifi_status['ssid']} - stopping monitor")
                wifi_ready_event.set()
                break
            
            if not connected and not wifi_status['hotspot_active']:
                logger.warning("No WiFi connection detected. Starting hotspot...")
                # Phát âm thanh cảnh báo không có WiFi
                try:
                    threading.Thread(
                        target=play_sound, 
                        args=("app/static/sounds/wifi_connection_error.mp3",), 
                        daemon=True
                    ).start()
                    logger.info("Playing WiFi connection error sound")
                except Exception as e:
                    logger.warning(f"Could not play error sound: {e}")
                
                if start_hotspot():
                    # Báo hiệu rằng hotspot đã sẵn sàng (để web server có thể chạy)
                    logger.info("Hotspot ready - setting wifi_ready_event")
                    wifi_ready_event.set()
            elif connected and wifi_status['hotspot_active']:
                logger.info("WiFi connected. Stopping hotspot...")
                stop_hotspot()
            
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            logger.error(f"Error in WiFi monitor: {e}")
            time.sleep(CHECK_INTERVAL)

def start_wifi_manager():
    """Khởi động WiFi manager"""
    logger.info("Starting WiFi Manager...")
    
    # Kiểm tra hệ thống ngay từ đầu
    if not check_system_requirements():
        logger.warning("WiFi Manager will not start - running in disabled mode")
        logger.warning("This is normal if you're running on Windows or without NetworkManager")
        return
    
    wifi_monitor()

def wait_for_wifi(timeout=None):
    """Chờ đợi cho đến khi WiFi kết nối thành công HOẶC hotspot đã sẵn sàng
    
    Args:
        timeout: Thời gian chờ tối đa (seconds). None = chờ vô thời hạn
    
    Returns:
        True nếu WiFi/hotspot đã sẵn sàng, False nếu timeout hoặc không hỗ trợ
    """
    if not HAS_NMCLI or not IS_LINUX:
        logger.warning("WiFi Manager không hỗ trợ trên platform này")
        return True  # Cho phép tiếp tục nếu không hỗ trợ
    
    logger.info("Waiting for WiFi connection or hotspot...")
    result = wifi_ready_event.wait(timeout=timeout)
    
    if result:
        if wifi_status['connected']:
            logger.info(f"WiFi connected to: {wifi_status['ssid']}")
        elif wifi_status['hotspot_active']:
            logger.info("Hotspot is active and ready")
        else:
            logger.info("Network ready!")
    else:
        logger.warning(f"Network setup timeout after {timeout} seconds")
    
    return result

def set_wifi_connected_callback(callback):
    """Set callback để gọi khi WiFi kết nối thành công
    
    Args:
        callback: Function không tham số để gọi khi WiFi connected
    """
    global on_wifi_connected_callback
    on_wifi_connected_callback = callback
    logger.info("WiFi connected callback registered")

def get_wifi_status():
    """Lấy trạng thái WiFi hiện tại"""
    if not HAS_NMCLI or not IS_LINUX:
        return wifi_status.copy()
    
    check_wifi_connection()
    return wifi_status.copy()
