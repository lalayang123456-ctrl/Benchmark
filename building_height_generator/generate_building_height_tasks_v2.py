
import argparse
import asyncio
import logging
import sys
import os
import json
import random
import math
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Add project root
sys.path.append(str(Path(__file__).parent.parent.parent))

from VLN_BENCHMARK.building_height_generator.generator import BuildingHeightTaskGenerator, BuildingWhitelistGenerator
from VLN_BENCHMARK.building_height_generator.config import TASKS_HEIGHT_DIR, HEIGHT_WHITELIST_PATH, MOVEMENT_RADIUS
from VLN_BENCHMARK.cache.metadata_cache import metadata_cache as sqlite_cache

# Load .env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
STATE_FILE = Path(__file__).parent / "generation_state.json"
MIN_YEAR_STRICT = 2021 # > 2020 means 2021 onwards

# Robust City List: Major cities with high likelihood of Solar/3D Data
WORLD_CITIES = [
    # North America
    {"name": "New York, USA", "lat": 40.7128, "lng": -74.0060},
    {"name": "Los Angeles, USA", "lat": 34.0522, "lng": -118.2437},
    {"name": "Chicago, USA", "lat": 41.8781, "lng": -87.6298},
    {"name": "San Francisco, USA", "lat": 37.7749, "lng": -122.4194},
    {"name": "Miami, USA", "lat": 25.7617, "lng": -80.1918},
    {"name": "Boston, USA", "lat": 42.3601, "lng": -71.0589},
    {"name": "Seattle, USA", "lat": 47.6062, "lng": -122.3321},
    {"name": "Toronto, Canada", "lat": 43.6532, "lng": -79.3832},
    {"name": "Montreal, Canada", "lat": 45.5017, "lng": -73.5673},
    {"name": "Vancouver, Canada", "lat": 49.2827, "lng": -123.1207},
    
    # Europe
    {"name": "London, UK", "lat": 51.5074, "lng": -0.1278},
    {"name": "Manchester, UK", "lat": 53.4808, "lng": -2.2426},
    {"name": "Paris, France", "lat": 48.8566, "lng": 2.3522},
    {"name": "Berlin, Germany", "lat": 52.5200, "lng": 13.4050},
    {"name": "Munich, Germany", "lat": 48.1351, "lng": 11.5820},
    {"name": "Madrid, Spain", "lat": 40.4168, "lng": -3.7038},
    {"name": "Barcelona, Spain", "lat": 41.3851, "lng": 2.1734},
    {"name": "Rome, Italy", "lat": 41.9028, "lng": 12.4964},
    {"name": "Milan, Italy", "lat": 45.4642, "lng": 9.1900},
    {"name": "Amsterdam, Netherlands", "lat": 52.3676, "lng": 4.9041},
    {"name": "Brussels, Belgium", "lat": 50.8503, "lng": 4.3517},
    {"name": "Vienna, Austria", "lat": 48.2082, "lng": 16.3738},
    {"name": "Zurich, Switzerland", "lat": 47.3769, "lng": 8.5417},
    
    # Asia/Pacific
    {"name": "Tokyo, Japan", "lat": 35.6762, "lng": 139.6503},
    {"name": "Osaka, Japan", "lat": 34.6937, "lng": 135.5023},
    {"name": "Sydney, Australia", "lat": -33.8688, "lng": 151.2093},
    {"name": "Melbourne, Australia", "lat": -37.8136, "lng": 144.9631},
    {"name": "Singapore", "lat": 1.3521, "lng": 103.8198},
    
    # South America (Solar coverage might be spotty but worth trying in capitals)
    # Sticking to high confidence ones first as requested
]

def load_state():
    default_state = {"last_id": 0, "visited_cities": []}
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                # Merge with defaults to ensure keys exist
                for k, v in default_state.items():
                    if k not in state:
                        state[k] = v
                return state
        except:
            return default_state
    return default_state

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

class BuildingHeightTaskGeneratorV2(BuildingHeightTaskGenerator):
    def __init__(self, api_key: str = None):
        super().__init__(api_key)
        # Ensure new output dir exists
        TASKS_HEIGHT_DIR.mkdir(parents=True, exist_ok=True)
        HEIGHT_WHITELIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.cache_dir = Path(__file__).parent.parent / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
    async def _fetch_pano_metadata(self, pano_id: str):
        """Helper to get full metadata for a pano ID to check date."""
        # This duplicates some logic but is necessary since _find_nearest_pano returns only ID
        # or we could use the metadata fetcher from whitelist generator if exposed.
        # Accessing the internal fetcher seems cleanest if we initialized it.
        return await self.whitelist_gen._get_metadata_with_retry(pano_id)

    async def _find_nearest_pano_with_date_check(self, lat, lng):
        """Finds nearest pano and checks date > 2020."""
        # 1. Get Nearest Pano ID
        pano_id = await self._find_nearest_pano(lat, lng, radius=15)
        if not pano_id:
            return None, "no_coverage"
            
        # 2. Check Date
        meta = await self._fetch_pano_metadata(pano_id)
        if not meta or 'date' not in meta:
            return None, "no_metadata"
            
        year = int(meta['date'].split('-')[0])
        if year < MIN_YEAR_STRICT:
            return None, f"old_pano_{year}"
            
        return pano_id, "ok"

    def _save_task_v2(self, task, filename):
        path = TASKS_HEIGHT_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(task, f, indent=2)

    def _save_whitelist_v2(self, name, whitelist):
        # Load existing config or create new
        if HEIGHT_WHITELIST_PATH.exists():
            with open(HEIGHT_WHITELIST_PATH, "r", encoding="utf-8") as f:
                try:
                    config = json.load(f)
                except:
                    config = {}
        else:
            config = {}
        
        config[name] = whitelist
        
        with open(HEIGHT_WHITELIST_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    def _save_metadata_cache(self, metadata_map: dict):
        """Save enhanced metadata to cache (both JSON file and SQLite database)."""
        cache_file = self.cache_dir / "pano_metadata.json"
        
        # Load existing cache
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                try:
                    cache = json.load(f)
                except:
                    cache = {}
        else:
            cache = {}
        
        # Update cache
        cache.update(metadata_map)
        
        # Save to JSON file
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        
        # Also save to SQLite database for Runtime
        for pano_id, meta in metadata_map.items():
            lat = meta.get("lat")
            lng = meta.get("lng")
            if lat is not None and lng is not None:
                sqlite_cache.save(
                    pano_id=pano_id,
                    lat=lat,
                    lng=lng,
                    capture_date=meta.get("date") or meta.get("capture_date"),
                    links=meta.get("links"),
                    center_heading=meta.get("center_heading"),
                    source="height_gen"
                )
        
        logger.info(f"Updated metadata cache: {len(metadata_map)} entries (JSON + SQLite)")

    async def generate_batch_v2(self, count: int, state: dict, min_height: float = 20.0):
        generated_count = 0
        attempts = 0
        
        # Determine available cities (simple random selection from global list)
        # We don't strictly remove visited cities forever, but we can iterate.
        # User said "including already used cities" -> "next time start from 0006... including already used cities".
        # Actually user said: "包括已经使用过的城市也是" -> implies persistent ID across runs, even if cities are reused?
        # Or implies tracking used cities to AVOID them?
        # "automatically find from world range... whitelist... persistent ID... including used cities"
        # Reading carefully: "including already used cities also" probably means the ID counting should continue regardless of city.
        # Re-reading: "automatically find from world range" usually implies exploration.
        # I will pick a random city from the list for each task attempt to simulate "World Range".
        
        try:
            # Optimize: Initialize session once for the batch
            await self.whitelist_gen.enter_session()
            
            while generated_count < count:
                attempts += 1
                if attempts > count * 30: # Max attempts to avoid infinite loop
                    logger.warning("Max attempts reached.")
                    break
                    
                # Pick a random city
                city = random.choice(WORLD_CITIES)
                center_lat, center_lng = city['lat'], city['lng']
                
                # Random point in city (radius 2km to find diverse buildings)
                lat, lng = self._random_point(center_lat, center_lng, 2000)
                
                # Check Building
                logger.info(f"Checking {city['name']} at {lat:.5f}, {lng:.5f}...")
                building_data = await self.gt_fetcher.fetch_building_data(lat, lng)
                
                if not building_data:
                    continue
                    
                b_lat = building_data['lat']
                b_lng = building_data['lng']
                b_height = building_data['height_meters']
                
                # Height Filter
                if min_height > 0 and b_height < min_height:
                    logger.info(f"  -> Skipped: Height {b_height:.1f}m < {min_height}m")
                    continue
                
                # Check Pano strict date
                pano_id, status = await self._find_nearest_pano_with_date_check(b_lat, b_lng)
                if not pano_id:
                    logger.info(f"  -> Skipped: {status}")
                    continue
                    
                # Generate Whitelist (45m radius, max 15)
                # Override params: radius 45m, max 15 panos
                
                logger.info(f"  -> Found Building: {building_data.get('name', 'Unknown')} ({b_height}m). Generating whitelist...")
                
                whitelist, meta_map = await self.whitelist_gen.generate_around_building(
                    start_pano=pano_id,
                    building_lat=b_lat,
                    building_lng=b_lng,
                    max_distance=80.0, # New constraint
                    max_panos=25,      # New constraint
                    keep_session=True  # Reuse session
                )
                
                if not whitelist or len(whitelist) < 2:
                    logger.info("  -> Whitelist too small.")
                    continue

                # Verify all panos in whitelist are new enough? 
                # User said "whitelist scope... must be late 2020".
                # Checking ALL panos in whitelist might be too strict if BFS just grabs them.
                # But the requirement says "for panorama... must be later than 2020".
                # I should filter the whitelist or reject if any are old?
                # Usually the constraint applies to the *task* context. Safe to check start pano (done) 
                # and maybe filter the neighbors.
                # I'll rely on the start pano check primarily, and filter whitelist if possible.
                
                valid_whitelist = []
                for pid in whitelist:
                    # We have metadata in meta_map
                    pmeta = meta_map.get(pid)
                    if pmeta and 'date' in pmeta:
                        pyear = int(pmeta['date'].split('-')[0])
                        if pyear >= MIN_YEAR_STRICT:
                            valid_whitelist.append(pid)
                
                if len(valid_whitelist) < 2:
                    logger.info("  -> Whitelist reduced too much by date filter.")
                    continue

                # Task Creation
                state["last_id"] += 1
                current_id = state["last_id"]
                current_time_str = datetime.now().strftime("%Y%m%d_%H%M%S") # "目前的时间" usually implies a timestamp
                
                # Format: height_0001_TIME
                task_id_str = f"height_{current_id:04d}_{current_time_str}"
                
                # Helper for bearing
                spawn_meta = meta_map[pano_id]
                bearing = self._calculate_bearing(spawn_meta['lat'], spawn_meta['lng'], b_lat, b_lng)
                direction_str = self._bearing_to_compass(bearing)
                
                instruction = (
                    f"Facing the building to your {direction_str} (approx. {int(bearing)}°), "
                    f"estimate the height of the main building in front of you in meters. "
                    f"Answer with one number and a short rationale."
                )
                
                task_data = {
                    "task_id": task_id_str,
                    "task_type": "building_height_estimation",
                    "description": instruction,
                    "spawn_pano_id": pano_id,
                    "spawn_heading": bearing,
                    "target_building": {
                        "lat": b_lat,
                        "lng": b_lng,
                        "height": b_height,
                        "floors": building_data.get('floors_estimated'),
                        "ground_elevation": building_data.get('ground_elevation'),
                        "roof_elevation": building_data.get('roof_elevation'),
                        "name": building_data.get('name'),
                        "date": building_data.get('date')
                    },
                    "geofence_id": f"list_{task_id_str}", # Use task ID for unique list name
                    "ground_truth": {
                        "height_meters": b_height
                    },
                    "answer": "",
                    "max_steps": None,
                    "max_time_seconds": 180,
                    "metadata": {
                        "created_at": datetime.now().isoformat(),
                        "bearing_deg": bearing,
                        "city": city["name"]
                    }
                }
                
                self._save_task_v2(task_data, f"{task_id_str}.json")
                self._save_whitelist_v2(f"list_{task_id_str}", valid_whitelist)
                
                # Save metadata to cache (Critical for Runtime)
                self._save_metadata_cache(meta_map)
                
                # Update state with visited city (set)
                if city["name"] not in state["visited_cities"]:
                    state["visited_cities"].append(city["name"])
                
                # Save state immediately
                saved_state = {
                    "last_id": state["last_id"],
                    "visited_cities": state["visited_cities"] 
                }
                save_state(saved_state)
                
                logger.info(f"  [SUCCESS] Generated {task_id_str} in {city['name']}")
                generated_count += 1
        
        finally:
            # Cleanup session after batch
            await self.whitelist_gen.exit_session()

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=50, help="Number of tasks to generate")
    parser.add_argument("--min_height", type=float, default=20.0, help="Minimum building height in meters (default: 20.0). Set to 0 to disable.")
    parser.add_argument("--api_key", type=str, help="Google API Key")
    args = parser.parse_args()
    
    state = load_state()
    logger.info(f"Loaded state: Last ID {state['last_id']}, Visited {len(state['visited_cities'])} cities")
    
    # Initialize Generator
    # We must explicitly initialize the whitelist generator's session inside the async loop
    generator = BuildingHeightTaskGeneratorV2(api_key=args.api_key)
    
    # Manually init logic that might be in generator's constructor or expected usage
    # BuildingHeightTaskGenerator doesn't enforce async init in __init__ but whitelist_gen needs it?
    # WhitelistGenerator usually handles session in its methods or we trust 'generate_around_building' does it.
    # Looking at V1 code: it calls whitelist_gen.generate_around_building
    # which does await self.metadata_fetcher.initialize() inside. So we are good.
    
    await generator.generate_batch_v2(args.count, state, min_height=args.min_height)
    
    logger.info("Done.")

if __name__ == "__main__":
    asyncio.run(main())
