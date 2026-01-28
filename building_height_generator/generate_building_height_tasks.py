import argparse
import asyncio
import logging
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Add project root
sys.path.append(str(Path(__file__).parent.parent.parent))

from VLN_BENCHMARK.building_height_generator.generator import BuildingHeightTaskGenerator

# Load .env from VLN_BENCHMARK directory
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

async def main():
    parser = argparse.ArgumentParser(description="Generate Building Height Estimation Tasks")
    parser.add_argument("--lat", type=float, help="Center Latitude (optional, random city if omitted)")
    parser.add_argument("--lng", type=float, help="Center Longitude (optional, random city if omitted)")
    parser.add_argument("--radius", type=float, default=100, help="Search radius for targets (meters)")
    parser.add_argument("--count", type=int, default=1, help="Number of tasks to generate")
    parser.add_argument("--api_key", type=str, help="Google API Key")
    
    args = parser.parse_args()
    
    # Predefined cities with good Street View & Building coverage
    CITIES = [
        {"name": "New York, USA", "lat": 40.7580, "lng": -73.9855},
        {"name": "London, UK", "lat": 51.5074, "lng": -0.1278},
        {"name": "Tokyo, Japan", "lat": 35.6895, "lng": 139.6917},
        {"name": "Paris, France", "lat": 48.8566, "lng": 2.3522},
        {"name": "San Francisco, USA", "lat": 37.7749, "lng": -122.4194},
        {"name": "Toronto, Canada", "lat": 43.651070, "lng": -79.347015},
        {"name": "Sydney, Australia", "lat": -33.8688, "lng": 151.2093},
        {"name": "Barcelona, Spain", "lat": 41.3851, "lng": 2.1734}
    ]

    import random
    
    # Determine center
    if args.lat is not None and args.lng is not None:
        center_lat, center_lng = args.lat, args.lng
        print(f"[*] Using specified center: {center_lat}, {center_lng}")
    else:
        city = random.choice(CITIES)
        center_lat, center_lng = city["lat"], city["lng"]
        print(f"[*] Randomly selected city: {city['name']} ({center_lat}, {center_lng})")
    
    generator = BuildingHeightTaskGenerator(api_key=args.api_key)
    
    task_ids = await generator.generate_batch(
        center_lat=center_lat,
        center_lng=center_lng,
        radius=args.radius,
        count=args.count
    )
    
    print(f"\nSuccessfully generated {len(task_ids)} tasks:")
    for tid in task_ids:
        print(f"- {tid}")

if __name__ == "__main__":
    asyncio.run(main())
