"""
Task Generation CLI Script

Command-line interface for generating navigation and exploration tasks.

Usage (V2 Navigation - recommended):
    python scripts/generate_tasks.py --v2 \\
        --center-lat 47.5065 \\
        --center-lng 19.0551 \\
        --poi-type restaurant \\
        --poi-keyword "McDonald's" \\
        --spawn-count 2

Usage (V2 with Secondary Targets):
    python scripts/generate_tasks.py --v2 \\
        --center-lat 47.5065 \\
        --center-lng 19.0551 \\
        --poi-type restaurant \\
        --poi-keyword "McDonald's" \\
        --spawn-count 3 \\
        --secondary-keywords "Starbucks" "KFC"

Usage (Exploration Mode):
    python scripts/generate_tasks.py --v2 \\
        --center-lat 47.5065 \\
        --center-lng 19.0551 \\
        --poi-type restaurant \\
        --poi-keyword "McDonald's" \\
        --exploration-mode \\
        --spawn-count 2 \\
        --negative-keywords "Starbucks" "KFC"
"""

import os
import sys
import argparse
import asyncio
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_generator.task_assembler import TaskAssembler


async def generate_tasks_v2(args):
    """Generate navigation and exploration tasks using V2 algorithm."""
    assembler = TaskAssembler()
    
    # Parse secondary keywords
    secondary_keywords = args.secondary_keywords if args.secondary_keywords else None
    
    # Check if exploration tasks should be generated
    generate_exploration = args.include_exploration
    
    tasks = await assembler.generate_batch_tasks_v2(
        center_lat=args.center_lat,
        center_lng=args.center_lng,
        poi_type=args.poi_type,
        poi_keyword=args.poi_keyword,
        spawn_count=args.spawn_count,
        min_panos=args.min_panos,
        max_panos=args.max_panos,
        max_distance=args.max_distance,
        spawn_min_distance=args.spawn_min,
        spawn_max_distance=args.spawn_max,
        virtual_link_threshold=args.virtual_link_threshold,
        secondary_keywords=secondary_keywords,
        generate_exploration=generate_exploration
    )
    
    return tasks


async def generate_exploration_tasks(args):
    """Generate exploration tasks (find POI in area)."""
    assembler = TaskAssembler()
    
    # Parse negative keywords
    negative_keywords = args.negative_keywords if args.negative_keywords else None
    
    tasks = await assembler.generate_exploration_tasks(
        center_lat=args.center_lat,
        center_lng=args.center_lng,
        poi_type=args.poi_type,
        poi_keyword=args.poi_keyword,
        negative_keywords=negative_keywords,
        spawn_count=args.spawn_count,
        min_panos=args.min_panos,
        max_panos=args.max_panos,
        max_distance=args.max_distance,
        spawn_min_distance=args.spawn_min,
        spawn_max_distance=args.spawn_max,
        virtual_link_threshold=args.virtual_link_threshold
    )
    
    return tasks


def main():
    parser = argparse.ArgumentParser(
        description="Generate POI navigation/exploration tasks for VLN Benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate 2 McDonald's navigation tasks in Budapest
  python scripts/generate_tasks.py --v2 \\
      --center-lat 47.5065 --center-lng 19.0551 \\
      --poi-type restaurant --poi-keyword "McDonald's" \\
      --spawn-count 2

  # Generate tasks with secondary targets
  python scripts/generate_tasks.py --v2 \\
      --center-lat 47.5065 --center-lng 19.0551 \\
      --poi-type restaurant --poi-keyword "McDonald's" \\
      --spawn-count 3 --secondary-keywords "Starbucks" "KFC"

  # Generate exploration tasks with negative examples
  python scripts/generate_tasks.py --v2 \\
      --center-lat 47.5065 --center-lng 19.0551 \\
      --poi-type restaurant --poi-keyword "McDonald's" \\
      --exploration-mode --spawn-count 2 \\
      --negative-keywords "Starbucks"
"""
    )
    
    # Version selection
    parser.add_argument(
        "--v2",
        action="store_true",
        help="Use V2 algorithm (BFS from target, virtual links) - REQUIRED"
    )
    
    # Task type
    parser.add_argument(
        "--exploration-mode",
        action="store_true",
        help="Generate exploration tasks instead of navigation tasks"
    )
    
    # Required arguments
    parser.add_argument(
        "--center-lat",
        type=float,
        required=True,
        help="Search center latitude (e.g., 47.5065 for Budapest)"
    )
    parser.add_argument(
        "--center-lng",
        type=float,
        required=True,
        help="Search center longitude (e.g., 19.0551 for Budapest)"
    )
    parser.add_argument(
        "--poi-type",
        type=str,
        required=True,
        choices=["restaurant", "transit", "landmark", "service", "gas_station", "supermarket"],
        help="POI category to search for"
    )
    
    # Optional arguments
    parser.add_argument(
        "--poi-keyword",
        type=str,
        default=None,
        help="Specific POI keyword (e.g., 'McDonald\\'s')"
    )
    
    # V2 specific arguments
    parser.add_argument(
        "--spawn-count",
        type=int,
        default=None,
        help="Number of spawn points/tasks per target (default: from poi_config.json)"
    )
    parser.add_argument(
        "--min-panos",
        type=int,
        default=None,
        help="Minimum panoramas required (default: from poi_config.json)"
    )
    parser.add_argument(
        "--max-panos",
        type=int,
        default=None,
        help="Maximum panoramas to explore (default: from poi_config.json)"
    )
    parser.add_argument(
        "--max-distance",
        type=float,
        default=None,
        help="Maximum distance from target in meters (default: from poi_config.json)"
    )
    parser.add_argument(
        "--spawn-min",
        type=int,
        default=None,
        help="Minimum spawn distance from target in meters (default: from poi_config.json)"
    )
    parser.add_argument(
        "--spawn-max",
        type=int,
        default=None,
        help="Maximum spawn distance from target in meters (default: from poi_config.json)"
    )
    parser.add_argument(
        "--virtual-link-threshold",
        type=float,
        default=None,
        help="Distance threshold for virtual links in meters (default: from poi_config.json)"
    )
    
    # Multi-target arguments
    parser.add_argument(
        "--secondary-keywords",
        type=str,
        nargs="+",
        default=None,
        help="Secondary POI keywords for multi-target generation"
    )
    
    # Exploration task control
    parser.add_argument(
        "--include-exploration",
        action="store_true",
        help="Enable exploration task generation (disabled by default)"
    )
    
    # Exploration-specific arguments (for standalone exploration mode)
    parser.add_argument(
        "--negative-keywords",
        type=str,
        nargs="+",
        default=None,
        help="Keywords for negative examples in exploration mode"
    )
    
    # Logging
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Validate
    if not args.v2:
        parser.error("--v2 flag is required. V1 mode is deprecated.")
    
    if args.spawn_min is not None and args.spawn_max is not None and args.spawn_min >= args.spawn_max:
        parser.error("--spawn-min must be less than --spawn-max")
    
    if args.exploration_mode and not args.poi_keyword:
        parser.error("--poi-keyword is required for exploration mode")
    
    # Run generation
    try:
        if args.exploration_mode:
            asyncio.run(generate_exploration_tasks(args))
        else:
            asyncio.run(generate_tasks_v2(args))
    except KeyboardInterrupt:
        print("\n\n[!] Generation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[!] Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

