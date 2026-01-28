"""
Visualization - Interactive Network HTML Generation

Generates interactive HTML visualizations for panorama networks.
"""

import json
import logging
from typing import Dict, List, Set, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body {{ margin: 0; padding: 0; font-family: Arial, sans-serif; }}
        #map {{ width: 100%; height: 100vh; }}
        .info-panel {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            z-index: 1000;
            max-width: 300px;
        }}
        .info-panel h3 {{ margin: 0 0 10px 0; }}
        .legend {{
            display: flex;
            flex-direction: column;
            gap: 5px;
            margin-top: 10px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .legend-dot {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }}
        .selected-info {{
            margin-top: 15px;
            padding-top: 10px;
            border-top: 1px solid #eee;
        }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="info-panel">
        <h3>{title}</h3>
        <div>Total Panos: <strong>{total_panos}</strong></div>
        <div>Spawn Points: <strong>{spawn_count}</strong></div>
        <div class="legend">
            <div class="legend-item">
                <div class="legend-dot" style="background: #e74c3c;"></div>
                <span>Target</span>
            </div>
            <div class="legend-item">
                <div class="legend-dot" style="background: #3498db;"></div>
                <span>Spawn Point</span>
            </div>
            <div class="legend-item">
                <div class="legend-dot" style="background: #95a5a6;"></div>
                <span>Panorama</span>
            </div>
            <div class="legend-item">
                <div class="legend-dot" style="background: #2ecc71;"></div>
                <span>Connected (click)</span>
            </div>
        </div>
        <div class="selected-info" id="selected-info">
            Click a point to see connections
        </div>
    </div>
    
    <script>
        // Data
        const panoData = {pano_data};
        const targetPanos = {target_panos};
        const spawnPoints = {spawn_points};
        
        // Initialize map
        const map = L.map('map');
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '© OpenStreetMap contributors'
        }}).addTo(map);
        
        // Markers and lines
        const markers = {{}};
        const connectionLines = [];
        let selectedPano = null;
        
        // Create markers
        const bounds = [];
        Object.entries(panoData).forEach(([panoId, data]) => {{
            const lat = data.lat;
            const lng = data.lng;
            bounds.push([lat, lng]);
            
            // Determine marker style
            let color = '#95a5a6';  // Default gray
            let radius = 6;
            let zIndex = 100;
            
            if (targetPanos.includes(panoId)) {{
                color = '#e74c3c';  // Red for target
                radius = 10;
                zIndex = 300;
            }} else if (spawnPoints.includes(panoId)) {{
                color = '#3498db';  // Blue for spawn
                radius = 8;
                zIndex = 200;
            }}
            
            const marker = L.circleMarker([lat, lng], {{
                radius: radius,
                fillColor: color,
                color: '#333',
                weight: 1,
                opacity: 1,
                fillOpacity: 0.8
            }}).addTo(map);
            
            marker.panoId = panoId;
            marker.originalColor = color;
            marker.on('click', () => selectPano(panoId));
            
            markers[panoId] = marker;
        }});
        
        // Fit map to bounds
        if (bounds.length > 0) {{
            map.fitBounds(bounds, {{ padding: [50, 50] }});
        }}
        
        // Select panorama function
        function selectPano(panoId) {{
            // Clear previous selection
            clearSelection();
            
            selectedPano = panoId;
            const data = panoData[panoId];
            const links = data.links || [];
            
            // Highlight connected panos
            links.forEach(link => {{
                const targetId = link.pano_id;
                if (markers[targetId]) {{
                    markers[targetId].setStyle({{ fillColor: '#2ecc71' }});
                    
                    // Draw connection line
                    const line = L.polyline([
                        [data.lat, data.lng],
                        [panoData[targetId].lat, panoData[targetId].lng]
                    ], {{
                        color: link.virtual ? '#e67e22' : '#27ae60',
                        weight: 2,
                        opacity: 0.7,
                        dashArray: link.virtual ? '5, 5' : null
                    }}).addTo(map);
                    connectionLines.push(line);
                }}
            }});
            
            // Update info panel
            const infoDiv = document.getElementById('selected-info');
            const virtualCount = links.filter(l => l.virtual).length;
            const nativeCount = links.length - virtualCount;
            
            let typeStr = '';
            if (targetPanos.includes(panoId)) {{
                typeStr = ' (Target)';
            }} else if (spawnPoints.includes(panoId)) {{
                typeStr = ' (Spawn)';
            }}
            
            infoDiv.innerHTML = `
                <strong>Selected:</strong> ${{panoId.substring(0, 20)}}...${{typeStr}}<br>
                <strong>Connections:</strong> ${{links.length}}<br>
                <span style="color: #27ae60;">● Native: ${{nativeCount}}</span><br>
                <span style="color: #e67e22;">○ Virtual: ${{virtualCount}}</span>
            `;
        }}
        
        // Clear selection
        function clearSelection() {{
            // Reset marker colors
            Object.entries(markers).forEach(([panoId, marker]) => {{
                marker.setStyle({{ fillColor: marker.originalColor }});
            }});
            
            // Remove connection lines
            connectionLines.forEach(line => map.removeLayer(line));
            connectionLines.length = 0;
        }}
        
        // Click on map to deselect
        map.on('click', (e) => {{
            if (e.originalEvent.target === map._container) {{
                clearSelection();
                document.getElementById('selected-info').innerHTML = 'Click a point to see connections';
            }}
        }});
    </script>
</body>
</html>
"""


def generate_network_html(
    geofence_name: str,
    metadata_map: Dict[str, dict],
    spawn_points: List[str],
    target_pano_ids: List[str],
    output_dir: str = "vis"
) -> str:
    """
    Generate interactive HTML visualization of the panorama network.
    
    Args:
        geofence_name: Name for the geofence/whitelist
        metadata_map: Dictionary mapping pano_id to metadata
        spawn_points: List of spawn point panorama IDs
        target_pano_ids: List of Target panorama IDs
        output_dir: Output directory for HTML file
    
    Returns:
        Path to generated HTML file
    """
    # Prepare data for JavaScript
    pano_data = {}
    for pano_id, meta in metadata_map.items():
        pano_data[pano_id] = {
            "lat": meta.get("lat"),
            "lng": meta.get("lng"),
            "links": meta.get("links", [])
        }
    
    # Generate HTML
    html_content = HTML_TEMPLATE.format(
        title=geofence_name,
        total_panos=len(metadata_map),
        spawn_count=len(spawn_points),
        pano_data=json.dumps(pano_data),
        target_panos=json.dumps(target_pano_ids),
        spawn_points=json.dumps(spawn_points)
    )
    
    # Write to file
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    html_file = output_path / f"{geofence_name}_network.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    logger.info(f"Generated visualization: {html_file}")
    return str(html_file)


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Example data
    metadata = {
        "pano_1": {
            "lat": 47.5065,
            "lng": 19.0551,
            "links": [{"pano_id": "pano_2", "heading": 45, "virtual": False}]
        },
        "pano_2": {
            "lat": 47.5066,
            "lng": 19.0553,
            "links": [{"pano_id": "pano_1", "heading": 225, "virtual": False}]
        },
        "pano_3": {
            "lat": 47.5068,
            "lng": 19.0550,
            "links": []
        }
    }
    
    html_path = generate_network_html(
        geofence_name="test_network",
        metadata_map=metadata,
        spawn_points=["pano_3"],
        target_pano_ids=["pano_1"],
        output_dir="vis"
    )
    
    print(f"Generated: {html_path}")
