"""
Perception Task Generator - Main Generator

Generates spatial perception tasks (distance and angle estimation)
from POI pairs found within a specified radius.
"""

import os
import json
import math
import logging
import asyncio
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from pathlib import Path
from itertools import combinations
from dotenv import load_dotenv

# Load .env from VLN_BENCHMARK directory
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

from .config import TASKS_DIR, WHITELIST_PATH, STATE_PATH, PANO_METADATA_PATH, MAX_STEPS, MAX_PANOS_PER_WHITELIST
from .places_searcher import PlacesSearcher, POI
from data_generator.whitelist_generator import WhitelistGenerator
from cache.metadata_cache import metadata_cache as sqlite_cache

logger = logging.getLogger(__name__)


class PerceptionTaskGenerator:
    """Generate perception tasks (distance/angle estimation) from POI pairs."""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.places_searcher = PlacesSearcher(self.api_key)
        self.whitelist_gen = WhitelistGenerator(self.api_key, parallel_workers=8)
        
        # Ensure directories exist
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        WHITELIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        self.cache_dir = Path(__file__).parent.parent / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    async def generate_tasks(
        self,
        center_lat: float,
        center_lng: float,
        radius: float,
        names: List[str]
    ) -> List[str]:
        """
        Generate perception tasks from POI pairs.
        
        Args:
            center_lat: Center latitude
            center_lng: Center longitude
            radius: Search radius in meters
            names: List of place names to search for
        
        Returns:
            List of generated task IDs
        """
        logger.info(f"[*] Starting perception task generation")
        logger.info(f"    Center: ({center_lat}, {center_lng}), Radius: {radius}m")
        logger.info(f"    Places to search: {names}")
        
        # 1. Search for places
        pois = await self.places_searcher.search_multiple_names(
            center_lat, center_lng, radius, names
        )
        
        if len(pois) < 2:
            logger.error(f"[!] Need at least 2 POIs to generate tasks, found {len(pois)}")
            return []
        
        # 2. Enrich with pano IDs
        pois = await self.places_searcher.enrich_with_pano_ids(pois)
        
        if len(pois) < 2:
            logger.error(f"[!] Need at least 2 POIs with Street View coverage, found {len(pois)}")
            return []
        
        logger.info(f"[*] Valid POIs: {len(pois)}")
        for poi in pois:
            logger.info(f"    - {poi.name} @ ({poi.lat:.6f}, {poi.lng:.6f})")
        
        # 3. Generate whitelist around center
        logger.info(f"[*] Generating whitelist around center...")
        
        # Find spawn pano near center
        spawn_pano_id = await self.places_searcher.get_nearest_pano_id(center_lat, center_lng, radius=30)
        if not spawn_pano_id:
            logger.error(f"[!] No Street View coverage at center")
            return []
        
        try:
            await self.whitelist_gen.enter_session()
            
            whitelist_set, spawn_candidates, meta_map = await self.whitelist_gen.generate_from_target(
                target_pano_id=spawn_pano_id,
                min_panos=5,
                max_panos=MAX_PANOS_PER_WHITELIST,
                max_distance=radius,
                spawn_min_distance=0,
                spawn_max_distance=radius,
                keep_session=True
            )
        finally:
            await self.whitelist_gen.exit_session()
        
        if not whitelist_set:
            logger.error(f"[!] Failed to generate whitelist")
            return []
        
        logger.info(f"[*] Whitelist generated: {len(whitelist_set)} panoramas")
        
        # Get spawn location from metadata
        spawn_meta = meta_map.get(spawn_pano_id)
        if not spawn_meta:
            logger.error(f"[!] Spawn pano metadata not found")
            return []
        
        spawn_lat = spawn_meta.get("lat")
        spawn_lng = spawn_meta.get("lng")
        
        # 4. Generate pairwise tasks
        state = self._load_state()
        generated_ids = []
        
        pairs = list(combinations(pois, 2))
        logger.info(f"[*] Generating {len(pairs)} task pairs (dis + angle)...")
        
        # Create unique geofence ID for this batch
        geofence_id = f"list_perception_{int(datetime.now().timestamp())}"
        
        for poi_a, poi_b in pairs:
            state["last_id"] += 1
            current_id = state["last_id"]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Calculate ground truth
            distance = self._calculate_distance(poi_a.lat, poi_a.lng, poi_b.lat, poi_b.lng)
            bearing_a_to_b = self._calculate_bearing(poi_a.lat, poi_a.lng, poi_b.lat, poi_b.lng)
            bearing_b_to_a = self._calculate_bearing(poi_b.lat, poi_b.lng, poi_a.lat, poi_a.lng)
            
            ground_truth = {
                "distance_between_pois_m": round(distance, 1),
                "bearing_a_to_b_deg": round(bearing_a_to_b, 1),
                "bearing_b_to_a_deg": round(bearing_b_to_a, 1)
            }
            
            pois_data = [poi_a.to_dict(), poi_b.to_dict()]
            
            metadata = {
                "created_at": datetime.now().isoformat(),
                "spawn_location": {
                    "lat": spawn_lat,
                    "lng": spawn_lng
                }
            }
            
            # Calculate spawn heading (face towards POI_A)
            spawn_heading = self._calculate_bearing(spawn_lat, spawn_lng, poi_a.lat, poi_a.lng)
            
            # Distance task
            dis_task_id = f"dis_{current_id:04d}_{timestamp}"
            dis_task = {
                "task_id": dis_task_id,
                "task_type": "perception_distance",
                "description": f"Estimate the distance between {poi_a.name} and {poi_b.name} in meters.",
                "spawn_pano_id": spawn_pano_id,
                "spawn_heading": round(spawn_heading, 1),
                "pois": pois_data,
                "geofence_id": geofence_id,
                "ground_truth": ground_truth,
                "answer": "",
                "max_steps": MAX_STEPS,
                "max_time_seconds": None,
                "metadata": metadata
            }
            
            # Angle task
            angle_task_id = f"angle_{current_id:04d}_{timestamp}"
            angle_task = {
                "task_id": angle_task_id,
                "task_type": "perception_angle",
                "description": f"Estimate the relative direction (0-360 deg, clockwise from North) of {poi_b.name} from {poi_a.name}.",
                "spawn_pano_id": spawn_pano_id,
                "spawn_heading": round(bearing_a_to_b, 1),
                "pois": pois_data,
                "geofence_id": geofence_id,
                "ground_truth": ground_truth,
                "answer": "",
                "max_steps": MAX_STEPS,
                "max_time_seconds": None,
                "metadata": metadata
            }
            
            # Save tasks
            self._save_task(dis_task, f"{dis_task_id}.json")
            self._save_task(angle_task, f"{angle_task_id}.json")
            
            generated_ids.extend([dis_task_id, angle_task_id])
            logger.info(f"  [+] Generated: {dis_task_id}, {angle_task_id}")
        
        # 5. Save whitelist
        self._save_whitelist(geofence_id, list(whitelist_set))
        
        # 6. Save metadata cache (dual write: JSON + SQLite)
        self._save_metadata_cache(meta_map)
        
        # 7. Save state
        self._save_state(state)
        
        logger.info(f"[*] Generation complete: {len(generated_ids)} tasks")
        return generated_ids
    
    def _calculate_distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate distance between two points using Haversine formula (meters)."""
        R = 6371000  # Earth radius in meters
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)
        
        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lng / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c
    
    def _calculate_bearing(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate bearing from point 1 to point 2 (0-360 degrees, clockwise from North)."""
        dLon = math.radians(lng2 - lng1)
        lat1 = math.radians(lat1)
        lat2 = math.radians(lat2)
        
        y = math.sin(dLon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
        
        bearing = math.degrees(math.atan2(y, x))
        return (bearing + 360) % 360
    
    def _load_state(self) -> dict:
        """Load generation state."""
        default_state = {"last_id": 0}
        if STATE_PATH.exists():
            try:
                with open(STATE_PATH, 'r') as f:
                    state = json.load(f)
                    for k, v in default_state.items():
                        if k not in state:
                            state[k] = v
                    return state
            except:
                return default_state
        return default_state
    
    def _save_state(self, state: dict):
        """Save generation state."""
        with open(STATE_PATH, 'w') as f:
            json.dump(state, f, indent=2)
    
    def _save_task(self, task: dict, filename: str):
        """Save task to JSON file."""
        path = TASKS_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(task, f, indent=2)
    
    def _save_whitelist(self, name: str, pano_ids: List[str]):
        """Save whitelist to perception_whitelist.json (append)."""
        if WHITELIST_PATH.exists():
            with open(WHITELIST_PATH, "r", encoding="utf-8") as f:
                try:
                    config = json.load(f)
                except:
                    config = {}
        else:
            config = {}
        
        config[name] = pano_ids
        
        with open(WHITELIST_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        
        logger.info(f"[*] Saved whitelist '{name}' with {len(pano_ids)} panoramas")
    
    def _save_metadata_cache(self, metadata_map: Dict[str, dict]):
        """Save metadata to cache (both JSON file and SQLite database)."""
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
                    source="perception_gen"
                )
        
        logger.info(f"[*] Updated metadata cache: {len(metadata_map)} entries (JSON + SQLite)")
