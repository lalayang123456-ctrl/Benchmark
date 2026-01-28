"""
Perception Task Generator - Configuration
"""

from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
TASKS_DIR = BASE_DIR / "VLN_BENCHMARK" / "tasks_perception"
WHITELIST_PATH = BASE_DIR / "VLN_BENCHMARK" / "config" / "perception_whitelist.json"
STATE_PATH = Path(__file__).parent / "generation_state.json"
PANO_METADATA_PATH = BASE_DIR / "VLN_BENCHMARK" / "cache" / "pano_metadata.json"

# Constraints
MAX_STEPS = 20  # Maximum steps allowed per task
MAX_PANOS_PER_WHITELIST = 30  # Maximum panoramas in whitelist
