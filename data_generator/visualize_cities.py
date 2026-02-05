"""
City Distribution World Map Heatmap Generator
- Shows world map outline
- Highlights only visited cities
"""

import json
import os
import matplotlib.pyplot as plt
import numpy as np

try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    HAS_CARTOPY = True
except ImportError:
    HAS_CARTOPY = False
    print("Warning: cartopy not installed. Install with: pip install cartopy")
    print("Falling back to simple map...")

# File paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data")
BUILDING_HEIGHT_DIR = os.path.join(SCRIPT_DIR, "..", "building_height_generator")
CITIES_FILE = os.path.join(DATA_DIR, "cities.json")
STATE_FILE = os.path.join(DATA_DIR, "generation_state.json")
BUILDING_HEIGHT_STATE_FILE = os.path.join(BUILDING_HEIGHT_DIR, "generation_state.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "city_heatmap.png")


def load_data():
    """Load cities data and visited state from both generation sources"""
    with open(CITIES_FILE, 'r', encoding='utf-8') as f:
        cities = json.load(f)
    
    # Load from data generator state
    visited_cities = set()
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        state = json.load(f)
        visited_cities.update(state.get('visited_cities', []))
    
    # Load from building height generator state
    if os.path.exists(BUILDING_HEIGHT_STATE_FILE):
        with open(BUILDING_HEIGHT_STATE_FILE, 'r', encoding='utf-8') as f:
            building_state = json.load(f)
            visited_cities.update(building_state.get('visited_cities', []))
    
    return cities, visited_cities



def get_density_colors(lats, lngs):
    """Calculate density-based colors (Light Blue to Dark Blue)"""
    if not lats: return []
    # Convert to radians for spherical coordinates
    coords = np.radians(np.column_stack([lats, lngs]))
    
    # Convert to 3D Cartesian coordinates for dot product (cosine distance)
    xyz = np.column_stack([
        np.cos(coords[:,0]) * np.cos(coords[:,1]),
        np.cos(coords[:,0]) * np.sin(coords[:,1]),
        np.sin(coords[:,0])
    ])
    
    # Pairwise cosine similarity (dot product of unit vectors)
    # shapes: (N, 3) @ (3, N) -> (N, N)
    dots = np.clip(np.dot(xyz, xyz.T), -1.0, 1.0)
    
    # Angular distance in radians
    thetas = np.arccos(dots)
    
    # Gaussian Kernel Density Estimation
    # Sigma ~ 300km (Earth radius ~6371km -> 0.05 rad)
    sigma = 0.05
    weights = np.exp(-(thetas**2) / (2 * sigma**2))
    density = np.sum(weights, axis=1)
    
    # Normalize density to 0-1 range
    if density.max() > density.min():
        norm = (density - density.min()) / (density.max() - density.min())
    else:
        norm = np.zeros_like(density)
    
    # Interpolate between Light Blue (#64b5f6) and Medium-Deep Blue (#1565c0)
    # #64b5f6 [100, 181, 246] -> Start (Adjusted Light)
    # #1565c0 [21, 101, 192] -> End
    c_start = np.array([100, 181, 246]) / 255.0
    c_end = np.array([21, 101, 192]) / 255.0
    
    colors = []
    for t in norm:
        c = c_start * (1 - t) + c_end * t
        colors.append(c)
        
    return colors


def create_world_map_cartopy(cities, visited_cities):
    """Create world map with cartopy (real map outlines)"""
    # Get visited cities only
    visited_list = [c for c in cities if c['name'] in visited_cities]
    
    # Create figure with cartopy projection
    fig = plt.figure(figsize=(20, 10), facecolor='#ffffff')
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.Robinson())
    ax.set_facecolor('#e8f4fc')
    
    # Set global extent
    ax.set_global()
    
    # Add world map features
    ax.add_feature(cfeature.LAND, facecolor='#a8d8ea', edgecolor='none')
    ax.add_feature(cfeature.OCEAN, facecolor='#e8f4fc')
    ax.add_feature(cfeature.COASTLINE, linewidth=0.5, edgecolor='#5da5c7')
    ax.add_feature(cfeature.BORDERS, linewidth=0.3, edgecolor='#7fb8d8', linestyle=':')
    
    # Plot visited cities
    if visited_list:
        visited_lngs = [c['lng'] for c in visited_list]
        visited_lats = [c['lat'] for c in visited_list]
        
        # Calculate density colors
        base_colors = get_density_colors(visited_lats, visited_lngs)
        colors_glow = [(c[0], c[1], c[2], 0.2) for c in base_colors]
        colors_main = [(c[0], c[1], c[2], 0.9) for c in base_colors]
        
        # Glow effect
        ax.scatter(visited_lngs, visited_lats,
                   c=colors_glow, s=400,
                   transform=ccrs.PlateCarree(), zorder=2)
        
        # Main dots
        ax.scatter(visited_lngs, visited_lats,
                   c=colors_main, s=80,
                   edgecolors='none',
                   transform=ccrs.PlateCarree(), zorder=3)
    
    # Remove all axes and borders
    ax.spines['geo'].set_visible(False)
    
    plt.tight_layout(pad=0)
    
    return fig


def create_world_map_simple(cities, visited_cities):
    """Create simple world map without cartopy (fallback)"""
    # Get visited cities only
    visited_list = [c for c in cities if c['name'] in visited_cities]
    
    plt.style.use('default')
    fig, ax = plt.subplots(figsize=(20, 10), facecolor='#ffffff')
    ax.set_facecolor('#e8f4fc')
    
    # Draw grid lines (simple map reference)
    for lon in range(-180, 181, 30):
        ax.axvline(x=lon, color='#a8d8ea', linewidth=0.3, alpha=0.3)
    for lat in range(-90, 91, 30):
        ax.axhline(y=lat, color='#a8d8ea', linewidth=0.3, alpha=0.3)
    
    # Plot visited cities
    if visited_list:
        visited_lngs = [c['lng'] for c in visited_list]
        visited_lats = [c['lat'] for c in visited_list]
        
        # Calculate density colors
        base_colors = get_density_colors(visited_lats, visited_lngs)
        colors_glow = [(c[0], c[1], c[2], 0.2) for c in base_colors]
        colors_main = [(c[0], c[1], c[2], 0.9) for c in base_colors]
        
        # Glow effect
        ax.scatter(visited_lngs, visited_lats,
                   c=colors_glow, s=400, zorder=2)
        
        # Main dots
        ax.scatter(visited_lngs, visited_lats,
                   c=colors_main, s=80,
                   edgecolors='none', zorder=3)
    
    # Set axis range
    ax.set_xlim(-180, 180)
    ax.set_ylim(-70, 85)
    
    # Remove all text and borders
    ax.set_xticks([])
    ax.set_yticks([])
    ax.axis('off')
    
    plt.tight_layout(pad=0)
    
    return fig


def main():
    print("Loading data...")
    cities, visited_cities = load_data()
    
    print(f"Total cities: {len(cities)}")
    print(f"Visited cities: {len(visited_cities)}")
    
    print("Generating heatmap...")
    
    if HAS_CARTOPY:
        fig = create_world_map_cartopy(cities, visited_cities)
    else:
        fig = create_world_map_simple(cities, visited_cities)
    
    # Save image
    fig.savefig(OUTPUT_FILE, dpi=150, bbox_inches='tight', 
                facecolor='#ffffff', edgecolor='none', pad_inches=0)
    print(f"Heatmap saved to: {OUTPUT_FILE}")
    
    plt.show()


if __name__ == "__main__":
    main()
