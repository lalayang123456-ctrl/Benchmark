"""
Panorama Network Visualizer
Generates an interactive HTML map showing panorama connections.
"""

import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.metadata_fetcher import MetadataFetcher
from cache.metadata_cache import metadata_cache
from config.settings import settings


async def fetch_all_metadata(pano_ids: list, api_key: str) -> dict:
    """Fetch metadata for all panoramas."""
    fetcher = MetadataFetcher(api_key)
    results = {}
    
    for i, pano_id in enumerate(pano_ids):
        print(f"  Fetching {i+1}/{len(pano_ids)}: {pano_id[:20]}...")
        
        # Check cache first
        cached = metadata_cache.get(pano_id)
        if cached and "links" in cached:
            results[pano_id] = cached
            continue
        
        # Fetch from API
        success = fetcher.fetch_and_cache_all(pano_id)
        if success:
            results[pano_id] = metadata_cache.get(pano_id)
        
        await asyncio.sleep(0.1)  # Rate limiting
    
    return results


def generate_html_map(metadata: dict, spawn_id: str, target_id: str, task_id: str) -> str:
    """Generate an interactive HTML map with Leaflet."""
    
    # Prepare nodes and edges
    nodes = []
    edges = []
    
    for pano_id, meta in metadata.items():
        if not meta or "lat" not in meta:
            continue
        
        node_type = "normal"
        if pano_id == spawn_id:
            node_type = "spawn"
        elif pano_id == target_id:
            node_type = "target"
        
        nodes.append({
            "id": pano_id,
            "lat": meta["lat"],
            "lng": meta["lng"],
            "type": node_type
        })
        
        # Add edges for links
        for link in meta.get("links", []):
            link_id = link.get("panoId")
            if link_id and link_id in metadata:
                edges.append({
                    "from": pano_id,
                    "to": link_id
                })
    
    # Calculate center
    if nodes:
        center_lat = sum(n["lat"] for n in nodes) / len(nodes)
        center_lng = sum(n["lng"] for n in nodes) / len(nodes)
    else:
        center_lat, center_lng = 0, 0
    
    html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Panorama Network - {task_id}</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body {{ margin: 0; padding: 0; font-family: Arial, sans-serif; }}
        #map {{ width: 100%; height: 100vh; }}
        .legend {{
            position: absolute;
            bottom: 20px;
            left: 20px;
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            z-index: 1000;
        }}
        .legend h4 {{ margin: 0 0 10px 0; }}
        .legend-item {{ display: flex; align-items: center; margin: 5px 0; }}
        .legend-color {{ width: 20px; height: 20px; border-radius: 50%; margin-right: 8px; }}
        .spawn {{ background: #22c55e; }}
        .target {{ background: #ef4444; }}
        .normal {{ background: #3b82f6; }}
        .info {{
            position: absolute;
            top: 20px;
            right: 20px;
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            z-index: 1000;
        }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="legend">
        <h4>Legend</h4>
        <div class="legend-item"><div class="legend-color spawn"></div>Spawn Point</div>
        <div class="legend-item"><div class="legend-color target"></div>Target (McDonald's)</div>
        <div class="legend-item"><div class="legend-color normal"></div>Panorama Node</div>
    </div>
    <div class="info">
        <strong>Task:</strong> {task_id}<br>
        <strong>Nodes:</strong> {len(nodes)}<br>
        <strong>Edges:</strong> {len(edges) // 2}
    </div>
    <script>
        const nodes = {json.dumps(nodes)};
        const edges = {json.dumps(edges)};
        
        // Initialize map
        const map = L.map('map').setView([{center_lat}, {center_lng}], 17);
        
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '© OpenStreetMap contributors'
        }}).addTo(map);
        
        // Draw edges first (so they're below nodes)
        const drawnEdges = new Set();
        edges.forEach(edge => {{
            const key = [edge.from, edge.to].sort().join('-');
            if (drawnEdges.has(key)) return;
            drawnEdges.add(key);
            
            const fromNode = nodes.find(n => n.id === edge.from);
            const toNode = nodes.find(n => n.id === edge.to);
            
            if (fromNode && toNode) {{
                L.polyline([[fromNode.lat, fromNode.lng], [toNode.lat, toNode.lng]], {{
                    color: '#94a3b8',
                    weight: 2,
                    opacity: 0.6
                }}).addTo(map);
            }}
        }});
        
        // Draw nodes
        nodes.forEach(node => {{
            let color = '#3b82f6';
            let radius = 6;
            
            if (node.type === 'spawn') {{
                color = '#22c55e';
                radius = 10;
            }} else if (node.type === 'target') {{
                color = '#ef4444';
                radius = 10;
            }}
            
            L.circleMarker([node.lat, node.lng], {{
                radius: radius,
                fillColor: color,
                color: '#fff',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.9
            }}).addTo(map)
              .bindPopup(`<b>${{node.type === 'spawn' ? 'SPAWN' : node.type === 'target' ? 'TARGET' : 'Node'}}</b><br>ID: ${{node.id.substring(0, 15)}}...`);
        }});
        
        // Fit bounds to show all nodes
        if (nodes.length > 0) {{
            const bounds = L.latLngBounds(nodes.map(n => [n.lat, n.lng]));
            map.fitBounds(bounds.pad(0.1));
        }}
    </script>
</body>
</html>'''
    
    return html


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Visualize panorama network for a task")
    parser.add_argument("--task-id", type=str, default="nav_mcdonalds_20260116_134537",
                        help="Task ID to visualize")
    args = parser.parse_args()
    
    # Load task
    task_file = Path(__file__).parent.parent / "tasks" / f"{args.task_id}.json"
    if not task_file.exists():
        print(f"Error: Task file not found: {task_file}")
        return
    
    with open(task_file, 'r') as f:
        task = json.load(f)
    
    # Load whitelist
    config_file = Path(__file__).parent.parent / "config" / "geofence_config.json"
    with open(config_file, 'r') as f:
        config = json.load(f)
    
    whitelist = config.get(task["geofence"], [])
    
    print(f"Task: {task['task_id']}")
    print(f"Spawn: {task['spawn_point']}")
    print(f"Target: {task['target_pano_ids'][0]}")
    print(f"Whitelist: {len(whitelist)} panoramas")
    print("\nFetching metadata...")
    
    # Fetch all metadata
    metadata = await fetch_all_metadata(whitelist, settings.GOOGLE_API_KEY)
    
    print(f"\nFetched {len(metadata)} panorama metadata")
    
    # Generate HTML
    html = generate_html_map(
        metadata,
        task["spawn_point"],
        task["target_pano_ids"][0],
        task["task_id"]
    )
    
    # Save HTML
    output_file = Path(__file__).parent.parent / "tasks" / f"{task['task_id']}_network.html"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"\n[OK] Visualization saved to: {output_file}")
    print(f"Open this file in a browser to view the network map.")


if __name__ == "__main__":
    asyncio.run(main())
