"""
Perception Task Generator - CLI Entry Point

Usage:
    python -m VLN_BENCHMARK.perception_generation.generate_perception_tasks \
        --lat 52.95481999 --lng -1.14771533 --radius 100 \
        --names "Jollibee" "vodafone" "McDonald's" "FOOTASYLUM" "HSBC UK" "JD" "schuh" "sainsbury's"
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root
sys.path.append(str(Path(__file__).parent.parent.parent))

from VLN_BENCHMARK.perception_generation.generator import PerceptionTaskGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(
        description="Generate perception tasks (distance/angle estimation) from POI pairs"
    )
    parser.add_argument("--lat", type=float, required=True, help="Center latitude")
    parser.add_argument("--lng", type=float, required=True, help="Center longitude")
    parser.add_argument("--radius", type=float, required=True, help="Search radius in meters")
    parser.add_argument("--names", nargs="+", required=True, help="Place names to search for")
    parser.add_argument("--api_key", type=str, help="Google API Key (optional, uses GOOGLE_API_KEY env var)")
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("Perception Task Generator")
    logger.info("=" * 60)
    logger.info(f"Center: ({args.lat}, {args.lng})")
    logger.info(f"Radius: {args.radius}m")
    logger.info(f"Places: {args.names}")
    logger.info("=" * 60)
    
    generator = PerceptionTaskGenerator(api_key=args.api_key)
    
    task_ids = await generator.generate_tasks(
        center_lat=args.lat,
        center_lng=args.lng,
        radius=args.radius,
        names=args.names
    )
    
    if task_ids:
        logger.info("=" * 60)
        logger.info(f"SUCCESS: Generated {len(task_ids)} tasks")
        for task_id in task_ids:
            logger.info(f"  - {task_id}")
        logger.info("=" * 60)
    else:
        logger.error("No tasks generated. Check logs for errors.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
