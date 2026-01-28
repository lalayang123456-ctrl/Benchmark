#!/usr/bin/env python
"""
Generate Spatial Orientation (Distance/Bearing Estimation) Tasks

Usage:
    python scripts/generate_spatial_tasks.py --lat 40.7580 --lng -73.9855 --count 5
    python scripts/generate_spatial_tasks.py --count 3  # Random city
"""

import sys
import asyncio
import argparse
import logging
import random
import os
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from VLN_BENCHMARK.spatial_orientation_generator.generator import SpatialOrientationTaskGenerator

# Load .env from VLN_BENCHMARK directory
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


async def main():
    parser = argparse.ArgumentParser(description="Generate Spatial Orientation Tasks")
    parser.add_argument("--lat", type=float, default=None, help="Center latitude (optional, random city if omitted)")
    parser.add_argument("--lng", type=float, default=None, help="Center longitude (optional, random city if omitted)")
    parser.add_argument("--radius", type=float, default=500, help="Sampling radius in meters (default: 500)")
    parser.add_argument("--count", type=int, default=1, help="Number of tasks to generate (default: 1)")
    parser.add_argument("--api_key", type=str, help="Google API Key")
    
    args = parser.parse_args()
    
    generator = SpatialOrientationTaskGenerator(api_key=args.api_key)
    
    print("=" * 60)
    print("Spatial Orientation Task Generator")
    print("=" * 60)
    
    task_ids = await generator.generate_batch(
        center_lat=args.lat,
        center_lng=args.lng,
        radius=args.radius,
        count=args.count
    )
    
    print("=" * 60)
    if task_ids:
        print(f"Successfully generated {len(task_ids)} task(s):")
        for tid in task_ids:
            print(f"  - {tid}")
    else:
        print("No tasks generated. Try different coordinates or increase radius.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
