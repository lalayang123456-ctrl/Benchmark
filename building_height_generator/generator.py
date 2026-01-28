import os
import json
import random
import math
import logging
import asyncio
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path

from ..data_generator.whitelist_generator import WhitelistGenerator
from ..data_generator.link_enhancer import enhance_panorama_links
from .ground_truth import GroundTruthFetcher
from .config import TASKS_DIR, GEOFENCE_CONFIG_PATH, MOVEMENT_RADIUS, STRICT_MODE_YEAR_DIFF

logger = logging.getLogger(__name__)

class BuildingWhitelistGenerator(WhitelistGenerator):
    """Extended WhitelistGenerator to support building-centric BFS."""
    
    async def generate_around_building(
        self, 
        start_pano: str, 
        building_lat: float, 
        building_lng: float, 
        max_distance: float, 
        max_panos: int,
        keep_session: bool = False
    ) -> Tuple[List[str], Dict[str, dict]]:
        """
        Generate whitelist centered on a building coordinate.
        """
        # Clear cache
        self.metadata_cache = {}
        
        self.metadata_cache = {}
        
        if not keep_session:
            await self.metadata_fetcher.initialize()
        try:
            # Ensure start pano is valid
            start_meta = await self._get_metadata_with_retry(start_pano)
            if not start_meta:
                return [], {}
            
            # BFS expansion
            whitelist_set = await self._bfs_expand_parallel(
                start_pano=start_pano,
                center_lat=building_lat,
                center_lng=building_lng,
                max_distance=max_distance,
                max_nodes=max_panos
            )
            return list(whitelist_set), self.metadata_cache.copy()
        finally:
            if not keep_session:
                await self.metadata_fetcher.cleanup()

class BuildingHeightTaskGenerator:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.gt_fetcher = GroundTruthFetcher(self.api_key)
        self.whitelist_gen = BuildingWhitelistGenerator(self.api_key, parallel_workers=8)
        
        # Ensure directories exist
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        GEOFENCE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    async def generate_batch(self, center_lat: float, center_lng: float, radius: float, count: int) -> List[str]:
        """
        Generate a batch of tasks by random sampling around center.
        
        Returns:
            List of generated task IDs.
        """
        generated_ids = []
        attempts = 0
        max_attempts = count * 10 
        
        print(f"[*] Starting generation: {count} tasks around {center_lat}, {center_lng}")
        
        while len(generated_ids) < count and attempts < max_attempts:
            attempts += 1
            
            # 1. Random Sample
            lat, lng = self._random_point(center_lat, center_lng, radius)
            
            # 2. Check for Building (Solar API)
            print(f"  Attempt {attempts}: Checking building at {lat:.5f}, {lng:.5f}...")
            building_data = await self.gt_fetcher.fetch_building_data(lat, lng)
            
            if not building_data:
                print("    -> No building/data found.")
                continue
                
            b_lat = building_data['lat']
            b_lng = building_data['lng']
            b_height = building_data['height_meters']
            print(f"    -> Found: {building_data['name']} (H={b_height}m)")
            
            # 3. Find Nearest Pano
            pano_id = await self._find_nearest_pano(b_lat, b_lng)
            if not pano_id:
                print("    -> No Street View coverage.")
                continue
            
            # 4. Generate Whitelist (40m radius from building center)
            print("    -> Generating whitelist...")
            whitelist, meta_map = await self.whitelist_gen.generate_around_building(
                start_pano=pano_id,
                building_lat=b_lat,
                building_lng=b_lng,
                max_distance=MOVEMENT_RADIUS,
                max_panos=20 # Small graph is fine for looking at one building
            )
            
            if not whitelist:
                print("    -> Whitelist generation failed (not connected?).")
                continue
            
            if len(whitelist) < 2:
                 print("    -> Whitelist too small.")
                 continue

            # 5. Filter by Year (Strict Mode)
            # Building Imagery Date vs Pano Date
            valid_panos = whitelist # Placeholder, logic below
            # TODO: Add strict year check if 'date' in meta_map
            
            # 6. Enhance Links (Virtual Links within the small graph)
            whitelist_set = set(whitelist)
            enhanced_map, added, removed = enhance_panorama_links(
                meta_map, 
                threshold_meters=18.0, 
                whitelist=whitelist_set
            )
            
            # 7. Create Task
            task_id = f"height_task_{len(generated_ids) + 1}_{int(datetime.now().timestamp())}"
            
            # Calculate Bearing for instruction
            spawn_meta = enhanced_map[pano_id]
            bearing = self._calculate_bearing(
                spawn_meta['lat'], spawn_meta['lng'],
                b_lat, b_lng
            )
            direction_str = self._bearing_to_compass(bearing)
            
            instruction = (
                f"Facing the building to your {direction_str} (approx. {int(bearing)}°), "
                f"estimate the height of the main building in front of you in meters. "
                f"Answer with one number and a short rationale."
            )
            
            task_data = {
                "task_id": task_id,
                "task_type": "building_height_estimation",
                "description": instruction,
                "spawn_pano_id": pano_id,
                "spawn_heading": bearing,  # Face towards the building
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
                "geofence_id": f"list_height_{task_id}",
                "ground_truth": {
                    "height_meters": b_height
                },
                "answer": "",  # Agent's answer will be filled here
                "max_steps": None,
                "max_time_seconds": 180,
                "metadata": {
                    "created_at": datetime.now().isoformat(),
                    "bearing_deg": bearing
                }
            }
            
            # 8. Save
            self._save_task(task_data)
            self._save_whitelist(f"list_height_{task_id}", whitelist)
            
            print(f"    [OK] Task Generated: {task_id}")
            generated_ids.append(task_id)
            
        return generated_ids

    def _random_point(self, lat, lng, radius_meters):
        """Random point within radius."""
        r = radius_meters / 111300.0
        u = random.random()
        v = random.random()
        w = r * math.sqrt(u)
        t = 2 * math.pi * v
        x = w * math.cos(t)
        y = w * math.sin(t)
        return (lat + x, lng + y / math.cos(math.radians(lat)))

    async def _find_nearest_pano(self, lat, lng, radius=50):
        # Use existing logic from POISearcher/MetadataFetcher or direct call
        # Since I can't easily import POISearcher instance without init, 
        # I'll use a direct fetch via MetadataFetcher helper or implemented here.
        # WhitelistGenerator has `fetch_basic_metadata` but that takes Pano ID.
        # I need location -> Pano ID.
        # Use simple requests.
        url = f"https://maps.googleapis.com/maps/api/streetview/metadata"
        params = {
            "location": f"{lat},{lng}",
            "key": self.api_key,
            "source": "outdoor",
            "radius": radius
        }
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "OK":
                        return data.get("pano_id")
        return None

    def _calculate_bearing(self, lat1, lng1, lat2, lng2):
        dLon = math.radians(lng2 - lng1)
        lat1 = math.radians(lat1)
        lat2 = math.radians(lat2)
        y = math.sin(dLon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
        brng = math.degrees(math.atan2(y, x))
        return (brng + 360) % 360

    def _bearing_to_compass(self, bearing):
        dirs = ["North", "North-East", "East", "South-East", "South", "South-West", "West", "North-West"]
        idx = round(bearing / 45) % 8
        return dirs[idx]

    def _save_task(self, task):
        path = TASKS_DIR / f"{task['task_id']}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(task, f, indent=2)

    def _save_whitelist(self, name, whitelist):
        # Load existing config
        if GEOFENCE_CONFIG_PATH.exists():
            with open(GEOFENCE_CONFIG_PATH, "r", encoding="utf-8") as f:
                try:
                    config = json.load(f)
                except:
                    config = {}
        else:
            config = {}
        
        config[name] = whitelist
        
        with open(GEOFENCE_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
