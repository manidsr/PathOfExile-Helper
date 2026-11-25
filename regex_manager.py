# regex_manager.py
import json
import os
import config

def load_regex_data():
    if os.path.exists(config.REGEX_FILE):
        try:
            with open(config.REGEX_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Error loading regex file: {e}")
    
    # Default fallback data if file doesn't exist
    default_data = [
        {"title": "Example Movement Speed", "regex": "movement speed.+3[0-9]%"}
    ]
    save_regex_data(default_data)
    return default_data

def save_regex_data(data):
    try:
        with open(config.REGEX_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[!] Error saving regex file: {e}")


def load_category_order():
    """Persisted drag-to-reorder tab order. Empty list if nothing saved yet -
    the GUI falls back to first-appearance order for anything not in here."""
    if os.path.exists(config.CATEGORY_ORDER_FILE):
        try:
            with open(config.CATEGORY_ORDER_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            print(f"[!] Error loading category order: {e}")
    return []


def save_category_order(order):
    try:
        with open(config.CATEGORY_ORDER_FILE, 'w') as f:
            json.dump(order, f, indent=4)
    except Exception as e:
        print(f"[!] Error saving category order: {e}")