
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
TASKS_DIR = BASE_DIR / "VLN_BENCHMARK" / "tasks"
TASKS_HEIGHT_DIR = BASE_DIR / "VLN_BENCHMARK" / "tasks_height"
GEOFENCE_CONFIG_PATH = BASE_DIR / "VLN_BENCHMARK" / "config" / "geofence_config.json"
HEIGHT_WHITELIST_PATH = BASE_DIR / "VLN_BENCHMARK" / "config" / "height_whitelist.json"

# Constraints
MOVEMENT_RADIUS = 40.0  # meters
STRICT_MODE_YEAR_DIFF = 2

# Google Solar API Config
SOLAR_API_BASE_URL = "https://solar.googleapis.com/v1/buildingInsights:findClosest"
