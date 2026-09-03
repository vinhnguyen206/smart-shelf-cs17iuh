'''
* Copyright 2025 Tran Vu Thuy Trang [C]
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
"""
Main Flask Application - Refactored with Blueprints
"""
import os
import signal
import atexit
import threading
import time
import logging
import requests

import numpy as np
from flask import Flask
from flask_socketio import SocketIO

# Import blueprints
from app.routes.main_routes import main_bp
from app.routes.api_routes import api_bp
from app.routes.payment_routes import payment_bp
from app.routes.loadcell_routes import loadcell_bp
from app.routes.debug_routes import debug_bp
from app.routes.wifi_routes import wifi_bp
from app.routes.webhook_routes import webhook_bp
from app.routes.websocket_routes import register_websocket_handlers

# Import utilities and modules
from app.modules import globals
from app.modules import voice_command_monitor
from app.modules import quantity_change_monitor
from app.modules import rfid_state_monitor
from app.modules import payment_webhook_listener
from app.utils.database_utils import load_products_from_json
from app.utils.loadcell_utils import (
    check_loadcell_error_codes, 
    update_cart_quantities,
    has_any_data,
    has_recent_data_reception
)
from app.utils.websocket_utils import emit_loadcell_update, emit_connection_status

# Create Flask app
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'
app.config['SESSION_COOKIE_SECURE'] = True

# Configure logging to suppress 200 status codes
class NoSuccessFilter(logging.Filter):
    def filter(self, record):
        # Filter out successful requests (200, 201, 204, 304)
        return not ('" 200 ' in record.getMessage() or 
                   '" 201 ' in record.getMessage() or 
                   '" 204 ' in record.getMessage() or 
                   '" 304 ' in record.getMessage())

# Apply filter to werkzeug logger (handles HTTP request logging)
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.addFilter(NoSuccessFilter())

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Setup voice command monitor with socketio instance and auto-start
voice_command_monitor.set_socketio(socketio)
voice_command_monitor.start_voice_command_monitor()

# Setup quantity change monitor with socketio instance and auto-start
quantity_change_monitor.set_socketio(socketio)
quantity_change_monitor.start_quantity_change_monitor()

# Setup RFID state monitor with socketio instance and auto-start
rfid_state_monitor.set_socketio(socketio)
rfid_state_monitor.start_rfid_state_monitor()

# Setup payment webhook listener with socketio instance and auto-start
payment_webhook_listener.set_socketio(socketio, app)
payment_webhook_listener.start_payment_webhook_listener()

# Setup cleanup handlers
def cleanup_voice_command_monitor():
    """Cleanup voice command monitor on app shutdown"""
    voice_command_monitor.stop_voice_command_monitor()

def cleanup_quantity_change_monitor():
    """Cleanup quantity change monitor on app shutdown"""
    quantity_change_monitor.stop_quantity_change_monitor()

def cleanup_rfid_state_monitor():
    """Cleanup RFID state monitor on app shutdown"""
    rfid_state_monitor.stop_rfid_state_monitor()

def signal_handler(signum, frame):
    """Handle SIGINT and SIGTERM signals"""
    print(f"\nReceived signal {signum}, shutting down gracefully...")
    cleanup_voice_command_monitor()
    cleanup_quantity_change_monitor()
    cleanup_rfid_state_monitor()
    print("Cleanup completed. Forcing exit...")
    import os
    os._exit(0)  # Force exit immediately

# Register cleanup handlers
atexit.register(cleanup_voice_command_monitor)
atexit.register(cleanup_quantity_change_monitor)
atexit.register(cleanup_rfid_state_monitor)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Register Blueprints
app.register_blueprint(main_bp)
app.register_blueprint(api_bp, url_prefix='/api')
app.register_blueprint(payment_bp)
app.register_blueprint(loadcell_bp, url_prefix='/api')
app.register_blueprint(debug_bp, url_prefix='/api')
app.register_blueprint(wifi_bp)
app.register_blueprint(webhook_bp, url_prefix='/webhook')

def get_cart():
    """Helper function to get cart from app context"""
    return app.config.get('cart', [])

def set_cart(new_cart):
    """Helper function to set cart in app context"""
    app.config['cart'] = new_cart

def get_loadcell_status():
    """Helper function to get loadcell status"""
    return (
        app.config.get('loadcell_connected', False),
        app.config.get('loadcell_connection_status', 'disconnected')
    )

def set_loadcell_status(connected, status):
    """Helper function to set loadcell status"""
    app.config['loadcell_connected'] = connected
    app.config['loadcell_connection_status'] = status

@app.route('/vendor/socket.io.min.js')
def vendor_socketio_js():
    """Serve the vendored Socket.IO client — works with no internet."""
    resp = app.send_static_file('vendor/socket.io.min.js')
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Ensure charset=utf-8 for JSON
    if response.content_type.startswith('application/json') and 'charset' not in response.content_type:
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

def receive_loadcell_quantity(socketio_instance):
    """
    Minimal backup polling - only for extreme fallback scenarios
    """
    while True:
        current_taken_quantity = globals.get_taken_quantity()
        
        if globals.get_quantity_change_flag():
            # Reset flag after processing
            globals.set_quantity_change_flag(False)
            # Mark as connected if we receive data changes via backup polling
            loadcell_connected, loadcell_connection_status = get_loadcell_status()
            if not loadcell_connected:
                set_loadcell_status(True, "connected")
                emit_connection_status(socketio_instance, "connected", "Loadcell connected successfully!")
            
            # Check for error codes and update cart
            check_loadcell_error_codes()
            cart = get_cart()
            updated_products = update_cart_quantities(cart, current_taken_quantity)
            set_cart(cart)
            
            # Always emit WebSocket update
            emit_loadcell_update(socketio_instance, current_taken_quantity, cart)
            
        else:
            # Even if data hasn't changed, check connection status based on recent reception
            if has_recent_data_reception():
                loadcell_connected, loadcell_connection_status = get_loadcell_status()
                if not loadcell_connected:
                    set_loadcell_status(True, "connected")
                    emit_connection_status(socketio_instance, "connected", "Loadcell data reception confirmed!")
            elif has_any_data():
                # Fallback: if we have any data but not recent reception, still mark as connected
                loadcell_connected, loadcell_connection_status = get_loadcell_status()
                if not loadcell_connected:
                    set_loadcell_status(True, "connected")
                    emit_connection_status(socketio_instance, "connected", "Loadcell data detected - Connection stable!")
        
        time.sleep(1.0)  

def connection_health_monitor(socketio_instance):
    """Minimal health monitor - only for major disconnections"""
    last_data_time = time.time()
    last_known_data = globals.get_loadcell_quantity_snapshot()
    last_status_emitted = None  # Track last status to avoid duplicate emissions
    
    while True:
        try:
            current_time = time.time()
            current_data = globals.get_loadcell_quantity_snapshot()
            
            # Check if data has changed (indicating fresh updates)
            if not np.all(np.array(current_data) == np.array(last_known_data)):
                last_data_time = current_time
                last_known_data = current_data
                
                # If data changed, ensure we're marked as connected
                loadcell_connected, loadcell_connection_status = get_loadcell_status()
                if not loadcell_connected:
                    set_loadcell_status(True, "connected")
                    emit_connection_status(socketio_instance, "connected", 'Loadcell data reception confirmed!')
                    last_status_emitted = "reconnected"
            
            loadcell_connected, loadcell_connection_status = get_loadcell_status()
            
            # Only check for MAJOR disconnection (60 seconds for more tolerance) and only if we don't have recent data reception
            if loadcell_connected and (current_time - last_data_time) > 60 and not has_recent_data_reception():
                if last_status_emitted != "major_disconnection":
                    set_loadcell_status(False, "error")
                    emit_connection_status(socketio_instance, "error", 'Loadcell connection lost - No data received')
                    last_status_emitted = "major_disconnection"
            
            # Auto-reconnect when we have recent data reception (even if all zeros)
            elif has_recent_data_reception() and not loadcell_connected:
                if last_status_emitted != "reconnected":
                    set_loadcell_status(True, "connected")
                    last_data_time = current_time
                    emit_connection_status(socketio_instance, "connected", 'Loadcell connection restored!')
                    last_status_emitted = "reconnected"
                
        except Exception as e:
            pass
        
        time.sleep(20)  # Check every 20 seconds - less frequent for stability

def main():
    """Main function to initialize the application"""
    
    # Load products from JSON file on startup using utility function
    products = load_products_from_json()
    
    # Convert products to cart format with quantity = 0 initially
    cart = []
    for product in products:
        cart_item = {
            **product,
            'qty': 0,  # Initialize quantity to 0
            'manual': False  # Track if manually adjusted
        }
        cart.append(cart_item)
    
    set_cart(cart)
    
    # Set initial status
    set_loadcell_status(False, "connecting")
    
    # Register WebSocket handlers
    register_websocket_handlers(socketio, get_cart)
    
    # Start background threads
    
    # Backup polling thread
    thread2 = threading.Thread(target=receive_loadcell_quantity, args=(socketio,), daemon=True)
    thread2.start()
    
    # Minimal health monitor for BLE disconnection detection
    health_thread = threading.Thread(target=connection_health_monitor, args=(socketio,), daemon=True)
    health_thread.start()
    
    # Run with SocketIO - accessible from LAN
    socketio.run(app, debug=False, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)


def get_local_ip():
    """Lấy địa chỉ IP local của thiết bị"""
    import socket
    try:
        # Tạo socket để lấy IP (không thực sự kết nối)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def start_webserver():
    # Pass socketio instance to BLE module for connection notifications FIRST
    from app.utils.loadcell_ws_utils import set_socketio_instance
    set_socketio_instance(socketio)
    
    # Start BLE loadcell connection only in main process (not Flask reloader)
    main()