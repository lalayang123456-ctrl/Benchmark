"""
Quick test script to verify the data generator pipeline.

This tests each module individually and then the full pipeline.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_generator.poi_searcher import POISearcher
from data_generator.directions_fetcher import DirectionsFetcher
from data_generator.whitelist_generator import WhitelistGenerator
from data_generator.task_assembler import TaskAssembler


async def test_poi_searcher():
    """Test POI search functionality."""
    print("\n" + "="*60)
    print("Testing POI Searcher...")
    print("="*60)
    
    searcher = POISearcher()
    pois = await searcher.search_nearby(
        lat=41.4108,
        lng=2.1803,
        poi_type="gas_station",
        keyword="gas station"
    )
    
    assert len(pois) > 0, "No POIs found"
    print(f"[OK] Found {len(pois)} POIs")
    
    # Enrich
    pois = await searcher.enrich_with_pano_ids(pois)
    assert len(pois) > 0, "No POIs with panoramas"
    print(f"[OK] {len(pois)} POIs have Street View coverage")
    print(f"  Sample: {pois[0].name} at {pois[0].nearest_pano_id}")


async def test_directions_fetcher():
    """Test route planning."""
    print("\n" + "="*60)
    print("Testing Directions Fetcher...")
    print("="*60)
    
    fetcher = DirectionsFetcher()
    route = await fetcher.get_route(
        origin_lat=41.4100,
        origin_lng=2.1800,
        dest_lat=41.4120,
        dest_lng=2.1810
    )
    
    assert len(route.steps) > 0, "No route steps"
    print(f"[OK] Route has {len(route.steps)} steps")
    print(f"  Distance: {route.total_distance_text}")
    print(f"  Sample step: '{route.steps[0].instruction}'")
    
    # Test instruction simplification
    original = "Turn right onto <b>King Street</b>"
    simplified = fetcher.simplify_instructions(original)
    assert "King Street" not in simplified, "Street name not removed"
    assert "Turn right" in simplified, "Action not preserved"
    print(f"[OK] Instruction simplification works")


async def test_full_pipeline():
    """Test complete task generation."""
    print("\n" + "="*60)
    print("Testing Full Pipeline...")
    print("="*60)
    
    assembler = TaskAssembler()
    
    task = await assembler.generate_navigation_task(
        center_lat=41.4108,
        center_lng=2.1803,
        poi_type="gas_station",
        poi_keyword="gas station",
        task_id="test_task_001"
    )
    
    # Verify task structure
    assert task["task_id"] == "test_task_001"
    assert task["task_type"] == "navigation_to_poi"
    assert "spawn_point" in task
    assert "description" in task
    assert len(task["target_pano_ids"]) > 0
    
    print(f"[OK] Task generated successfully")
    print(f"  Task ID: {task['task_id']}")
    print(f"  Target: {task['ground_truth']['target_name']}")
    print(f"  Distance: {task['ground_truth']['optimal_distance_meters']}m")


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("Data Generator Pipeline Tests")
    print("="*60)
    
    try:
        await test_poi_searcher()
        await test_directions_fetcher()
        await test_full_pipeline()
        
        print("\n" + "="*60)
        print("All tests passed!")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
