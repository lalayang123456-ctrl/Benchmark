import sys
from pathlib import Path
sys.path.insert(0, str(Path('.')))
from cache.metadata_cache import metadata_cache
import json

# Get task spawn point
with open('tasks/task_001.json') as f:
    task = json.load(f)

spawn_pano_id = task.get('spawn_point')
spawn_heading = task.get('spawn_heading', 0)
print(f'Spawn Point: {spawn_pano_id}')
print(f'Spawn Heading: {spawn_heading}')
print()

# Get metadata
metadata = metadata_cache.get(spawn_pano_id)
if metadata:
    print(f'Location: ({metadata["lat"]}, {metadata["lng"]})')
    print(f'centerHeading: {metadata.get("center_heading", "N/A")}')
    print()
    print('Links:')
    for i, link in enumerate(metadata.get('links', []), 1):
        pano_id = link.get('panoId') or link.get('pano_id')
        heading = link.get('heading')
        desc = link.get('description', '')
        print(f'  {i}. heading={heading:.1f}, panoId={pano_id[:20]}..., desc="{desc}"')
        
    print()
    print(f'Agent facing: {spawn_heading} degrees')
    print()
    print('Relative directions from agent perspective:')
    for i, link in enumerate(metadata.get('links', []), 1):
        heading = link.get('heading')
        relative = (heading - spawn_heading + 360) % 360
        print(f'  Link {i}: absolute={heading:.1f}, relative to agent={relative:.1f}')
else:
    print('No metadata found')
