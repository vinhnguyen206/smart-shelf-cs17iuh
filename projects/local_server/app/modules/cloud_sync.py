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
import requests
import json
import os
import threading
import time
import dotenv
from dotenv import load_dotenv
from app.modules import globals

# .env is static for the lifetime of the process — parse it once at import
# instead of re-reading the file inside every cloud call.
load_dotenv()

def load_products_from_cloud():
    try:
        url = os.getenv("GET_PRODUCTS_API_KEY")
        if not url:
            print("Warning: GET_PRODUCTS_API_KEY not configured")
            return
        
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()["products"]

            prefix = "http://ducdatphat.id.vn:3000"
            for product in data:
                img_url = product.get("img_url", "")
                if img_url and not img_url.startswith("http"):
                    product["img_url"] = str(prefix + img_url)

            json_path = os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'products.json')
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print("Data written to products.json")
            globals.set_products_data(data)
            globals.set_products_weight(globals.load_weight_of_one(data))
            globals.set_products_price(globals.load_products_price(data))
            globals.set_products_name(globals.load_products_name(data))
            products_name_decimal, products_name_char_count = globals.load_products_name_decimal(globals.get_products_name())
            globals.set_products_name_char_count(products_name_char_count)
            globals.set_products_name_decimal(products_name_decimal)
        else:
            print(f"Failed to retrieve products: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Warning: Could not connect to cloud for products: {e}")
        print("Continuing with local data...")
    except Exception as e:
        print(f"Warning: Error loading products from cloud: {e}")

def load_rfids_from_cloud():
    try:
        url = os.getenv("GET_RFIDS_API_KEY")
        if not url:
            print("Warning: GET_RFIDS_API_KEY not configured")
            return
        
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            rfids = [user["rfid"] for user in response.json()["users"]]
            json_path = os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'rfids.json')
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(rfids, f, ensure_ascii=False, indent=4)
            print("Data written to rfids.json")
            globals.set_rfids(rfids)
        else:
            print(f"Failed to retrieve rfids: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Warning: Could not connect to cloud for RFIDs: {e}")
        print("Continuing with local data...")
    except Exception as e:
        print(f"Warning: Error loading RFIDs from cloud: {e}")

def load_combo_from_cloud():
    try:
        url = os.getenv("GET_COMBOS_API_KEY")
        if not url:
            print("Warning: GET_COMBOS_API_KEY not configured")
            return
        
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            api_data = response.json()["data"]
            combos = []
            for i, combo in enumerate(api_data, start=1):
                combos.append({
                    "id":combo["_id"],
                    "name": combo["name"],
                    "desc": combo.get("description", ""),
                    "img": combo.get("image", ""),
                    "price": combo.get("price", 0),
                    "oldPrice": combo.get("oldPrice", 0),
                    "validFrom": combo.get("validFrom"),
                    "validTo": combo.get("validTo"),
                    "products": [p["_id"] for p in combo.get("products", [])]
                })
            json_path = os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'combo.json')
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(combos, f, ensure_ascii=False, indent=4)
            print("Data written to combo.json")
        else:
            print(f"Failed to retrieve combos: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Warning: Could not connect to cloud for combos: {e}")
        print("Continuing with local data...")
    except Exception as e:
        print(f"Warning: Error loading combos from cloud: {e}")

def load_posters_from_cloud():
    try:
        url = os.getenv("GET_POSTERS_API_KEY")
        if not url:
            print("Warning: GET_POSTERS_API_KEY not configured")
            return
        
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            api_data = response.json()["data"]
            posters = []
            for i, poster in enumerate(api_data, start=1):
                posters.append({
                    "image_url": poster.get("image_url", "")
                })
            json_path = os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'slideshow_images.json')
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(posters, f, ensure_ascii=False, indent=4)
            print("Data written to slideshow_images.json")
        else:
            print(f"Failed to retrieve posters: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Warning: Could not connect to cloud for posters: {e}")
        print("Continuing with local data...")
    except Exception as e:
        print(f"Warning: Error loading posters from cloud: {e}")

def load_sepay_info_from_cloud():
    try:
        url = os.getenv("GET_SEPAY_INFO_API_KEY")
        if not url:
            print("Warning: GET_SEPAY_INFO_API_KEY not configured")
            return
        
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            sepay_info = response.json()
            json_path = os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'sepay_info.json')
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(sepay_info, f, ensure_ascii=False, indent=4)
            print("Data written to sepay_info.json")
            
            # Reload globals.sepay_info to use new values
            globals.reload_sepay_info()
        else:
            print(f"Failed to retrieve Sepay info: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Warning: Could not connect to cloud for Sepay info: {e}")
        print("Continuing with local data...")
    except Exception as e:
        print(f"Warning: Error loading Sepay info from cloud: {e}")

def sync_all_from_cloud(wait_timeout=8):
    """Refresh all cloud-backed data (products, rfids, combos, posters, sepay).

    The five GETs run concurrently, so the worst case is one 5s HTTP timeout
    instead of five in a row (~25s). Each loader already falls back to the
    local JSON files on failure."""
    loaders = [
        load_products_from_cloud,
        load_rfids_from_cloud,
        load_combo_from_cloud,
        load_posters_from_cloud,
        load_sepay_info_from_cloud,
    ]
    threads = [threading.Thread(target=fn, daemon=True) for fn in loaders]
    for t in threads:
        t.start()
    deadline = time.time() + wait_timeout
    for t in threads:
        t.join(max(0.0, deadline - time.time()))

def post_order_data_to_cloud(order_data):
    try:
        file_path = os.path.abspath(os.path.join(__file__, "../../..", "app/static/img/customer_frame/frame_box.jpg"))
        url = os.getenv("POST_ORDER_API_KEY")
        
        # Convert orderDetails array to JSON string for multipart form data
        order_data_copy = order_data.copy()
        if 'orderDetails' in order_data_copy:
            order_data_copy['orderDetails'] = json.dumps(order_data_copy['orderDetails'])
        
        print(f"DEBUG: Sending order_data to cloud: {order_data_copy}")
        
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "image/jpeg")}
            response = requests.post(url, files=files, data=order_data_copy, timeout=30)

            if response.ok:
                print("Order data posted successfully")
                print(response.text)
            else:
                print(f"Failed to post order data: {response.status_code}")
                print(response.text)
    except requests.exceptions.ConnectionError as e:
        print(f"Connection error while posting order data: {e}")
        raise  # Re-raise to be caught by caller
    except requests.exceptions.Timeout as e:
        print(f"Timeout while posting order data: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error while posting order data: {e}")
        raise

def post_history_added_products_to_cloud(history_added_data):
    url = os.getenv("POST_HISTORY_ADDED_PRODUCTS_API_KEY")
    # timeout is essential: without it a dead link hangs the RFID thread forever
    response = requests.post(url, json=history_added_data, timeout=10)
    if response.status_code == 201:
        print("History added data posted successfully")
    else:
        print(f"Failed to post history added data: {response.status_code}")
        print(response.text)