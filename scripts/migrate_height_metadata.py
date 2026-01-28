
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import List, Set

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from VLN_BENCHMARK.cache.metadata_cache import metadata_cache
from VLN_BENCHMARK.engine.metadata_fetcher import MetadataFetcher
from VLN_BENCHMARK.building_height_generator.config import HEIGHT_WHITELIST_PATH, TASKS_HEIGHT_DIR

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def migrate_height_tasks():
    logger.info("Starting Height Task Metadata Migration...")
    
    # 1. Load Whitelist Config
    if not HEIGHT_WHITELIST_PATH.exists():
        logger.error(f"Whitelist file not found: {HEIGHT_WHITELIST_PATH}")
        return
        
    with open(HEIGHT_WHITELIST_PATH, 'r', encoding='utf-8') as f:
        whitelist_config = json.load(f)
        
    logger.info(f"Loaded whitelist config with {len(whitelist_config)} lists.")
    
    # 2. Identify Relevant Whitelists from Task Files (Optional, can just do all in config)
    # But user specifically asked for "current and generated 54 tasks".
    # Safest is to collect all Pano IDs from *all* lists in height_whitelist.json 
    # that correspond to the tasks in tasks_height dir.
    
    task_files = list(TASKS_HEIGHT_DIR.glob("height_*.json"))
    logger.info(f"Found {len(task_files)} task files in {TASKS_HEIGHT_DIR}")
    
    relevant_lists = set()
    for tf in task_files:
        with open(tf, 'r', encoding='utf-8') as f:
            task = json.load(f)
            geofence_id = task.get("geofence_id")
            if geofence_id:
                relevant_lists.add(geofence_id)
                
    logger.info(f"Identified {len(relevant_lists)} relevant whitelist IDs from tasks.")
    
    # 3. Collect Unique Pano IDs
    all_pano_ids: Set[str] = set()
    for list_id in relevant_lists:
        if list_id in whitelist_config:
            panos = whitelist_config[list_id]
            all_pano_ids.update(panos)
        else:
            logger.warning(f"Whitelist ID {list_id} found in task but not in config file.")
            
    logger.info(f"Total unique panoramas to fetch: {len(all_pano_ids)}")
    
    if not all_pano_ids:
        logger.info("No panoramas to fetch. Exiting.")
        return

    # 4. Initialize Fetcher
    fetcher = MetadataFetcher(num_workers=20) # High concurrency for speed
    await fetcher.initialize()
    
    try:
        # 5. Fetch and Save (Batch Processing)
        # metadata_cache.save() is synchronous (SQLite), fetcher is async.
        # We can fetch in batches and save.
        
        pano_list = list(all_pano_ids)
        batch_size = 50
        
        for i in range(0, len(pano_list), batch_size):
            batch = pano_list[i : i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(pano_list)//batch_size)+1} ({len(batch)} panos)...")
            
            # Create fetch tasks
            fetch_tasks = [fetcher.fetch_links(pid) for pid in batch]
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            
            success_count = 0
            for pid, res in zip(batch, results):
                if isinstance(res, Exception) or not res:
                    logger.warning(f"Failed to fetch {pid}: {res}")
                    continue
                
                # MetadataFetcher.fetch_links returns dict with 'links', 'centerHeading', 'date', 'location'
                # But fetch_links implementation returns specific structure.
                # Let's check fetcher code or just assume standard return.
                # Actually fetch_links usually returns the raw-ish JSON response or parsed dict.
                # Let's use fetch_full_metadata if available or manually fetch basic + links.
                # MetadataFetcher.fetch_links does a "social" fetch effectively.
                
                # Getting details from result assuming it mimics the API response structure wrapper
                # We need lat/lng too. fetch_links (simulated) usually has it? 
                # If fetch_links only gets links, we might miss lat/lng. 
                # Let's use fetch_basic_metadata + fetch_links logic? 
                
                # Wait, MetadataFetcher in this codebase is powerful.
                # It has `fetch_basic_metadata` (sync) and `fetch_links` (async).
                # `fetch_links` usually returns the full metadata object if successful?
                # Let's double check `usage` or implementation.
                # In `whitelist_generator.py`: 
                # basic = await asyncio.to_thread(self.metadata_fetcher.fetch_basic_metadata, pano_id)
                # links_result = await self.metadata_fetcher.fetch_links(pano_id)
                
                # So we need TWO calls per pano to get full data.
                # 1. Basic (Location, Date)
                # 2. Links (Connections)
                
                # Using a helper here to do both would be cleaner, but we can just do inline.
                
                # A. Basic Metadata
                basic = await asyncio.to_thread(fetcher.fetch_basic_metadata, pid)
                if not basic:
                    continue
                    
                # B. Links
                links_data = res # From gathered tasks
                
                # Parse links
                links = []
                if links_data and 'links' in links_data:
                    for l in links_data['links']:
                         links.append({
                             "pano_id": l.get("panoId"),
                             "heading": l.get("heading"),
                             "description": l.get("description", "")
                         })
                         
                # Save to SQLite
                metadata_cache.save(
                    pano_id=pid,
                    lat=basic['lat'],
                    lng=basic['lng'],
                    capture_date=basic.get('capture_date'),
                    links=links,
                    center_heading=links_data.get('centerHeading', 0) if links_data else 0,
                    source='migration_script'
                )
                success_count += 1
                
            logger.info(f"  Saved {success_count}/{len(batch)} panos in batch.")
            
    finally:
        await fetcher.cleanup()
        
    logger.info("Migration Complete.")

if __name__ == "__main__":
    asyncio.run(migrate_height_tasks())
