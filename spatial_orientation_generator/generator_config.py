
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
TASKS_DIR = BASE_DIR / "VLN_BENCHMARK" / "tasks"
GEOFENCE_CONFIG_PATH = BASE_DIR / "VLN_BENCHMARK" / "config" / "geofence_config.json"

# Constraints
SEARCH_RADIUS = 30.0  # meters - max distance from pano to POI for visibility
MAX_PATH_STEPS = 3    # max steps between POI_A and POI_B panoramas
MIN_POI_COUNT = 2     # minimum number of POIs required

# POI Categories with high recognition
HIGH_VISIBILITY_TYPES = [
    "restaurant",
    "cafe",
    "bank",
    "gas_station",
    "pharmacy",
    "convenience_store",
    "fast_food_restaurant"
]

# Filtering: Only allow these specific brands for food-related categories
RESTAURANT_BRANDS = [
    "McDonald's",
    "KFC",
    "Starbucks",
    "Subway",
    "Pizza Hut",
    "Burger King"
]

# Keywords to identify food/restaurant related types (to enforce brand filtering)
FOOD_TYPE_KEYWORDS = [
    "restaurant", "cafe", "bakery", "food", "cream", "donut", 
    "coffee", "tea", "bistro", "sandwich", "bar", "pub", "diner",
    "meal", "breakfast", "lunch", "dinner"
]
