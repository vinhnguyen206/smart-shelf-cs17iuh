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
Loadcell routes - Handle loadcell, hardware monitoring, manual quantity
"""
import time

import numpy as np
from flask import Blueprint, request, jsonify, current_app

from app.modules import globals
from app.utils.loadcell_utils import (
    has_real_data, 
    has_any_data, 
    get_error_messages, 
    get_error_codes_info,
    has_recent_data_reception
)
from app.utils.status_utils import get_status_message
from app.utils.database_utils import load_products_from_json

loadcell_bp = Blueprint('loadcell', __name__)

def safe_to_list(arr):
    return arr.tolist() if isinstance(arr, np.ndarray) else arr

def get_cart():
    """Helper function to get cart from app context"""
    return current_app.config.get('cart', [])

def get_loadcell_status():
    """Helper function to get loadcell status from app context"""
    return (
        current_app.config.get('loadcell_connected', False),
        current_app.config.get('loadcell_connection_status', 'disconnected')
    )

@loadcell_bp.route('/loadcell')
def api_loadcell():
    snapshot = globals.get_taken_quantity()
    return jsonify(safe_to_list(snapshot))

@loadcell_bp.route('/loadcell-status')
def api_loadcell_status():
    """API endpoint to check loadcell connection status"""
    loadcell_connected, loadcell_connection_status = get_loadcell_status()
    
    # Get thread-safe snapshot of loadcell data
    loadcell_snapshot = globals.get_taken_quantity()

    # Check if we're receiving real data using utility function
    has_real_data_val = has_real_data()
    
    # Check if we have any data (even error codes) using utility function
    has_any_data_val = has_any_data()
    
    # Get error messages using utility function
    error_messages = get_error_messages()
    
    # Check if we have recent data reception using utility function
    has_recent_reception = has_recent_data_reception()
    
    # Debug info
    current_time = time.time()
    
    return jsonify({
        'connected': loadcell_connected,
        'status': loadcell_connection_status,
        'has_data': has_real_data_val,
        'has_any_data': has_any_data_val,
        'has_recent_reception': has_recent_reception,
        'loadcell_quantity': safe_to_list(loadcell_snapshot),
        'error_messages': error_messages,
        'error_codes': get_error_codes_info(),
        'message': get_status_message(loadcell_connection_status),
        'timestamp': current_time,
        'data_summary': {
            'total_slots': len(loadcell_snapshot),
            'non_zero_slots': sum(1 for val in loadcell_snapshot if val != 0),
            'error_slots': sum(1 for val in loadcell_snapshot if val in [200, 222, 255]),
            'valid_data_slots': sum(1 for val in loadcell_snapshot if val > 0 and val not in [200, 222, 255])
        }
    })

@loadcell_bp.route('/loadcell-status-detailed')
def api_loadcell_status_detailed():
    """API endpoint to check detailed loadcell connection status matching BGM220 data format"""
    loadcell_connected, loadcell_connection_status = get_loadcell_status()
    
    # Get thread-safe snapshot of loadcell data
    loadcell_snapshot = globals.get_loadcell_quantity_snapshot()
    
    # Check if we're receiving real data using utility function
    has_real_data_val = has_real_data()
    
    # Check if we have any data (even error codes) using utility function
    has_any_data_val = has_any_data()
    
    # Check if we have recent data reception using utility function
    has_recent_reception = has_recent_data_reception()
    
    # Debug info
    current_time = time.time()
    
    return jsonify({
        'current_data': loadcell_snapshot,
        'data_summary': {
            'total_slots': len(loadcell_snapshot),
            'non_zero_slots': sum(1 for val in loadcell_snapshot if val != 0),
            'error_slots': sum(1 for val in loadcell_snapshot if val in [200, 222, 255]),
            'valid_data_slots': sum(1 for val in loadcell_snapshot if val > 0 and val not in [200, 222, 255])
        },
        'has_any_data': has_any_data_val,
        'has_real_data': has_real_data_val,
        'has_recent_reception': has_recent_reception,
        'loadcell_connected': loadcell_connected,
        'loadcell_connection_status': loadcell_connection_status,
        'timestamp': current_time
    })

@loadcell_bp.route('/manual-quantity', methods=['POST'])
def api_manual_quantity():
    """Update product quantity manually when loadcell fails"""
    try:
        data = request.get_json()
        position = data.get('position')
        quantity = data.get('quantity')
        
        # Validate input
        if position is None or quantity is None:
            return jsonify({'success': False, 'message': 'Missing position or quantity'}), 400
        
        if not isinstance(position, int) or position < 0 or position >= 15:
            return jsonify({'success': False, 'message': 'Position must be 0-14'}), 400
            
        if not isinstance(quantity, int) or quantity < 0:
            return jsonify({'success': False, 'message': 'Quantity must be >= 0'}), 400
        
        # Only allow manual update for loadcell error (255)
        if globals.loadcell_quantity[position] != 255:
            return jsonify({'success': False, 'message': 'Manual update only allowed for loadcell error (255)'}), 400
        
        # Update cart
        cart = get_cart()
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
        
        # Update and emit
        current_app.config['cart'] = cart
        socketio = current_app.extensions.get('socketio')
        if socketio:
            from app.utils.websocket_utils import emit_loadcell_update
            emit_loadcell_update(socketio, globals.loadcell_quantity, cart)
        
        return jsonify({
            'success': True,
            'message': f'Updated {product.get("product_name", "product")} to {quantity}',
            'position': position,
            'quantity': quantity
        })
        
    except Exception as e:
        print(f'Manual quantity error: {e}')
        return jsonify({'success': False, 'message': 'Update failed'}), 500
