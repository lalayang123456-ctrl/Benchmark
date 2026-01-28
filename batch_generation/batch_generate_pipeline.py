"""
Batch Generation Pipeline V3

Orchestrates the generation of VLN tasks across multiple cities.
1. Selects City (from 150 list).
2. Finds Primary POI & Generates Whitelist.
3. Finds Secondary POIs in Whitelist.
4. Downloads ALL Whitelist Panoramas (Preload).
5. Generates Temporary Tasks.
6. Verifies Tasks using Agent (Concurrent).
7. Saves Qualified Tasks with Global ID.

Target: 1500 Qualified Tasks.
"""

import sys
import os
import json
import time
import random
import logging
import asyncio
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from filelock import FileLock

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_generator.task_assembler import TaskAssembler
from visual_data_generator.run_agent_visual import run_agent_on_task
from engine.image_stitcher import image_stitcher

# --- Configuration ---
TARGET_TASKS = 1200
MAX_VERIFICATION_WORKERS = 5
MAX_DOWNLOAD_WORKERS = 10
STATE_FILE = Path(__file__).parent.parent / "data" / "generation_state.json"
CITIES_FILE = Path(__file__).parent.parent / "data" / "cities.json"
TASKS_DIR = Path(__file__).parent.parent / "tasks"

# POI Configuration
# POI Configuration
PRIMARY_TYPES = ["restaurant", "landmark", "transit", "service", "gas_station", "supermarket"]
FAST_FOOD_CHAINS = ["McDonald's", "KFC", "Starbucks", "Subway", "Pizza Hut", "Burger King"]
SECONDARY_KEYWORDS = [
    "McDonald's", "Starbucks", "KFC", "Subway", "Burger King", 
    "Bus Stop", "Subway Station", "Park", "Pharmacy", "Bank", 
    "Supermarket", "Convenience Store", "Gas Station", "Cafe", "Post Office"
]

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("batch_generation.log", encoding='utf-8')
    ]
)
logger = logging.getLogger("BatchGen")

class BatchGenerator:
    def __init__(self):
        self.cities = self._load_cities()
        self.state = self._load_state()
        self.assembler = TaskAssembler()
        self.lock = FileLock("state_lock.lock")
        
        # Validation queue
        self.verification_executor = ThreadPoolExecutor(max_workers=MAX_VERIFICATION_WORKERS)
        self.download_executor = ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS)

    def _load_cities(self):
        if not CITIES_FILE.exists():
            logger.error(f"Cities file not found: {CITIES_FILE}")
            sys.exit(1)
        with open(CITIES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _load_state(self):
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    # Clean up pending files from previous run if any
                    self._cleanup_pending(state.get("pending_temp_files", []))
                    state["pending_temp_files"] = [] 
                    return state
            except Exception as e:
                logger.warning(f"Failed to load state: {e}. Creating new state.")
        
        return {
            "total_qualified_tasks": 0,
            "next_global_id": 1,
            "visited_cities": [],
            "pending_temp_files": []
        }

    def _save_state(self):
        with self.lock:
            # Ensure directory exists
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2)

    def _cleanup_pending(self, file_paths):
        """Delete temporary files from previous crashed runs."""
        for path_str in file_paths:
            path = Path(path_str)
            if path.exists():
                try:
                    path.unlink()
                    logger.info(f"Cleaned up stale temp file: {path}")
                    # Try to clean visual counterpart too
                    path_str = str(path)
                    if "nav_" in path_str:
                        vis_expected = path_str.replace("nav_", "visual_")
                    elif "visual_" in path_str:
                         vis_expected = path_str.replace("visual_", "nav_")
                    else:
                        vis_expected = None
                    
                    if vis_expected and os.path.exists(vis_expected):
                        os.remove(vis_expected)

                except Exception as e:
                    logger.warning(f"Failed to delete {path}: {e}")

    def download_panoramas_concurrently(self, whitelist):
        """Download all panoramas in the whitelist using thread pool."""
        logger.info(f"[*] Downloading {len(whitelist)} panoramas...")
        
        futures = []
        for pano_id in whitelist:
            # check if exists first to avoid submitting unnecessary tasks? 
            # image_stitcher download_and_stitch handles caching, but we can call it directly
            futures.append(
                self.download_executor.submit(image_stitcher.download_and_stitch, pano_id, 3)
            )
        
        completed = 0
        total = len(whitelist)
        
        for future in futures:
            res = future.result()
            if res:
                completed += 1
            # Simple progress logging
            if completed % 10 == 0:
                print(f"    - Downloaded {completed}/{total}", end='\r')
        
        print(f"\n    [OK] Downloaded {completed}/{total} panoramas.")

    async def run_pipeline_async(self):
        logger.info("Starting Batch Generation Pipeline V3")
        logger.info(f"Target: {TARGET_TASKS} qualified tasks")
        
        # Determine parallel workers for metadata fetching
        # We can pass this to WhitelistGenerator if needed, but it uses default 4 or from metadata_fetcher.
        # Let's ensure session is started globally.
        logger.info("[Global] Initializing Global Chrome Session...")
        await self.assembler.whitelist_generator.enter_session()
        
        try:
            while self.state["total_qualified_tasks"] < TARGET_TASKS:
                available_cities = [c for c in self.cities if c["name"] not in self.state["visited_cities"]]
                
                if not available_cities:
                    logger.warning("[!] All cities visited! Cleaning visited list to restart...")
                     # Logic to restart or stop? Let's stop to be safe, or clear visited. 
                     # For now, just stop.
                    logger.error("[!] Stopping: No more cities.")
                    break

                city = random.choice(available_cities)
                city_name = city["name"]
                logger.info(f"\n[{self.state['total_qualified_tasks']}/{TARGET_TASKS}] Processing City: {city_name}")

                tasks_generated_for_city = False
                
                # Check lat/lng
                if not city.get("lat") or not city.get("lng"):
                    logger.warning(f"Skipping {city_name}: Invalid coordinates")
                    self.state["visited_cities"].append(city_name)
                    self._save_state()
                    continue

                # Probabilistic Primary Target Selection
                # 40% chance: Select specific fast food chain as Primary
                # 60% chance: Select from generic PRIMARY_TYPES
                
                candidates = [] # List of (poi_type, poi_keyword)
                
                if random.random() < 0.4:
                    # 40% -> Fast Food Chain
                    # Iterate through all fast food chains in random order
                    chain_candidates = FAST_FOOD_CHAINS.copy()
                    random.shuffle(chain_candidates)
                    
                    # For chains, we pass empty type and specific keyword
                    # But to ensure assembler works, often "restaurant" + keyword is safer, 
                    # or just empty type + keyword if poi_searcher handles it.
                    # Based on poi_searcher, if type is empty, it uses text search with keyword.
                    for chain in chain_candidates:
                        candidates.append(("", chain))
                    
                    logger.info(f"  [Mode] 40% Fast Food Chain Focus: {chain_candidates}")
                else:
                    # 60% -> Generic Type
                    type_candidates = PRIMARY_TYPES.copy()
                    random.shuffle(type_candidates)
                    for t in type_candidates:
                        candidates.append((t, None))
                        
                    logger.info(f"  [Mode] 60% Generic Type Focus: {type_candidates}")

                for poi_type, poi_keyword in candidates:
                    disp_name = poi_keyword if poi_keyword else poi_type
                    logger.info(f"  > Trying Primary POI: {disp_name}")
                    
                    try:
                        # Secondary Keywords: increase to 10
                        current_secondaries = random.sample(SECONDARY_KEYWORDS, min(len(SECONDARY_KEYWORDS), 10))
                        
                        logger.info(f"    (Secondaries: {current_secondaries})")

                        # Pass both poi_type and poi_keyword to assembler
                        # assembler.generate_batch_tasks_v2(..., poi_type=poi_type, poi_keyword=poi_keyword)
                        
                        tasks, whitelist = await self.assembler.generate_batch_tasks_v2(
                            center_lat=city["lat"],
                            center_lng=city["lng"],
                            poi_type=poi_type,
                            poi_keyword=poi_keyword,
                            spawn_count=3, # 3 spawns per target
                            secondary_keywords=current_secondaries,
                            generate_exploration=False # Focus on Navigation for now
                        )

                        if tasks and whitelist:
                            logger.info(f"    [OK] Generated {len(tasks)} raw tasks.")
                            
                            # 1. Download Panoramas (DISABLED TEMPORARILY)
                            # self.download_panoramas_concurrently(whitelist)
                            
                            # 2. Direct Save (Nav-Only Mode)
                            timestamp_str = datetime.now().strftime("%H%M")
                            date_str = datetime.now().strftime("%Y%m%d")
                            
                            saved_count = 0
                            
                            for i, task in enumerate(tasks):
                                with self.lock:
                                     global_id = self.state["next_global_id"]
                                     self.state["next_global_id"] += 1
                                     self.state["total_qualified_tasks"] += 1
                                     self._save_state()

                                # Format: nav_{GlobalID}_{POI}_{Date}_{Time}_{Idx}.json
                                # User example: nav_0001_mcdonalds_20260123_1530_1.json
                                
                                poi_clean = task.get('target_poi_name', 'target').strip().replace(' ', '_').lower()
                                spawn_idx = i + 1 
                                
                                id_str = f"{global_id:04d}"
                                
                                final_filename = f"nav_{id_str}_{poi_clean}_{date_str}_{timestamp_str}_{spawn_idx}.json"
                                final_id = final_filename.replace('.json', '')
                                
                                # Update internal ID
                                task['task_id'] = final_id
                                # Ensure agent verification is PENDING (or SKIP since we aren't running it)
                                task["agent_verification"] = "SKIPPED" 
                                
                                # Save
                                final_path = TASKS_DIR / final_filename
                                with open(final_path, 'w', encoding='utf-8') as f:
                                    json.dump(task, f, indent=2, ensure_ascii=False)
                                    
                                logger.info(f"    [Saved] {final_filename}")
                                saved_count += 1

                            if saved_count > 0:
                                tasks_generated_for_city = True
                                break # Done with this city
                    
                    except Exception as e:
                        logger.error(f"    [!] Error processing {poi_type}: {e}")
                        import traceback
                        traceback.print_exc()

                # Mark city as visited
                with self.lock:
                    self.state["visited_cities"].append(city_name)
                    self._save_state()
                
                if not tasks_generated_for_city:
                    logger.warning(f"  [!] Failed to generate any tasks for {city_name} after trying all types.")

        except KeyboardInterrupt:
            logger.info("\n[!] Loop interrupted by user. Exiting...")
        except Exception as e:
            logger.error(f"[!] Critical Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
             logger.info("[Global] Cleaning up Global Chrome Session...")
             await self.assembler.whitelist_generator.exit_session()
             self.verification_executor.shutdown(wait=False)
             self.download_executor.shutdown(wait=False)

    def run_pipeline(self):
        asyncio.run(self.run_pipeline_async())

    def _promote_task(self, temp_path: Path):
        """Rename temp task to final ID, update internal IDs, and update counter."""
        with self.lock:
            global_id = self.state["next_global_id"]
            self.state["next_global_id"] += 1
            self.state["total_qualified_tasks"] += 1
            self._save_state()
        
        # 1. Load Nav Task & Update Internal ID
        try:
            with open(temp_path, 'r', encoding='utf-8') as f:
                nav_data = json.load(f)
            
            target = nav_data.get('target_poi_name', 'target').strip().replace(' ', '_')
            date_str = datetime.now().strftime("%Y%m%d")
            
            # Generate Final ID: e.g. nav_0001_Tokyo_Tower_20231027
            id_str = f"{global_id:04d}"
            final_nav_id = f"nav_{id_str}_{target}_{date_str}"
            
            # Update internal ID
            nav_data['task_id'] = final_nav_id
            
            # 2. Process Visual Task (if exists)
            # Logic: run_agent_visual.py does: new_name = original_name.replace("nav_", "visual_nav_", 1)
            # e.g. temp_nav_123 -> temp_visual_nav_123
            temp_vis_stem = temp_path.stem.replace("nav_", "visual_nav_", 1)
            temp_vis_path = temp_path.parent / f"{temp_vis_stem}.json"
            
            final_vis_id = f"visual_{id_str}_{target}_{date_str}"
            
            if temp_vis_path.exists():
                with open(temp_vis_path, 'r', encoding='utf-8') as f:
                    vis_data = json.load(f)
                
                # Update Visual Task Internal IDs
                vis_data['task_id'] = final_vis_id
                vis_data['nav_task_id'] = final_nav_id
                
                # Save Final Visual Task
                final_vis_name = f"{final_vis_id}.json"
                final_vis_path = TASKS_DIR / final_vis_name
                with open(final_vis_path, 'w', encoding='utf-8') as f:
                    json.dump(vis_data, f, indent=2, ensure_ascii=False)
                
                logger.info(f"    [Promoted] Visual: {final_vis_name}")
                
                # Delete Temp Visual Task
                try:
                    temp_vis_path.unlink()
                except Exception as e:
                    logger.warning(f"    [!] Could not delete temp visual file {temp_vis_path}: {e}")
            else:
                logger.warning(f"    [!] Expected visual task file not found: {temp_vis_path}")

            # 3. Save Final Nav Task
            final_nav_name = f"{final_nav_id}.json"
            final_nav_path = TASKS_DIR / final_nav_name
            with open(final_nav_path, 'w', encoding='utf-8') as f:
                json.dump(nav_data, f, indent=2, ensure_ascii=False)
                
            logger.info(f"    [Promoted] Nav: {final_nav_name}")
            
            # 4. Delete Temp Nav Task
            try:
                temp_path.unlink()
            except Exception as e:
                logger.warning(f"    [!] Could not delete temp nav file {temp_path}: {e}")
                
        except Exception as e:
            logger.error(f"    [!] Error promoting task {temp_path}: {e}")
            # If error, do not increment global ID? Too late, state already saved.
            # Just log it.
        #   new_name = original_name.replace("nav_", "visual_nav_", 1)
        #   if new_name == original_name: new_name = f"visual_{original_name}"
        #   So "temp_nav_..." -> "visual_temp_nav_..."
        
        expected_vis_temp_name = temp_path.stem.replace("nav_", "visual_nav_", 1) + ".json"
        
        # Fix logic if replace didn't work (e.g. no nav_)
        if expected_vis_temp_name == temp_path.name:
             expected_vis_temp_name = f"visual_{temp_path.name}"

        expected_vis_path = TASKS_DIR / expected_vis_temp_name
        
        if expected_vis_path.exists():
            expected_vis_path.rename(final_vis_path)
            # Update the ID inside the JSON? Ideally yes but maybe not strictly required.
            # But we should update the "task_id" field if it exists.
            self._update_task_id(final_nav_path, id_str)
            self._update_task_id(final_vis_path, id_str)
            
            logger.info(f"    [+] Promoted to ID {id_str}: {final_nav_name}")
        else:
            logger.warning(f"    [!] visual task not found for {temp_path.name} (Expected: {expected_vis_temp_name})")

    def _update_task_id(self, path: Path, new_id: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data['task_id'] = new_id
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except:
            pass

    def _cleanup_task_files(self, temp_path: Path):
        """Delete temp files for failed task."""
        try:
            if temp_path.exists():
                temp_path.unlink()
            
            # Try visual
            vis_name = temp_path.stem.replace("nav_", "visual_nav_", 1) + ".json"
            vis_path = TASKS_DIR / vis_name
            if vis_path.exists():
                vis_path.unlink()
        except:
             pass

if __name__ == "__main__":
    generator = BatchGenerator()
    generator.run_pipeline()
