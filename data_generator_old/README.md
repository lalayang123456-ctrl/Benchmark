# Data Generator Module

Automated test data generation for VLN Benchmark POI navigation tasks.

## Quick Start

```bash
# Generate a single McDonald's navigation task in Barcelona
python scripts/generate_tasks.py \
    --center-lat 41.4108 \
    --center-lng 2.1803 \
    --poi-type restaurant \
    --poi-keyword "McDonald's"

# Generate 5 bus stop navigation tasks
python scripts/generate_tasks.py \
    --center-lat 41.4108 \
    --center-lng 2.1803 \
    --poi-type transit \
    --poi-keyword "bus stop" \
    --count 5
```

## Features

- ✅ **POI Discovery**: Automatic search using Google Places API
- ✅ **Route Planning**: Real navigation paths from Google Directions API
- ✅ **Instruction Simplification**: Removes street names, keeps only directions
- ✅ **Large Whitelist Coverage**: Bidirectional BFS with 2x distance multiplier
- ✅ **Batch Generation**: Generate multiple tasks in one command

## Modules

- `poi_searcher.py` - Places API integration
- `directions_fetcher.py` - Routes + instruction simplification
- `whitelist_generator.py` - Bidirectional BFS exploration
- `task_assembler.py` - Main orchestrator
- `poi_config.json` - POI type configuration

## Output

Generated tasks are saved to:
- `tasks/nav_*.json` - Task definitions
- `config/geofence_config.json` - Updated whitelists

## Configuration

Edit `data_generator/poi_config.json` to customize POI categories and default parameters.
