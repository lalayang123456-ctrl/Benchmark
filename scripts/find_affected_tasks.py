"""
Script to find tasks that contain black-bottom panoramas in their geofence whitelist.
"""

import json
import os
from pathlib import Path

def main():
    ROOT_DIR = Path(__file__).parent.parent
    
    # Load black bottom pano IDs (strip _z2 suffix to match geofence format)
    black_bottom_file = ROOT_DIR / "scripts" / "black_bottom_panos.txt"
    with open(black_bottom_file, "r") as f:
        black_bottom_ids = set()
        for line in f:
            pano_id = line.strip()
            if pano_id:
                # Strip _z2 suffix if present
                if pano_id.endswith("_z2"):
                    pano_id = pano_id[:-3]
                black_bottom_ids.add(pano_id)
    
    print(f"Loaded {len(black_bottom_ids)} black-bottom pano IDs")
    
    # Load geofence config
    geofence_file = ROOT_DIR / "config" / "geofence_config.json"
    with open(geofence_file, "r") as f:
        geofence_config = json.load(f)
    
    print(f"Loaded {len(geofence_config)} geofence lists")
    
    # Find which geofence lists contain black-bottom panos
    affected_geofences = {}
    for geofence_name, pano_list in geofence_config.items():
        bad_panos = set(pano_list) & black_bottom_ids
        if bad_panos:
            affected_geofences[geofence_name] = bad_panos
    
    print(f"\nFound {len(affected_geofences)} geofence lists containing black-bottom panos:")
    for name, panos in affected_geofences.items():
        print(f"  - {name}: {len(panos)} bad panos")
    
    # Scan task directories
    task_dirs = [
        ROOT_DIR / "tasks",
        ROOT_DIR / "tasks_height",
        ROOT_DIR / "tasks_perception"
    ]
    
    affected_tasks = []
    
    for task_dir in task_dirs:
        if not task_dir.exists():
            print(f"\nWarning: {task_dir} does not exist, skipping")
            continue
            
        print(f"\nScanning {task_dir}...")
        task_files = list(task_dir.glob("*.json"))
        
        for task_file in task_files:
            try:
                with open(task_file, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
                
                geofence_name = task_data.get("geofence", "")
                
                if geofence_name in affected_geofences:
                    task_id = task_data.get("task_id", task_file.stem)
                    bad_panos = list(affected_geofences[geofence_name])
                    affected_tasks.append({
                        "task_id": task_id,
                        "task_file": str(task_file.relative_to(ROOT_DIR)),
                        "geofence": geofence_name,
                        "bad_pano_count": len(bad_panos),
                        "bad_panos": bad_panos[:5]  # Only show first 5
                    })
            except Exception as e:
                print(f"Error reading {task_file}: {e}")
    
    # Summary
    print("\n" + "=" * 60)
    print(f"SUMMARY: Found {len(affected_tasks)} tasks with black-bottom panos in geofence")
    print("=" * 60)
    
    # Group by directory
    by_dir = {}
    for task in affected_tasks:
        dir_name = Path(task["task_file"]).parent.name
        if dir_name not in by_dir:
            by_dir[dir_name] = []
        by_dir[dir_name].append(task)
    
    for dir_name, tasks in by_dir.items():
        print(f"\n{dir_name}: {len(tasks)} affected tasks")
        for task in tasks[:10]:  # Show first 10
            print(f"  - {task['task_id']} (geofence: {task['geofence']}, {task['bad_pano_count']} bad panos)")
        if len(tasks) > 10:
            print(f"  ... and {len(tasks) - 10} more")
    
    # Save detailed results
    output_file = ROOT_DIR / "scripts" / "affected_tasks.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(affected_tasks, f, indent=2, ensure_ascii=False)
    
    print(f"\nDetailed results saved to {output_file}")
    
    # Also save just task IDs (unique only)
    task_ids_file = ROOT_DIR / "scripts" / "affected_task_ids.txt"
    unique_task_ids = sorted(set(task["task_id"] for task in affected_tasks))
    with open(task_ids_file, "w", encoding="utf-8") as f:
        for task_id in unique_task_ids:
            f.write(task_id + "\n")
    
    print(f"Task IDs saved to {task_ids_file} ({len(unique_task_ids)} unique IDs)")

if __name__ == "__main__":
    main()
