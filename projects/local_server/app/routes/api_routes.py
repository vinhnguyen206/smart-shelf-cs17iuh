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
API routes - Basic APIs for products, cart, refresh
"""
import time

from flask import Blueprint, request, jsonify, current_app

from app.modules import globals
from app.utils.loadcell_utils import update_cart_quantities
from app.utils.database_utils import (
    load_products_from_json, 
    load_combos_from_json, 
    load_all_combos_from_json,
    detect_and_apply_combo_pricing,
    calculate_cart_total_with_combos
)

"""
API routes - Basic APIs for products, cart, refresh
"""
import time

from flask import Blueprint, request, jsonify, current_app

from app.modules import globals
from app.utils.loadcell_utils import update_cart_quantities
from app.utils.database_utils import (
    load_products_from_json, 
    load_combos_from_json, 
    load_all_combos_from_json,
    detect_and_apply_combo_pricing,
    calculate_cart_total_with_combos
)

api_bp = Blueprint('api', __name__)

@api_bp.route('/sensor-data')
def get_sensor_data():
    """Get current sensor data from globals"""
    return jsonify({
        'pressure': globals.get_pressure(),
        'temperature': globals.get_temperature(),
        'humidity': globals.get_humidity(),
        'light': globals.get_light(),
        'sound': globals.get_sound(),
        'magnetic': globals.get_magnetic(),
        'timestamp': time.time()
    })

def get_cart():
    """Helper function to get cart from app context"""
    return current_app.config.get('cart', [])

def set_cart(new_cart):
    """Helper function to set cart in app context"""
    current_app.config['cart'] = new_cart

@api_bp.route('/loadcell-data')
def api_loadcell_data():
    """Get loadcell data for each product position"""
    try:
        loadcell_data = globals.get_loadcell_quantity_snapshot()
        
        # Return raw loadcell data including 255 values for error handling
        return jsonify({
            'success': True,
            'raw_loadcell_data': loadcell_data  # Keep original values including 255
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Error getting loadcell data: {str(e)}',
            'raw_loadcell_data': [0] * 15  # Default to 15 empty slots
        })

@api_bp.route('/loadcell-total')
def api_loadcell_total():
    """Get total number of products currently on shelf from loadcell"""
    try:
        loadcell_data = globals.get_loadcell_quantity_snapshot()
        
        # Calculate total products on shelf (exclude 255 values which indicate no sensor/empty)
        total_products = 0
        for value in loadcell_data:
            if value != 255 and value > 0:  # 255 indicates no sensor, 0 means empty
                total_products += value
        
        return jsonify({
            'success': True,
            'total_products': total_products,
            'loadcell_data': loadcell_data
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Error getting loadcell total: {str(e)}',
            'total_products': 0
        })

@api_bp.route('/rfid-state')
def api_rfid_state():
    """Get current RFID state (0 = added/idle, 1 = adding)"""
    try:
        rfid_state = globals.get_rfid_state()
        
        return jsonify({
            'success': True,
            'rfid_state': rfid_state,
            'is_adding': rfid_state == 1  # 1 means adding is in progress
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Error getting RFID state: {str(e)}',
            'rfid_state': 0,
            'is_adding': False
        })

@api_bp.route('/products')
def api_products():
    """Get all products with their current taken_quantity and discount info"""
    try:
        # Get current taken quantities
        taken_quantity = globals.get_taken_quantity()
        
        # Load fresh product data from database
        from app.utils.database_utils import load_products_from_json
        products = load_products_from_json()
        
        # Merge taken_quantity and calculate discount pricing
        for i, product in enumerate(products):
            if i < len(taken_quantity):
                product['qty'] = taken_quantity[i]
            else:
                product['qty'] = 0
            
            # Calculate discounted price if discount exists
            original_price = product.get('price', 0)
            discount = product.get('discount', 0)
            
            if discount > 0:
                discounted_price = original_price * (1 - discount / 100)
                discounted_price = round(discounted_price)  # Round to nearest integer
                product['original_price'] = original_price  # Store original price
                product['price'] = discounted_price  # Update with discounted price
            else:
                product['original_price'] = original_price  # Store same as price if no discount
        
        return jsonify(products)
        
    except Exception as e:
        print(f"[ERROR] Failed to get products: {e}")
        # Fallback to loading from database only
        from app.utils.database_utils import load_products_from_json
        return jsonify(load_products_from_json())

@api_bp.route('/cart')
def api_cart():
    """Get current cart based on real-time taken_quantity and fresh product data"""
    try:
        # Get current taken quantities
        taken_quantity = globals.get_taken_quantity()
        
        # Load fresh product data from database
        from app.utils.database_utils import load_products_from_json
        products = load_products_from_json()
        
        # Build cart from taken_quantity
        cart = []
        for i, qty in enumerate(taken_quantity):
            if qty > 0 and i < len(products):
                product = products[i]
                original_price = product.get('price', 0)
                discount = product.get('discount', 0)
                
                # Calculate discounted price if discount exists
                if discount > 0:
                    discounted_price = original_price * (1 - discount / 100)
                    discounted_price = round(discounted_price)  # Round to nearest integer
                else:
                    discounted_price = original_price
                
                cart.append({
                    'position': i,
                    'quantity': qty,
                    'qty': qty,  # Legacy compatibility
                    'product_id': product.get('product_id'),
                    'product_name': product.get('product_name'),
                    'price': discounted_price,  # Use discounted price
                    'original_price': original_price,  # Always store original for comparison
                    'discount': discount,
                    'img_url': product.get('img_url'),
                    'weight': product.get('weight'),
                    'max_quantity': product.get('max_quantity', 0)
                })
        
        # Apply combo pricing if any
        from app.utils.loadcell_utils import update_cart_with_combo_pricing
        cart_with_combo, applied_combos = update_cart_with_combo_pricing(cart)
        
        # Update app config cache for consistency
        current_app.config['cart'] = cart_with_combo
        
        return jsonify(cart_with_combo)
        
    except Exception as e:
        print(f"[ERROR] Failed to get cart: {e}")
        # Fallback to cached cart if error
        return jsonify(get_cart())

@api_bp.route('/cart/set', methods=['POST'])
def set_cart_api():
    """Set cart contents"""
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        # Set the cart
        set_cart(data)
        
        return jsonify({
            'success': True,
            'message': 'Cart set successfully',
            'cart': data
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Failed to set cart: {str(e)}'
        }), 500

@api_bp.route('/combos')
def api_combos():
    """Get active combos only (for slideshow and public pages)"""
    combos = load_combos_from_json()
    return jsonify(combos)

@api_bp.route('/slideshow-images')
def api_slideshow_images():
    """Get slideshow images from slideshow_images.json + valid combos"""
    try:
        from app.utils.slideshow_utils import get_slideshow_images, load_slideshow_images, load_valid_combos
        
        images = get_slideshow_images()
        
        # Get counts for debugging
        slideshow_count = len(load_slideshow_images())
        valid_combo_count = len(load_valid_combos())
        
        return jsonify({
            'success': True,
            'images': images,
            'count': len(images),
            'sources': {
                'slideshow_images_json': slideshow_count,
                'valid_combos': valid_combo_count,
                'total_unique': len(images)
            }
        })
    except Exception as e:
        print(f"Error loading slideshow images: {e}")
        # Fallback to old method if slideshow_utils fails
        try:
            combos = load_combos_from_json()
            images = []
            
            for combo in combos:
                images.append({
                    'url': combo.get('img', '/static/img/no-image.jpg'),
                    'alt': combo.get('name', 'Combo Image'),
                    'title': combo.get('name', ''),
                    'description': combo.get('desc', ''),
                    'combo_id': combo.get('id'),
                    'price': combo.get('price', 0),
                    'old_price': combo.get('oldPrice', 0)
                })
            
            return jsonify({
                'success': True,
                'images': images,
                'count': len(images),
                'source': 'fallback to combo.json'
            })
        except Exception as fallback_error:
            return jsonify({
                'success': False,
                'message': f'Primary error: {str(e)}, Fallback error: {str(fallback_error)}',
                'images': []
            }), 500

@api_bp.route('/combos/all')
def api_all_combos():
    """Get all combos including expired ones (for admin/debug)"""
    combos = load_all_combos_from_json()
    return jsonify(combos)

@api_bp.route('/refresh-cart', methods=['POST'])
def refresh_cart():
    """Refresh cart with current loadcell data and apply combo pricing"""
    cart = get_cart()
    
    # Update cart quantities with current loadcell data using utility function
    updated_products = update_cart_quantities(cart, globals.loadcell_quantity)
    
    # Apply combo pricing to updated cart
    try:
        cart_with_combos, applied_combos = detect_and_apply_combo_pricing(cart)
        set_cart(cart_with_combos)  # Update cart with combo pricing
        
        # Log combo application
        if applied_combos:
            print(f"🔥 Cart refresh: Applied {len(applied_combos)} combo(s)")
            for combo in applied_combos:
                combo_type = combo.get('combo_type', 'regular')
                if combo_type == 'buy_x_get_y':
                    print(f"  - {combo['combo_name']}: Buy {combo['buy_quantity']} get {combo['get_quantity']} free")
                else:
                    print(f"  - {combo['combo_name']}: {combo.get('savings', 0):,.0f}đ saved")
        
    except Exception as e:
        print(f"Error applying combo pricing in refresh: {e}")
        set_cart(cart)  # Fallback to cart without combo pricing
        cart_with_combos = cart
        applied_combos = []
    
    # Get socketio from app context
    socketio = current_app.extensions.get('socketio')
    if socketio:
        # Import here to avoid circular import
        from app.utils.websocket_utils import emit_loadcell_update
        emit_loadcell_update(socketio, globals.loadcell_quantity, cart_with_combos)
    
    return jsonify({
        'success': True, 
        'message': 'Cart refreshed successfully with combo pricing',
        'cart': cart_with_combos,
        'loadcell_data': globals.loadcell_quantity,
        'updated_products': updated_products,
        'applied_combos': applied_combos,
        'combo_savings': sum(combo.get('savings', 0) for combo in applied_combos)
    })

@api_bp.route('/cart/process', methods=['GET', 'POST'])
def process_cart():
    """Process cart for checkout - validate and prepare order data"""
    try:
        cart = get_cart()
        
        if not cart:
            return jsonify({
                'success': False,
                'message': 'Cart is empty. Please add products to cart.',
                'cart': [],
                'total': 0,
                'suggestions': [
                    'Check loadcell connection',
                    'Refresh page and try again',
                    'Add products to shelf and wait for update'
                ]
            }), 200  # Return 200 instead of 400 for empty cart
        
        # First, apply individual discounts to all cart items
        for item in cart:
            original_price = item.get('original_price') or item.get('price', 0)
            discount = item.get('discount', 0)
            
            # Apply discount if exists and price hasn't been discounted yet
            if discount > 0 and item.get('price', 0) == original_price:
                discounted_price = original_price * (1 - discount / 100)
                discounted_price = round(discounted_price)
                item['price'] = discounted_price
                if 'original_price' not in item:
                    item['original_price'] = original_price
        
        # Then apply combo pricing and calculate total
        updated_cart, applied_combos = detect_and_apply_combo_pricing(cart)
        total, breakdown = calculate_cart_total_with_combos(updated_cart)
        
        valid_items = []
        invalid_items = []
        
        for idx, item in enumerate(updated_cart):
            qty = item.get('qty', item.get('quantity', 0))
            price = item.get('price', 0)
            product_name = item.get('product_name', item.get('name', f'Item {idx}'))
            
            if qty > 0 and price >= 0:
                item_total = qty * price
                valid_items.append({
                    **item,
                    'item_total': item_total,
                    'quantity': qty  # Normalize quantity field
                })
            else:
                invalid_items.append({
                    'index': idx,
                    'name': product_name,
                    'qty': qty,
                    'price': price,
                    'reason': 'Quantity is 0 or price invalid' if qty <= 0 else 'Invalid price'
                })
        
        if not valid_items:
            return jsonify({
                'success': False,
                'message': 'No valid products in cart. All products have quantity = 0 or invalid price.',
                'cart': cart,
                'total': 0,
                'debug': {
                    'valid_items_count': len(valid_items),
                    'invalid_items': invalid_items,
                    'total_items': len(cart),
                    'loadcell_data': list(globals.loadcell_quantity[:5])
                },
                'suggestions': [
                    'Check if loadcell is working',
                    'Place products on shelf to update quantity',
                    'Refresh cart using refresh button'
                ]
            }), 200  # Return 200 with helpful message instead of 400
        
        # Check for any loadcell errors that might affect checkout
        error_positions = []
        warning_positions = []
        for i, val in enumerate(globals.loadcell_quantity):
            if val == 255:  # Loadcell error
                error_positions.append(i)
            elif val in [200, 222]:  # Placement warnings
                warning_positions.append(i)
        
        # Return processed cart data with combo information
        result = {
            'success': True,
            'message': f'Cart processed successfully with {len(valid_items)} products',
            'cart': valid_items,
            'total': total,
            'item_count': len(valid_items),
            'total_quantity': sum(item.get('qty', item.get('quantity', 0)) for item in valid_items),
            'combo_info': {
                'applied_combos': applied_combos,
                'combo_count': len(applied_combos),
                'total_savings': breakdown['combo_savings'],
                'original_total': breakdown['subtotal'],
                'breakdown': breakdown
            },
            'warnings': {
                'loadcell_errors': error_positions,
                'loadcell_warnings': warning_positions,
                'has_errors': len(error_positions) > 0,
                'has_warnings': len(warning_positions) > 0
            },
            'debug': {
                'invalid_items_count': len(invalid_items),
                'processing_time': time.time()
            }
        }
        
        return jsonify(result)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Cart processing error: {str(e)}',
            'cart': [],
            'total': 0,
            'error_details': str(e),
            'suggestions': [
                'Try again in a few seconds',
                'Check server connection',
                'Contact admin if error persists'
            ]
        }), 500

@api_bp.route('/cart/clear', methods=['POST'])
def clear_cart():
    """Clear all items from cart"""
    try:
        set_cart([])
        
        # Emit WebSocket update
        socketio = current_app.extensions.get('socketio')
        if socketio:
            from app.utils.websocket_utils import emit_loadcell_update
            emit_loadcell_update(socketio, globals.loadcell_quantity, [])
        
        return jsonify({
            'success': True,
            'message': 'Cart cleared successfully',
            'cart': []
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to clear cart',
            'error': str(e)
        }), 500

@api_bp.route('/cart/validate', methods=['GET'])
def validate_cart():
    """Validate current cart against loadcell data"""
    try:
        cart = get_cart()
        
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'cart_items': len(cart),
            'total_value': 0
        }
        
        for idx, item in enumerate(cart):
            qty = item.get('qty', 0)
            price = item.get('product_price', 0)
            
            # Check if quantity is valid
            if qty <= 0:
                validation_result['errors'].append(f'Product {item.get("product_name", "Unknown")} has invalid quantity')
                validation_result['valid'] = False
            
            # Check if price is valid
            if price < 0:
                validation_result['errors'].append(f'Product {item.get("product_name", "Unknown")} has invalid price')
                validation_result['valid'] = False
            
            # Check against loadcell data if available
            if idx < len(globals.loadcell_quantity):
                loadcell_val = globals.loadcell_quantity[idx]
                if loadcell_val == 255:
                    validation_result['warnings'].append(f'Loadcell at position {idx} error - manual check required')
                elif loadcell_val in [200, 222]:
                    validation_result['warnings'].append(f'Product at position {idx} not placed correctly')
            
            validation_result['total_value'] += qty * price
        
        return jsonify(validation_result)
        
    except Exception as e:
        return jsonify({
            'valid': False,
            'errors': [f'Lỗi validate giỏ hàng: {str(e)}'],
            'warnings': []
        }), 500

@api_bp.route('/cart/status', methods=['GET'])
def cart_status():
    """Get comprehensive cart status information"""
    try:
        cart = get_cart()
        
        # Calculate basic stats
        total_items = len(cart)
        total_quantity = sum(item.get('qty', 0) for item in cart)
        total_value = sum(item.get('qty', 0) * item.get('product_price', 0) for item in cart)
        
        # Check loadcell status
        loadcell_errors = []
        loadcell_warnings = []
        for i, val in enumerate(globals.loadcell_quantity):
            if val == 255:
                loadcell_errors.append(i)
            elif val in [200, 222]:
                loadcell_warnings.append(i)
        
        # Check if cart is ready for checkout
        ready_for_checkout = (
            total_items > 0 and 
            total_quantity > 0 and 
            total_value > 0 and
            len(loadcell_errors) == 0
        )
        
        return jsonify({
            'cart_summary': {
                'total_items': total_items,
                'total_quantity': total_quantity,
                'total_value': total_value,
                'ready_for_checkout': ready_for_checkout
            },
            'loadcell_status': {
                'errors': loadcell_errors,
                'warnings': loadcell_warnings,
                'error_count': len(loadcell_errors),
                'warning_count': len(loadcell_warnings)
            },
            'cart_items': cart,
            'timestamp': time.time()
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'cart_summary': {
                'total_items': 0,
                'total_quantity': 0,
                'total_value': 0,
                'ready_for_checkout': False
            }
        }), 500

@api_bp.route('/cart/debug', methods=['GET'])
def debug_cart():
    """Debug endpoint to check cart contents"""
    cart = get_cart()
    return jsonify({
        'cart_length': len(cart),
        'cart_sample': cart[:3] if cart else [],  # First 3 items
        'cart_full': cart,
        'loadcell_data': list(globals.loadcell_quantity),
        'loadcell_length': len(globals.loadcell_quantity)
    })


@api_bp.route('/cart/combo-info', methods=['GET'])
def get_cart_combo_info():
    """Get combo information for current cart"""
    try:
        cart = get_cart()
        
        if not cart:
            return jsonify({
                'success': True,
                'message': 'Cart is empty',
                'cart': [],
                'combo_info': {
                    'applied_combos': [],
                    'combo_count': 0,
                    'total_savings': 0,
                    'original_total': 0,
                    'final_total': 0
                }
            })
        
        # Apply combo detection and pricing
        updated_cart, applied_combos = detect_and_apply_combo_pricing(cart)
        total, breakdown = calculate_cart_total_with_combos(cart)
        
        return jsonify({
            'success': True,
            'message': f'Found {len(applied_combos)} combo(s) in cart',
            'cart': updated_cart,
            'combo_info': {
                'applied_combos': applied_combos,
                'combo_count': len(applied_combos),
                'total_savings': breakdown['combo_savings'],
                'original_total': breakdown['subtotal'],
                'final_total': total,
                'breakdown': breakdown
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error getting combo info: {str(e)}',
            'cart': get_cart(),
            'combo_info': {
                'applied_combos': [],
                'combo_count': 0,
                'total_savings': 0,
                'original_total': 0,
                'final_total': 0
            }
        }), 500


@api_bp.route('/cart/apply-combos', methods=['POST'])
def apply_combos_to_cart():
    """Manually apply combo pricing to current cart"""
    try:
        # Get cart from request body instead of global cart
        data = request.get_json()
        cart = data.get('cart_items', []) if data else []
        
        if not cart:
            return jsonify({
                'success': False,
                'message': 'Cart is empty',
                'cart': []
            })
        
        # Apply combo pricing
        updated_cart, applied_combos = detect_and_apply_combo_pricing(cart)
        total, breakdown = calculate_cart_total_with_combos(cart)
        
        # Don't update global cart - just return the combo-applied cart
        # set_cart(updated_cart)
        
        # Don't emit WebSocket update - this is just a calculation endpoint
        # socketio = current_app.extensions.get('socketio')
        # if socketio:
        #     from app.utils.websocket_utils import emit_loadcell_update
        #     emit_loadcell_update(socketio, globals.loadcell_quantity, updated_cart)
        
        return jsonify({
            'success': True,
            'message': f'Applied {len(applied_combos)} combo(s) to cart',
            'cart_items': updated_cart,  # Changed from 'cart' to 'cart_items' to match frontend
            'applied_combos': applied_combos,
            'total_savings': breakdown['combo_savings'],
            'original_total': breakdown['subtotal'],
            'final_total': total
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error applying combos: {str(e)}',
            'cart': get_cart()
        }), 500


@api_bp.route('/all-products')
def api_all_products():
    """API endpoint to get all products data (different from cart products)"""
    try:
        products = load_products_from_json()
        return jsonify(products)
    except Exception as e:
        return jsonify([]), 500

@api_bp.route('/set-print-bill', methods=['POST'])
def set_print_bill():
    """API endpoint to set print bill preference"""
    try:
        data = request.get_json()
        
        if data is None:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400
        
        print_bill = data.get('print_bill', False)
        log_choice = data.get('log_choice', '')
        
        # Set the global print_bill flag
        globals.set_print_bill(print_bill)
        
        # Log print_bill value to terminal
        print(f'print_bill = {print_bill}')
        
        return jsonify({
            'success': True, 
            'message': f'Print bill set to {print_bill}',
            'print_bill': print_bill
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@api_bp.route('/test-voice-command', methods=['POST'])
def test_voice_command():
    """Test voice command with proper SocketIO integration"""
    try:
        data = request.get_json()
        command = data.get('command', '')
        
        if not command:
            return jsonify({'success': False, 'message': 'Command is required'}), 400
        
        # Get SocketIO instance
        socketio = current_app.extensions.get('socketio')
        if not socketio:
            return jsonify({'success': False, 'message': 'SocketIO not available'}), 500
        
        # Process the voice command directly with SocketIO
        command_lower = command.lower().strip()
        
        if "combo" in command_lower or "discount" in command_lower:
            socketio.emit('redirect_to_combo', {
                'url': '/combo',
                'message': f'Voice command "{command}" detected! Redirecting to combo page...'
            })
            return jsonify({
                'success': True, 
                'message': f'Combo command processed: {command}',
                'action': 'redirect_to_combo'
            })
        elif "pay" in command_lower or "payment" in command_lower or "thanh toán" in command_lower:
            # Check if cart has items first
            taken_quantity = globals.get_taken_quantity()
            has_products_taken = any(qty > 0 for qty in taken_quantity)
            
            if not has_products_taken:
                socketio.emit('empty_cart_notification', {
                    'message': 'Giỏ hàng trống! Vui lòng chọn sản phẩm trước khi thanh toán.'
                })
                return jsonify({
                    'success': False,
                    'message': 'Cart is empty - cannot process payment command',
                    'action': 'empty_cart_notification'
                })
            
            socketio.emit('create_order_and_redirect', {
                'message': f'Voice command "{command}" detected! Creating order and redirecting to payment...'
            })
            return jsonify({
                'success': True,
                'message': f'Payment command processed: {command}',
                'action': 'create_order_and_redirect'
            })
        elif "cart" in command_lower or "giỏ hàng" in command_lower:
            socketio.emit('redirect_to_cart', {
                'url': '/cart',
                'message': f'Voice command "{command}" detected! Redirecting to cart page...'
            })
            return jsonify({
                'success': True,
                'message': f'Cart command processed: {command}',
                'action': 'redirect_to_cart'
            })
        elif "back" in command_lower or "quay lại" in command_lower:
            socketio.emit('redirect_to_main', {
                'url': '/',
                'message': f'Voice command "{command}" detected! Redirecting to main page...'
            })
            return jsonify({
                'success': True,
                'message': f'Back command processed: {command}',
                'action': 'redirect_to_main'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Unknown voice command: {command}',
                'action': 'unknown'
            })
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@api_bp.route('/print-terminal', methods=['POST'])
def print_to_terminal():
    """Print message to server terminal"""
    try:
        data = request.json
        message = data.get('message', '')
        
        if message:
            print(message)  # Print to terminal
            return jsonify({
                'success': True,
                'message': f'Printed to terminal: {message}'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No message provided'
            }), 400
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    
@api_bp.route('/added-product', methods=['POST'])
def added_products():
    """Complete adding products - triggered by button click"""
    try:
        data = request.json
        message = data.get('message', '')
        
        # Set RFID state back to 0 (added/idle)
        globals.set_rfid_state(0)
        
        # Set bool_rfid_devices to True to trigger the state monitor
        globals.set_bool_rfid_devices(True)
        
        if message:
            print(f"[SHELF] {message}")  # Print to terminal
        
        print(f"[SHELF] Complete adding: rfid_state=0, bool_rfid_devices=True")
        
        return jsonify({
            'success': True,
            'message': f'Complete adding products. State updated.',
            'rfid_state': 0
        })
            
    except Exception as e:
        print(f"[ERROR] Failed to complete adding: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@api_bp.route('/slideshow-images/manage', methods=['GET', 'POST', 'DELETE'])
def manage_slideshow_images():
    """Manage slideshow images"""
    try:
        from app.utils.slideshow_utils import (
            load_slideshow_images, 
            add_slideshow_image,
            remove_slideshow_image_by_url
        )
        
        if request.method == 'GET':
            # Get all slideshow images  
            all_images = load_slideshow_images()
            
            return jsonify({
                'success': True,
                'all_images': all_images,
                'total_count': len(all_images)
            })
            
        elif request.method == 'POST':
            # Add new slideshow image
            data = request.get_json()
            image_url = data.get('image_url')
            
            if not image_url:
                return jsonify({
                    'success': False,
                    'message': 'image_url is required'
                }), 400
            
            success = add_slideshow_image(image_url)
            
            if success:
                return jsonify({
                    'success': True,
                    'message': f'Added slideshow image: {image_url}'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'Failed to add slideshow image: {image_url}'
                }), 400
                
        elif request.method == 'DELETE':
            # Remove slideshow image
            data = request.get_json()
            image_url = data.get('image_url')
            
            if not image_url:
                return jsonify({
                    'success': False,
                    'message': 'image_url is required'
                }), 400
            
            success = remove_slideshow_image_by_url(image_url)
            
            if success:
                return jsonify({
                    'success': True,
                    'message': f'Removed slideshow image: {image_url}'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'Failed to remove slideshow image: {image_url}'
                }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error managing slideshow images: {str(e)}'
        }), 500
    