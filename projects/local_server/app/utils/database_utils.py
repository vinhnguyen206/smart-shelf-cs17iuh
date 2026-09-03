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
Database utility functions for handling orders and products
"""
import os
import json
import threading
from datetime import datetime

# In-memory caches keyed by file mtime. The BLE notification handler, socket
# emits and page renders all call these loaders; a stat() is enough to detect
# the rewrites done by cloud_sync, so each file is parsed at most once per
# change instead of once per call.
_cache_lock = threading.Lock()
_products_cache = {"mtime": None, "data": []}
_combos_cache = {"mtime": None, "data": []}


def save_order(order_data):
    """Save order data to orders.json"""
    json_path = os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'orders.json')
    try:
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                orders = json.load(f)
        except:
            orders = []
        orders.append(order_data)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(orders, f, ensure_ascii=False, indent=2)
    except Exception as e:
        pass


def save_order_details(order_details):
    """Save order details to order_details.json"""
    json_path = os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'order_details.json')
    try:
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                details = json.load(f)
        except:
            details = []
        details.extend(order_details)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(details, f, ensure_ascii=False, indent=2)
    except Exception as e:
        pass
def load_products_from_json():
    """Load products from products.json (cached until the file changes)"""
    json_path = os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'products.json')
    try:
        mtime = os.path.getmtime(json_path)
        with _cache_lock:
            if _products_cache["mtime"] != mtime:
                with open(json_path, 'r', encoding='utf-8') as f:
                    _products_cache["data"] = json.load(f)
                _products_cache["mtime"] = mtime
            return _products_cache["data"]
    except Exception as e:
        return []


def load_combos_from_json():
    """Load combos from combo.json (cached until the file changes) and filter out expired ones"""
    json_path = os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'combo.json')
    try:
        mtime = os.path.getmtime(json_path)
        with _cache_lock:
            if _combos_cache["mtime"] != mtime:
                with open(json_path, 'r', encoding='utf-8') as f:
                    combos = json.load(f)
                # Parse validTo (format: 2025-08-15T23:59:59Z) once per file
                # change; the expiry check itself stays per-call.
                parsed = []
                for combo in combos:
                    valid_to_naive = None
                    try:
                        valid_to_str = combo.get('validTo', '')
                        if valid_to_str:
                            valid_to_naive = datetime.fromisoformat(
                                valid_to_str.replace('Z', '+00:00')).replace(tzinfo=None)
                    except Exception:
                        # If date parsing fails, include the combo to be safe
                        valid_to_naive = None
                    parsed.append((combo, valid_to_naive))
                _combos_cache["data"] = parsed
                _combos_cache["mtime"] = mtime
            parsed = _combos_cache["data"]

        current_time = datetime.now()
        return [combo for combo, valid_to in parsed
                if valid_to is None or current_time <= valid_to]

    except Exception as e:
        return []


def load_all_combos_from_json():
    """Load all combos from combo.json (including expired ones) - for admin/debug purposes"""
    json_path = os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'combo.json')
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        return []


def get_product_price_with_discount(product_data):
    """
    Calculate product price with discount applied
    Returns (original_price, discounted_price)
    """
    original_price = product_data.get('price', 0)
    discount = product_data.get('discount', 0)
    
    if discount > 0:
        # discount is in percentage (e.g., 50 = 50%)
        discounted_price = original_price * (1 - discount / 100)
        discounted_price = round(discounted_price)  # Round to nearest integer
    else:
        discounted_price = original_price
    
    return original_price, discounted_price


def detect_and_apply_combo_pricing(cart_items):
    """
    Detect combo products in cart and apply combo pricing
    Returns updated cart with combo pricing applied
    """
    if not cart_items:
        return cart_items, []
    
    # Load active combos and products
    active_combos = load_combos_from_json()
    all_products = load_products_from_json()
    
    # Create product lookup by product_id
    product_lookup = {p['product_id']: p for p in all_products}
    
    # Track which products are in cart (by product_id)
    cart_product_ids = set()
    cart_by_product_id = {}
    
    for item in cart_items:
        # Assuming cart items have 'product_id' field
        product_id = item.get('product_id') or item.get('id')  # fallback to 'id' if needed
        if product_id:
            cart_product_ids.add(str(product_id))
            cart_by_product_id[str(product_id)] = item
    
    applied_combos = []
    updated_cart = cart_items.copy()
    
    # Check each combo to see if all products are in cart
    for combo in active_combos:
        combo_type = combo.get('type', 'regular')
        combo_products = combo.get('products', [])
        combo_products_set = set(str(pid) for pid in combo_products)
        
        # Handle different combo types
        if combo_type == 'buy_x_get_y':
            # Handle buy X get Y free promotion
            promotion = combo.get('promotion', {})
            buy_quantity = promotion.get('buy_quantity', 2)
            get_quantity = promotion.get('get_quantity', 1)
            promo_product_id = str(promotion.get('product_id', ''))
            
            # Check if the promotion product is in cart
            if promo_product_id in cart_by_product_id:
                cart_item = cart_by_product_id[promo_product_id]
                current_qty = cart_item.get('qty', cart_item.get('quantity', 0))
                
                # Calculate how many free items customer gets
                eligible_sets = current_qty // buy_quantity
                free_items = eligible_sets * get_quantity
                
                if eligible_sets > 0:
                    # Get prices - cart item already has discount applied
                    # But original_price should be from product database (before any discount)
                    product_data = product_lookup.get(promo_product_id, {})
                    true_original_price, discounted_price_per_item = get_product_price_with_discount(product_data)
                    
                    # Use cart item price if available (it should already have discount applied)
                    # Otherwise use calculated discounted price
                    current_price_per_item = cart_item.get('price', discounted_price_per_item)
                    
                    total_items = current_qty + free_items
                    # Total if customer paid for all items (including free ones) at current price
                    total_original_price = total_items * current_price_per_item
                    # Actual price customer pays (only for bought items)
                    actual_price = current_qty * current_price_per_item
                    # Savings from free items
                    total_savings = free_items * current_price_per_item
                    
                    combo_info = {
                        'combo_id': combo['id'],
                        'combo_name': combo['name'],
                        'combo_type': 'buy_x_get_y',
                        'buy_quantity': buy_quantity,
                        'get_quantity': get_quantity,
                        'eligible_sets': eligible_sets,
                        'free_items': free_items,
                        'total_items': total_items,
                        'original_total': total_original_price,
                        'discounted_total': actual_price,
                        'savings': total_savings,
                        'product_ids': [promo_product_id]
                    }
                    applied_combos.append(combo_info)
                    
                    # Update cart item with promotion details
                    for j, item in enumerate(updated_cart):
                        if (item.get('product_id') == promo_product_id or 
                            str(item.get('id')) == str(promo_product_id)):
                            updated_cart[j] = item.copy()
                            # Set original_price to TRUE original (from database before any discount)
                            updated_cart[j]['original_price'] = true_original_price
                            # Store the price AFTER individual discount but BEFORE combo
                            updated_cart[j]['discounted_price'] = current_price_per_item
                            updated_cart[j]['original_qty'] = current_qty
                            updated_cart[j]['free_qty'] = free_items
                            updated_cart[j]['total_qty'] = total_items
                            updated_cart[j]['qty'] = total_items  # Update displayed quantity
                            updated_cart[j]['quantity'] = total_items
                            # Effective price per item (including free items)
                            updated_cart[j]['effective_price'] = actual_price / total_items if total_items > 0 else 0
                            updated_cart[j]['price'] = actual_price / total_items if total_items > 0 else 0
                            updated_cart[j]['in_combo'] = combo_info
                            updated_cart[j]['promotion_type'] = 'buy_x_get_y'
                            updated_cart[j]['savings'] = total_savings
                            break
        
        elif combo_products_set.issubset(cart_product_ids):
            # Regular combo pricing (existing logic)
            # Calculate original price vs combo price - use cart prices (with individual discount already applied)
            original_total = 0
            for product_id in combo_products:
                if str(product_id) in cart_by_product_id:
                    # Use price from cart (already includes individual discount)
                    cart_price = cart_by_product_id[str(product_id)].get('price', 0)
                    original_total += cart_price
                elif str(product_id) in product_lookup:
                    # Fallback: calculate price with discount from product database
                    product_data = product_lookup[str(product_id)]
                    _, discounted_price = get_product_price_with_discount(product_data)
                    original_total += discounted_price
            
            combo_price = combo['price']
            savings = original_total - combo_price
            
            # Apply combo pricing to cart items
            combo_info = {
                'combo_id': combo['id'],
                'combo_name': combo['name'],
                'combo_type': 'regular',
                'combo_price': combo_price,
                'original_price': original_total,
                'savings': savings,
                'product_ids': combo_products
            }
            applied_combos.append(combo_info)
            
            # Update cart items with combo pricing
            # Distribute combo price among products proportionally
            total_distributed = 0
            combo_items = []
            
            for i, product_id in enumerate(combo_products):
                if str(product_id) in cart_by_product_id:
                    cart_item = cart_by_product_id[str(product_id)]
                    product_data = product_lookup.get(str(product_id), {})
                    
                    # Get true original price (before any discount) and discounted price
                    true_original_price, discounted_price = get_product_price_with_discount(product_data)
                    
                    # Use cart price if available (should already have individual discount)
                    # This is the price AFTER individual discount but BEFORE combo
                    current_item_price = cart_item.get('price', discounted_price)
                    
                    # Calculate proportional combo price for this item
                    if i == len(combo_products) - 1:
                        # Last item gets remaining amount to avoid rounding errors
                        combo_item_price = combo_price - total_distributed
                    else:
                        proportion = current_item_price / original_total if original_total > 0 else 0
                        combo_item_price = round(combo_price * proportion)
                        total_distributed += combo_item_price
                    
                    combo_items.append({
                        'product_id': product_id,
                        'original_price': current_item_price,  # Price after individual discount
                        'combo_price': combo_item_price,
                        'savings': current_item_price - combo_item_price
                    })
                    
                    # Update the cart item
                    for j, item in enumerate(updated_cart):
                        if (item.get('product_id') == product_id or 
                            str(item.get('id')) == str(product_id)):
                            updated_cart[j] = item.copy()
                            # Set TRUE original price (from database, before any discount)
                            updated_cart[j]['original_price'] = true_original_price
                            # Store price after individual discount but before combo
                            updated_cart[j]['discounted_price'] = current_item_price
                            updated_cart[j]['combo_price'] = combo_item_price
                            updated_cart[j]['price'] = combo_item_price  # Final price (combo price)
                            updated_cart[j]['in_combo'] = combo_info
                            updated_cart[j]['savings'] = current_item_price - combo_item_price
                            break
            
            # Update combo_info with exact item breakdown
            combo_info['items'] = combo_items
            combo_info['total_distributed'] = sum(item['combo_price'] for item in combo_items)
    
    return updated_cart, applied_combos


def calculate_cart_total_with_combos(cart_items):
    """
    Calculate cart total with combo pricing applied
    Returns total amount and breakdown
    """
    updated_cart, applied_combos = detect_and_apply_combo_pricing(cart_items)
    
    total = 0
    total_savings = 0
    breakdown = {
        'items': [],
        'combos': applied_combos,
        'subtotal': 0,
        'combo_savings': 0,
        'final_total': 0
    }
    
    for item in updated_cart:
        quantity = item.get('qty', item.get('quantity', 1))
        item_price = item.get('price', 0)
        
        # Handle buy X get Y free promotions
        if item.get('promotion_type') == 'buy_x_get_y':
            # For buy X get Y, the item_price is already the effective price
            # and quantity includes free items
            original_qty = item.get('original_qty', quantity)
            free_qty = item.get('free_qty', 0)
            original_price = item.get('original_price', item_price)
            
            # Total cost is only for the bought items
            item_total = original_qty * original_price
            # But we show the effective price per item (including free items)
            savings = item.get('savings', 0)
            
            breakdown['items'].append({
                'name': item.get('product_name', 'Unknown'),
                'original_price': original_price,
                'effective_price': item_price,
                'bought_quantity': original_qty,
                'free_quantity': free_qty,
                'total_quantity': quantity,
                'total': item_total,
                'promotion_type': 'buy_x_get_y',
                'in_combo': item.get('in_combo', {}).get('combo_name') if 'in_combo' in item else None,
                'savings': savings
            })
            
            total += item_total
            total_savings += savings
        else:
            # Regular item or regular combo
            item_total = item_price * quantity
            
            # Calculate savings for this item
            item_savings = 0
            if 'savings' in item:
                # Item is in combo - use combo savings
                item_savings = item['savings'] * quantity
            elif item.get('original_price') and item.get('original_price') > item_price:
                # Item has individual discount (not in combo)
                item_savings = (item['original_price'] - item_price) * quantity
            
            total_savings += item_savings
            
            breakdown['items'].append({
                'name': item.get('product_name', 'Unknown'),
                'price': item_price,
                'quantity': quantity,
                'total': item_total,
                'original_price': item.get('original_price'),
                'in_combo': item.get('in_combo', {}).get('combo_name') if 'in_combo' in item else None,
                'savings': item_savings
            })
            
            total += item_total
    
    breakdown['subtotal'] = total + total_savings  # Original total
    breakdown['combo_savings'] = total_savings
    breakdown['final_total'] = total
    
    return total, breakdown
