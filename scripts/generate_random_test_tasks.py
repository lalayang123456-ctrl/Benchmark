
import os
import sys
import asyncio
import random
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_generator.task_assembler import TaskAssembler

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

# POI Configuration
POI_DATA = {
    "restaurant": ["McDonald's", "KFC", "Starbucks", "Subway", "Pizza Hut", "Burger King"],
    "supermarket": ["Carrefour", "Aldi", "Lidl", "Tesco", "Whole Foods"],
    "gas_station": ["Shell", "BP", "Exxon", "TotalEnergies"],
    "landmark": ["Park", "Museum", "Church"],
    "service": ["Bank", "Post Office", "Pharmacy"]
}

# Major Cities (Lat, Lng)
CITIES = [
    {"name": "New York, USA", "lat": 40.7128, "lng": -74.0060},
    {"name": "London, UK", "lat": 51.5074, "lng": -0.1278},
    {"name": "Tokyo, Japan", "lat": 35.6762, "lng": 139.6503},
    {"name": "Sydney, Australia", "lat": -33.8688, "lng": 151.2093},
    {"name": "Paris, France", "lat": 48.8566, "lng": 2.3522},
    {"name": "Berlin, Germany", "lat": 52.5200, "lng": 13.4050},
    {"name": "Toronto, Canada", "lat": 43.65107, "lng": -79.347015},
    {"name": "Singapore", "lat": 1.3521, "lng": 103.8198},
    {"name": "Los Angeles, USA", "lat": 34.0522, "lng": -118.2437},
    {"name": "Chicago, USA", "lat": 41.8781, "lng": -87.6298},
    {"name": "San Francisco, USA", "lat": 37.7749, "lng": -122.4194},
    {"name": "Miami, USA", "lat": 25.7617, "lng": -80.1918},
    {"name": "Seoul, South Korea", "lat": 37.5665, "lng": 126.9780},
    {"name": "Barcelona, Spain", "lat": 41.3851, "lng": 2.1734},
    {"name": "Rome, Italy", "lat": 41.9028, "lng": 12.4964},
    {"name": "Amsterdam, Netherlands", "lat": 52.3676, "lng": 4.9041},
    {"name": "Bangkok, Thailand", "lat": 13.7563, "lng": 100.5018},
    {"name": "Dubai, UAE", "lat": 25.2048, "lng": 55.2708},
    {"name": "Istanbul, Turkey", "lat": 41.0082, "lng": 28.9784},
    {"name": "Melbourne, Australia", "lat": -37.8136, "lng": 144.9631}
]

def get_random_poi():
    """Select a random POI type and keyword."""
    poi_type = random.choice(list(POI_DATA.keys()))
    keyword = random.choice(POI_DATA[poi_type])
    return poi_type, keyword

def get_random_keyword_any_type():
    """Select a random keyword from any type."""
    all_keywords = [k for sublist in POI_DATA.values() for k in sublist]
    return random.choice(all_keywords)

async def generate_random_tasks():
    # Setup Output Directory
    # We want to put everything in a new folder 'tasks_test'
    # Assuming relative to the project root (where the script handles paths)
    project_root = Path(__file__).parent.parent
    output_dir = project_root / "tasks_test"
    output_dir.mkdir(exist_ok=True)
    
    logger.info(f"Output directory set to: {output_dir}")
    
    # Initialize TaskAssembler
    assembler = TaskAssembler()
    
    # Override output directories
    assembler.tasks_dir = output_dir
    assembler.config_dir = output_dir  # For geofence_config.json
    assembler.vis_dir = output_dir     # For html visualization
    
    total_generations = 10
    
    for i in range(total_generations):
        logger.info(f"\n[{i+1}/{total_generations}] Preparing generation...")
        
        # 1. Pick Random Location
        city = random.choice(CITIES)
        
        # 2. Pick Primary Goal
        primary_type, primary_keyword = get_random_poi()
        
        # 3. Pick 2 Random Secondary Goals (distinct)
        secondaries = []
        while len(secondaries) < 2:
            sec_kw = get_random_keyword_any_type()
            # Avoid duplicates with primary and each other
            if sec_kw != primary_keyword and sec_kw not in secondaries:
                secondaries.append(sec_kw)
        
        logger.info(f"Target: {city['name']} | Primary: {primary_keyword} ({primary_type}) | Secondary: {secondaries}")
        
        try:
            # Generate Tasks
            # We use spawn_count=1 to keep it light, or 2 as default.
            # 'Main goal randomly picked... secondary goal picked two'
            await assembler.generate_batch_tasks_v2(
                center_lat=city['lat'],
                center_lng=city['lng'],
                poi_type=primary_type,
                poi_keyword=primary_keyword,
                secondary_keywords=secondaries,
                spawn_count=2,       # 1 spawn point per target -> 1 Nav + 1 Exp task per target
                min_panos=30,        # Reduce requirements for faster testing/higher success rate
                max_panos=120,
                max_distance=500,
                generate_exploration=False # User didn't strictly ask for exploration, but 'tasks' usually implies navigation. 
                                           # If I disable exploration, I get fewer files.
                                           # I will keep exploration disabled to reduce clutter unless requested. 
                                           # Wait, "vis html also". 
                                           # I'll enable exploration if the user implies standard generation.
                                           # "tasks of automatically generate... main goal... secondary goal"
                                           # I'll set generate_exploration=True to be safe, easier to delete than recreate.
            )
        except Exception as e:
            logger.error(f"Failed to generate for {city['name']}: {e}")
            # Continue to next iteration even if one fails
            continue

    logger.info("Generation Loop Complete.")

if __name__ == "__main__":
    asyncio.run(generate_random_tasks())
