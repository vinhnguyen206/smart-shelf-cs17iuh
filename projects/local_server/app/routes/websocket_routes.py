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
WebSocket routes - WebSocket event handlers
"""
import threading
import time
import os
from datetime import datetime, timezone
from flask import current_app, request
from flask_socketio import emit
import numpy as np

from app.modules import globals
from app.services.vietqr_payment_service import VietQRPaymentAPI
from app.utils.database_utils import save_order, save_order_details, load_products_from_json
from app.utils.websocket_utils import emit_loadcell_update
from app.modules.cloud_sync import post_order_data_to_cloud
from app.utils.sound_utils import speech_text, play_sound
from app.utils.string_utils import remove_accents

def format_currency(value):
    return "{:,}".format(value).replace(",", ".")

def safe_to_list(arr):
    return arr.tolist() if isinstance(arr, np.ndarray) else arr

def register_websocket_handlers(socketio, get_cart_func):
    """Register all WebSocket event handlers"""
    
    # Track connected clients to prevent duplicate combo applications
    connected_clients = set()
    
    @socketio.on('connect')
    def handle_connect(auth):
        from app.webserver import get_loadcell_status
        
        # Get client session ID to track unique connections
        client_id = request.sid
        
        # Check if this client already connected recently
        if client_id in connected_clients:
            print(f"Client {client_id} already connected, skipping combo application")
            cart = get_cart_func()
        else:
            connected_clients.add(client_id)
            cart = get_cart_func()
            
            # Apply combo pricing only for new connections
            try:
                from app.utils.database_utils import detect_and_apply_combo_pricing
                cart_with_combos, applied_combos = detect_and_apply_combo_pricing(cart)
                
                # Update app cart config
                current_app.config['cart'] = cart_with_combos
                
                if applied_combos:
                    print(f"Client connect: Applied {len(applied_combos)} combo(s)")
                cart = cart_with_combos
            except Exception as e:
                print(f"Error applying combo pricing on connect: {e}")
        
        emit('loadcell_update', {
            'loadcell_data': safe_to_list(globals.taken_quantity),
            'cart': cart
        })
        
        # Check if loadcell is already connected and emit status
        try:
            loadcell_connected, loadcell_status = get_loadcell_status()
            if loadcell_connected:
                emit('loadcell_connected', {
                    'status': 'connected',
                    'message': 'Loadcell connected and ready!'
                })
        except Exception as e:
            pass

    @socketio.on('disconnect')
    def handle_disconnect():
        # Remove client from connected set
        client_id = request.sid
        if client_id in connected_clients:
            connected_clients.remove(client_id)
            # print(f"Client {client_id} disconnected and removed from tracking")

    @socketio.on('request_cart_update')
    def handle_cart_request():
        cart = get_cart_func()
        
        # Apply combo pricing when cart update is requested
        try:
            from app.utils.database_utils import detect_and_apply_combo_pricing
            cart_with_combos, applied_combos = detect_and_apply_combo_pricing(cart)
            
            # Update app cart config
            current_app.config['cart'] = cart_with_combos
            
            if applied_combos:
                print(f"Cart update request: Applied {len(applied_combos)} combo(s)")
        except Exception as e:
            print(f"Error applying combo pricing on cart request: {e}")
            cart_with_combos = cart
        
        emit('loadcell_update', {
            'loadcell_data': safe_to_list(globals.taken_quantity),
            'cart': cart_with_combos
        })

    @socketio.on('rfid_input')
    def handle_rfid_input(data):
        """Handle RFID input via WebSocket - deprecated, hardware listener handles RFID"""
        rfid_code = data.get('rfid_code', '').strip()
        
        # Log for debugging but don't process - hardware listener handles RFID
        print(f"Received RFID input via WebSocket: {rfid_code} (ignored - using hardware listener)")
        print("Note: RFID processing is now handled by hardware listener in listen_rfid.py")
        print("and rfid_state_monitor.py which emits 'employee_adding_max_quantity' event")

    @socketio.on('generate_qr_request')
    def handle_qr_request(data):
        """Handle QR generation request via WebSocket - no caching for unique order IDs"""
        
        order_id = data.get('orderId')
        total = data.get('total')
        
        print(f'WebSocket QR generation request: orderId={order_id}, total={total}')
        
        # Always generate fresh QR for each order to ensure correct order ID in transfer content
        
        def qr_generation_task():
            try:
                # Emit initial progress - start immediately
                socketio.emit('qr_generation_progress', {
                    'status': 'processing', 
                    'progress': 20,
                    'order_id': order_id,
                    'message': 'Generating QR code...'
                })
                
                # Call VietQR API immediately - no artificial delays
                qr_data = VietQRPaymentAPI.generate_qr(total, order_id)
                
                # Emit near completion immediately after API success
                socketio.emit('qr_generation_progress', {
                    'status': 'processing', 
                    'progress': 95,
                    'order_id': order_id,
                    'message': 'Completing QR code generation...'
                })
                
                # Emit completion
                socketio.emit('qr_generation_complete', {
                    'success': True,
                    'qrUrl': qr_data['data']['qrDataURL'],
                    'order_id': order_id,
                    'total': total,
                    'message': 'QR code generated successfully!'
                })
                
                print(f'WebSocket QR generation successful for order {order_id}')
                
                # Auto-start payment monitoring after QR generation
                # COMMENTED OUT - Using webhook listener instead of polling
                # print(f'Auto-starting payment monitoring for order {order_id}')
                # auto_start_payment_monitoring(
                #     socketio, 
                #     order_id, 
                #     total, 
                #     data.get('products', [])
                # )
                
            except Exception as e:
                print(f'WebSocket QR generation failed for order {order_id}: {e}')
                socketio.emit('qr_generation_complete', {
                    'success': False,
                    'error': str(e),
                    'order_id': order_id,
                    'total': total,
                    'fallback_message': f'Transfer {total:,} VND with content: {order_id}',
                    'message': 'Unable to generate QR code. Please transfer manually.'
                })
        
        # Start QR generation in background thread
        threading.Thread(target=qr_generation_task, daemon=True).start()

    # Track active payment monitoring threads
    payment_monitoring_threads = {}
    
    def create_payment_monitoring_task(socketio, order_id, total, products, stop_flag, monitoring_type="auto"):
        """Create a payment monitoring task function"""
        def payment_monitoring_task():
            print(f'Starting {monitoring_type} payment monitoring for order {order_id}, total {total}')
            
            # Load Sepay config from globals
            sepay_config = globals.sepay_info
            SEPAY_AUTH_TOKEN = sepay_config.get("SEPAY_AUTH_TOKEN", "")
            SEPAY_BANK_ACCOUNT_ID = sepay_config.get("SEPAY_BANK_ACCOUNT_ID", "")
            add_info = f"Pay for snack machine {order_id}"  # Match with QR generation content
            
            # Debug SEPAY configuration
            if not SEPAY_AUTH_TOKEN:
                print(f'SEPAY_AUTH_TOKEN not configured')
            if not SEPAY_BANK_ACCOUNT_ID:
                print(f'SEPAY_BANK_ACCOUNT_ID not configured')
            
            print(f'Looking for payment with content: "{add_info}" or order_id: "{order_id}"')
            
            timeout = 300  # 300 seconds (5 minutes)
            # This polling path is only the fallback when the MQTT webhook is
            # unavailable; 2s keeps the SePay API load at ~150 requests per
            # payment window instead of ~1000 at 0.3s.
            interval = 2
            start = time.time()
            check_count = 0
            
            while time.time() - start < timeout:
                # Check if monitoring should stop
                if stop_flag['stop_flag']:
                    print(f'{monitoring_type} payment monitoring stopped for order {order_id} (stop flag)')
                    return
                    
                check_count += 1
                
                # Emit monitoring status every 5 checks
                if check_count % 5 == 0:
                    remaining_time = int(timeout - (time.time() - start))
                    socketio.emit('payment_monitoring_status', {
                        'order_id': order_id,
                        'status': 'monitoring',
                        'check_count': check_count,
                        'remaining_time': remaining_time
                    })
                
                # print(f'{monitoring_type} payment check #{check_count} for order {order_id}...')  # Commented out - webhook handles payment verification
                
                success, tx = VietQRPaymentAPI.check_sepay_payment(
                    SEPAY_AUTH_TOKEN, SEPAY_BANK_ACCOUNT_ID, total, add_info, order_id
                )
                
                # print(f'Check result: success={success}, tx_found={tx is not None}')  # Commented out - webhook handles payment verification
                # if tx:  # Commented out - webhook handles payment verification
                #     print(f'Transaction content: {tx.get("transaction_content", "N/A")}')
                
                # Handle authorization issues
                if success == "unauthorized":
                    print(f'SEPAY authorization failed - token may be expired')
                    if check_count >= 5:  # After 5 failed attempts due to auth issues
                        # Just log the error, don't show alert to user (countdown handles all timing)
                        print('API authentication error after 5 attempts')
                        # Don't emit payment_monitoring_status - keep UI clean with just countdown
                        # Don't break, continue monitoring in case manual test is triggered
                
                if success and tx and order_id in tx.get('transaction_content', ''):
                    # Save order and order_detail to JSON file when payment is successful
                    print(f'DEBUG: Creating order details from products: {products}')
                    
                    order_details = []
                    order_details_products_name = []
                    for p in products:
                        product_id = p.get('product_id', p.get('_id', ''))
                        product_name = p.get('product_name', '')
                        qty = p.get('qty', 0)
                        price = p.get('price', 0)
                        
                        # Debug log for each product
                        print(f'DEBUG: Processing product - ID: {product_id}, Name: {product_name}, Qty: {qty}, Price: {price}')
                        
                        # Skip products with missing critical data
                        if not product_id or qty <= 0:
                            print(f'WARNING: Skipping product with missing data - ID: {product_id}, Qty: {qty}')
                            continue
                        
                        order_details_products_name.append(remove_accents(product_name))
                        order_details.append({
                            'product_id': product_id,
                            'quantity': qty,
                            'price': price,
                            'total_price': qty * price
                        })
                    
                    print(f'DEBUG: Created {len(order_details)} order details')

                    shelf_id = os.getenv("SHELF_ID_CLOUD")
                    order_data = {
                        'status': 'paid',
                        'order_code': order_id,
                        'shelf_id': shelf_id,
                        'total_bill': total,
                        'orderDetails': order_details
                    }
                    
                    print(f'DEBUG: Final order_data to send to cloud:')
                    print(f'  - Order ID: {order_id}')
                    print(f'  - Total: {total}')
                    print(f'  - Order Details Count: {len(order_details)}')
                    print(f'  - Order Details: {order_details}')
                    
                    print(f'{monitoring_type} payment successful! Order {order_id}, transaction: {tx.get("id", "N/A")}')
                    
                    # Set payment verified to True
                    globals.set_payment_verified(True)
                    
                    # Clean up monitoring thread
                    if order_id in payment_monitoring_threads:
                        del payment_monitoring_threads[order_id]
                    
                    # Print invoice if requested
                    success_message = f'Payment successful for order {order_id}!' if monitoring_type == "auto" else 'Thanh toán thành công!'
                    
                    # Emit payment success
                    socketio.emit('payment_received', {
                        'order_id': order_id,
                        'transaction': tx,
                        'success': True,
                        'message': success_message
                    })

                    # Khang post-payment event handling
                    ### Voice notification success ###
                    total_price = order_data['total_bill']
                    # abspath is required: mpg123 cannot resolve a path that
                    # still contains the .py file as a directory component
                    sound_path = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/ting.mp3"))
                    threading.Thread(target=play_sound, args=(sound_path,), daemon=True).start()
                    threading.Thread(target=speech_text, args=("Thanh toán thành công " + str(total_price) + " đồng",), daemon=True).start()

                    ### Send order data to cloud (background - UI already notified) ###
                    print(order_data)
                    print("Send order data to cloud")
                    threading.Thread(target=post_order_data_to_cloud, args=(order_data,), daemon=True).start()
                    
                    ### Print bill ###
                    if globals.get_print_bill():
                        print("Printing bill...")
                        ### Write txt bill file ###
                        bill_file_path = os.path.abspath(os.path.join(__file__, "../../..", "app/static/txt/bill.txt"))
                        with open(bill_file_path, "w", encoding="utf-8") as f:
                            f.write("       KỆ HÀNG CS17IUH        \n")
                            f.write("                              \n")
                            f.write("  Địa chi: 12 Nguyên Văn Bao, \n")
                            f.write("  Phường Hạnh Thông, TP.HCM   \n")
                            f.write("       SDT: 0356972399        \n")
                            f.write(" ---------------------------- \n")
                            f.write("       HÓA ĐƠN BÁN HÀNG       \n")
                            f.write("                              \n")
                            f.write(f" Mã HD    : {order_data['order_code']}\n")
                            f.write(f" Kệ hàng  : CS17IUH-01 \n")
                            f.write(f" Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
                            f.write(" ---------------------------- \n")
                            f.write("     SL     Giá bán   T.Tiên  \n")
                            f.write(" ---------------------------- \n")

                            for i,item in enumerate(order_details):
                                f.write(f" {order_details_products_name[i]:<28} \n")
                                f.write(f"     {item['quantity']:<7}{format_currency(item['price']):<10}{format_currency(item['total_price'])}\n")
                            
                            f.write("                              \n")
                            f.write(" ---------------------------- \n")
                            f.write(f" THANH TOÁN:      {format_currency(order_data['total_bill'])} VND \n")
                            f.write(" ---------------------------- \n")
                            f.write("                              \n")
                            f.write("                              \n")
                            f.write("       Cam ơn quý khách!      \n")

                        print(f"Hóa đơn đã được lưu vào {bill_file_path}")
                    ###################################
                    return
                    
                time.sleep(interval)
            
            # Handle timeout
            if monitoring_type == "auto":
                print(f'Auto payment monitoring timeout for order {order_id}')
                if order_id in payment_monitoring_threads:
                    del payment_monitoring_threads[order_id]
                
                # No need to emit status - timeout is handled by frontend countdown
                # socketio.emit('payment_monitoring_status', {
                #     'order_id': order_id,
                #     'status': 'timeout',
                #     'message': f'Automatic checking timeout for order {order_id}. Please check manually.'
                # })
            else:
                print(f'Manual payment monitoring timeout for order {order_id}')
                socketio.emit('payment_timeout', {
                    'order_id': order_id,
                    'message': 'Hết thời gian thanh toán. Vui lòng thử lại.'
                })
        
        return payment_monitoring_task
    
    def auto_start_payment_monitoring(socketio, order_id, total, products):
        """Auto-start payment monitoring after QR generation"""
        
        # Stop any existing monitoring for this order
        if order_id in payment_monitoring_threads:
            payment_monitoring_threads[order_id]['stop_flag'] = True
            
        # Create stop flag for this monitoring thread
        stop_flag = {'stop_flag': False}
        payment_monitoring_threads[order_id] = stop_flag
        
        print(f'Auto payment monitoring started for order {order_id}')
        
        # Create and start payment monitoring task
        payment_task = create_payment_monitoring_task(
            socketio, 
            order_id, 
            total, 
            products, 
            stop_flag, 
            "auto"
        )
        threading.Thread(target=payment_task, daemon=True).start()
    
    @socketio.on('payment_monitoring_stop')
    def handle_payment_monitoring_stop(data):
        """Handle request to stop payment monitoring"""
        order_id = data.get('order_id')
        reason = data.get('reason', 'manual')
        
        if order_id in payment_monitoring_threads:
            thread_info = payment_monitoring_threads[order_id]
            thread_info['stop_flag'] = True
            print(f"Payment monitoring stopped for order {order_id} (reason: {reason})")
            
            # Clean up thread reference
            del payment_monitoring_threads[order_id]
            
            # No need to emit status - keep UI clean with just countdown
            # emit('payment_monitoring_status', {
            #     'order_id': order_id,
            #     'status': 'stopped',
            #     'reason': reason,
            #     'message': f'Stopped payment checking for order {order_id}'
            # })

    @socketio.on('start_payment_monitoring')
    def handle_payment_monitoring(data):
        """Handle payment monitoring via WebSocket"""
        
        order_id = data.get('orderId')
        total = data.get('total')
        products = data.get('products', [])
        
        # Stop any existing monitoring for this order
        if order_id in payment_monitoring_threads:
            payment_monitoring_threads[order_id]['stop_flag'] = True
            
        # Create stop flag for this monitoring thread
        stop_flag = {'stop_flag': False}
        payment_monitoring_threads[order_id] = stop_flag
        
        print(f'Manual payment monitoring started for order {order_id}')
        
        # Create and start payment monitoring task
        payment_task = create_payment_monitoring_task(
            socketio, 
            order_id, 
            total, 
            products, 
            stop_flag, 
            "manual"
        )
        threading.Thread(target=payment_task, daemon=True).start()

    @socketio.on('manual_quantity_update')
    def handle_manual_quantity_update(data):
        """Handle manual quantity update via WebSocket"""
        
        try:
            position = data.get('position')
            quantity = data.get('quantity')
            
            # Validate input
            if position is None or quantity is None:
                emit('manual_quantity_result', {
                    'success': False, 
                    'message': 'Missing position or quantity'
                })
                return
            
            if not isinstance(position, int) or position < 0 or position >= 15:
                emit('manual_quantity_result', {
                    'success': False, 
                    'message': 'Position must be 0-14'
                })
                return
                
            if not isinstance(quantity, int) or quantity < 0:
                emit('manual_quantity_result', {
                    'success': False, 
                    'message': 'Quantity must be >= 0'
                })
                return
            
            # Only allow manual update for loadcell error (255)
            if globals.loadcell_quantity[position] != 255:
                emit('manual_quantity_result', {
                    'success': False, 
                    'message': 'Manual update only allowed for loadcell error (255)'
                })
                return
            
            # Update cart
            cart = current_app.config.get('cart', [])
            products = load_products_from_json()
            product = products[position]
            
            # Find existing item in cart
            existing_item = next((item for item in cart if item.get('product_id') == product.get('product_id')), None)
            
            if quantity > 0:
                if existing_item:
                    existing_item.update({'qty': quantity, 'manual_override': True, 'error_position': position})
                else:
                    cart.append({**product, 'qty': quantity, 'manual_override': True, 'error_position': position})
            elif existing_item:
                cart.remove(existing_item)
            
            # Update cart in app config
            current_app.config['cart'] = cart
            
            # Apply combo pricing to updated cart
            try:
                from app.utils.database_utils import detect_and_apply_combo_pricing
                cart_with_combos, applied_combos = detect_and_apply_combo_pricing(cart)
                current_app.config['cart'] = cart_with_combos
                
                # Log combo application
                if applied_combos:
                    print(f"🔥 Manual update: Applied {len(applied_combos)} combo(s)")
                    for combo in applied_combos:
                        combo_type = combo.get('combo_type', 'regular')
                        if combo_type == 'buy_x_get_y':
                            print(f"  - {combo['combo_name']}: Buy {combo['buy_quantity']} get {combo['get_quantity']} free")
                        else:
                            print(f"  - {combo['combo_name']}: {combo.get('savings', 0):,.0f}đ saved")
            except Exception as e:
                print(f"Error applying combo pricing in manual update: {e}")
                cart_with_combos = cart
                applied_combos = []
            
            # Emit success and broadcast update to all clients
            emit('manual_quantity_result', {
                'success': True,
                'message': f'Updated {product.get("product_name", "product")} to {quantity}',
                'position': position,
                'quantity': quantity,
                'applied_combos': applied_combos,
                'combo_savings': sum(combo.get('savings', 0) for combo in applied_combos)
            })
            
            # Broadcast loadcell update to all clients with combo-applied cart
            socketio.emit('loadcell_update', {
                'loadcell_data': safe_to_list(globals.loadcell_quantity),
                'cart': cart_with_combos
            })
            
            print(f'Manual quantity updated: position={position}, quantity={quantity}')
            
        except Exception as e:
            print(f'Manual quantity error: {e}')
            emit('manual_quantity_result', {
                'success': False, 
                'message': 'Update failed'
            })

    @socketio.on('request_connection_status')
    def handle_connection_status_request():
        """Handle request for current connection status (used in loading page)"""
        from app.webserver import get_loadcell_status
        
        try:
            loadcell_connected, loadcell_status = get_loadcell_status()
            
            if loadcell_connected:
                # If loadcell is already connected, emit connected event immediately
                socketio.emit('loadcell_connected', {
                    'status': 'connected',
                    'message': 'Loadcell đã được kết nối từ trước!'
                })
            else:
                # Still connecting
                socketio.emit('loadcell_connecting', {
                    'status': 'connecting', 
                    'message': 'Đang kết nối với loadcell...'
                })
        except Exception as e:
            print(f"Error checking connection status: {e}")
            socketio.emit('loadcell_connecting', {
                'status': 'connecting',
                'message': 'Đang kiểm tra kết nối...'
            })

    @socketio.on('request_loadcell_redirect_check')
    def handle_loadcell_redirect_check(data):
        """Handle loadcell change detection for redirect (used in QR page)"""
        current_loadcell = data.get('current_loadcell')
        
        # Get current loadcell data
        live_loadcell = safe_to_list(globals.taken_quantity)
        
        # Compare with stored data
        if current_loadcell != live_loadcell:
            emit('loadcell_changed_redirect', {
                'changed': True,
                'new_loadcell': live_loadcell,
                'redirect_url': '/'
            })
        else:
            emit('loadcell_changed_redirect', {
                'changed': False,
                'current_loadcell': live_loadcell
            })

    @socketio.on('slideshow_page_enter')
    def handle_slideshow_page_enter():
        """Handle slideshow page enter - start tracking quantity changes"""
        from app.modules.quantity_change_monitor import set_slideshow_status
        set_slideshow_status(True)
        print("User entered slideshow page - quantity change tracking enabled")

    @socketio.on('slideshow_page_leave')
    def handle_slideshow_page_leave():
        """Handle slideshow page leave - stop tracking quantity changes"""
        from app.modules.quantity_change_monitor import set_slideshow_status
        set_slideshow_status(False)
        # print("User left slideshow page - quantity change tracking disabled")

    # RFID State monitoring events
    @socketio.on('employee_adding_max_quantity')
    def handle_employee_adding_max_quantity():
        """Handle employee adding max_quantity event - redirect to shelf page"""
        print("Employee adding max_quantity detected via WebSocket")
        # This event is automatically handled by the client-side JavaScript

    @socketio.on('max_quantity_added_notification')
    def handle_max_quantity_added_notification():
        """Handle max_quantity added notification event"""
        print("Max_quantity added successfully notification via WebSocket")
        # This event is automatically handled by the client-side JavaScript
