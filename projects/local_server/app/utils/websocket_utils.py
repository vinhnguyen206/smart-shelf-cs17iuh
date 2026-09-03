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
WebSocket utility functions for handling real-time updates
"""
from flask_socketio import emit


def emit_loadcell_update(socketio, loadcell_data, cart, applied_combos=None):
    """Emit loadcell update event to all connected clients with combo pricing applied.

    Pass applied_combos when the cart already went through
    update_cart_with_combo_pricing — re-running the solve on a combo-priced
    cart double-applies buy-X-get-Y promotions.
    """
    try:
        from app.utils.loadcell_utils import get_error_codes_info, update_cart_with_combo_pricing
        import numpy as np

        # Convert numpy array to list for JSON serialization
        if isinstance(loadcell_data, np.ndarray):
            loadcell_data_list = loadcell_data.tolist()
        else:
            loadcell_data_list = loadcell_data if isinstance(loadcell_data, list) else list(loadcell_data)

        # Apply combo pricing to cart before emitting (unless already applied)
        if applied_combos is None:
            cart_with_combos, applied_combos = update_cart_with_combo_pricing(cart)
        else:
            cart_with_combos = cart
        
        error_codes = get_error_codes_info()
        
        event_data = {
            'loadcell_data': loadcell_data_list,
            'taken_quantity': loadcell_data_list,  # Add this for compatibility
            'cart': cart_with_combos,  # Use cart with combo pricing applied
            'error_codes': error_codes,
            'applied_combos': applied_combos  # Include combo info
        }
        
        socketio.emit('loadcell_update', event_data)
        return True
    except Exception as e:
        print(f"Error in emit_loadcell_update: {e}")
        import traceback
        traceback.print_exc()
        return False


def emit_connection_status(socketio, status, message):
    """Emit connection status change to all connected clients"""
    try:
        if status == "connected":
            socketio.emit('loadcell_connected', {
                'status': 'connected',
                'message': message or 'Loadcell connected successfully!'
            })
        elif status == "connecting":
            socketio.emit('loadcell_connecting', {
                'status': 'connecting',
                'message': message or 'Connecting to loadcell...'
            })
        elif status == "disconnected":
            socketio.emit('loadcell_disconnected', {
                'status': 'disconnected',
                'message': message or 'Loadcell disconnected'
            })
        elif status == "error":
            socketio.emit('loadcell_error', {
                'status': 'error',
                'message': message or 'Loadcell connection error'
            })
        return True
    except Exception as e:
        return False


def emit_cart_reset(socketio, message="Cart cleared"):
    """Emit cart reset event to all connected clients"""
    try:
        socketio.emit('cart_reset', {'message': message})
        return True
    except Exception as e:
        return False
