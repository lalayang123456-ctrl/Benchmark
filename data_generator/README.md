# Data Generator Module

Automated task generation for VLN Benchmark navigation and exploration tasks.

## Overview

This module implements the task generation pipeline described in `task_generation_process.md`. It generates complete navigation tasks by:

1. **Searching** for target POIs using Google Places API
2. **Exploring** the Street View network via BFS from target
3. **Enhancing** panorama connections with virtual links
4. **Selecting** dispersed spawn points using Greedy Farthest Point Sampling
5. **Generating** task JSON files with navigation descriptions

## Quick Start

```bash
# Generate McDonald's navigation tasks in Budapest
python -m data_generator.task_assembler

# Or use the CLI script
python scripts/generate_tasks.py --v2 \
    --center-lat 47.5065 \
    --center-lng 19.0551 \
    --poi-type restaurant \
    --poi-keyword "McDonald's" \
    --spawn-count 2
```

## Modules

| Module | Description |
|--------|-------------|
| `poi_searcher.py` | Google Places API integration (Text Search + Nearby Search) |
| `directions_fetcher.py` | Google Routes API + instruction simplification |
| `whitelist_generator.py` | BFS exploration from target panorama |
| `link_enhancer.py` | Virtual link addition (18m threshold) |
| `task_assembler.py` | Main orchestrator |
| `visualization.py` | Interactive HTML network visualization |
| `poi_config.json` | POI categories and default parameters |

## Features

### V2 Algorithm
- **BFS from target**: Ensures all spawn points are reachable from target
- **Virtual links**: 18m threshold for enhanced connectivity
- **No distance pruning**: Preserves original Google API links
- **External link filtering**: Removes links outside whitelist

### Spawn Point Selection
Uses **Greedy Farthest Point Sampling**:
1. First point: Random selection
2. Subsequent points: Choose the candidate furthest from all already selected points

This ensures spawn points are spatially distributed around the target.

### Multi-Target Support
- Primary target: Text Search API (keyword-based)
- Secondary targets: Within same whitelist (validated by `nearest_pano_id ∈ whitelist`)
- Each target gets `spawn_count` independent tasks

### Task Types

| Type | Description | Answer Format |
|------|-------------|---------------|
| `navigation_to_poi` | Follow instructions to reach POI | N/A |
| `exploration_find_poi` | Search area for POI, answer yes/no | `yes` or `no` |

## CLI Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--center-lat` | float | Required | Search center latitude |
| `--center-lng` | float | Required | Search center longitude |
| `--poi-type` | string | Required | POI category |
| `--poi-keyword` | string | Optional | Specific POI name |
| `--v2` | flag | - | Use V2 algorithm |
| `--spawn-count` | int | 2 | Tasks per target |
| `--min-panos` | int | 20 | Minimum panoramas |
| `--max-panos` | int | 60 | Maximum panoramas |
| `--max-distance` | float | 500 | Max BFS distance (m) |
| `--spawn-min` | int | 100 | Min spawn distance (m) |
| `--spawn-max` | int | 200 | Max spawn distance (m) |
| `--virtual-link-threshold` | float | 18 | Virtual link distance (m) |
| `--secondary-keywords` | list | [] | Secondary POI keywords |
| `--exploration-mode` | flag | - | Generate exploration tasks |
| `--negative-keywords` | list | [] | Negative example keywords |

## Output

### Task Files
- Location: `tasks/{task_id}.json`
- Format:
```json
{
    "task_id": "nav_mcdonalds_20260119_223000_1",
    "task_type": "navigation_to_poi",
    "geofence": "list_nav_mcdonalds_20260119_223000",
    "spawn_point": "pano_id",
    "spawn_heading": 135.0,
    "description": "Navigate to McDonald's. Walk northeast...",
    "ground_truth": {
        "target_name": "McDonald's",
        "target_pano_id": "target_pano_id",
        "optimal_distance_meters": 156
    },
    "target_pano_ids": ["target_pano_id"],
    "max_steps": null,
    "max_time_seconds": 300
}
```

### Whitelist Config
- Location: `config/geofence_config.json`
- Contains panorama ID lists keyed by geofence name

### Visualization
- Location: `vis/{geofence_name}_network.html`
- Interactive Leaflet.js map
- Click on nodes to highlight connections
- Color-coded: target (red), spawn (blue), connected (green)

## Configuration

Edit `poi_config.json` to customize:
- POI categories and keywords
- Recommended secondary types for Nearby Search
- Default generation parameters

## Dependencies

- `aiohttp`: Async HTTP requests
- `python-dotenv`: Environment variable loading
- Parent module: `engine.metadata_fetcher` for panorama metadata

## Environment Variables

```
GOOGLE_API_KEY=your_api_key_here
```

## Example: Multi-Target Generation

```python
from data_generator import TaskAssembler
import asyncio

async def main():
    assembler = TaskAssembler()
    
    # Generate tasks for McDonald's and nearby Starbucks
    tasks = await assembler.generate_batch_tasks_v2(
        center_lat=47.5065,
        center_lng=19.0551,
        poi_type="restaurant",
        poi_keyword="McDonald's",
        spawn_count=3,
        secondary_keywords=["Starbucks", "KFC"]
    )
    
    print(f"Generated {len(tasks)} tasks")

asyncio.run(main())
```

## Example: Exploration Tasks

```python
from data_generator import TaskAssembler
import asyncio

async def main():
    assembler = TaskAssembler()
    
    # Generate exploration tasks
    tasks = await assembler.generate_exploration_tasks(
        center_lat=47.5065,
        center_lng=19.0551,
        poi_type="restaurant",
        poi_keyword="McDonald's",
        negative_keywords=["Starbucks"],  # Generate "no" answer tasks
        spawn_count=2
    )
    
    print(f"Generated {len(tasks)} exploration tasks")

asyncio.run(main())
```
