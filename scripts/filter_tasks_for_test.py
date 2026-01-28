
import json
import os
import shutil
from pathlib import Path

def filter_and_copy_tasks():
    source_dir = Path(r"c:\GitHub\StreetView\VLN_BENCHMARK\tasks")
    target_dir = Path(r"c:\GitHub\StreetView\VLN_BENCHMARK\tasks_test_2")
    
    # Create target directory if it doesn't exist
    target_dir.mkdir(parents=True, exist_ok=True)
    
    vis_files = list(source_dir.glob("vis_*.json"))
    
    selected_tasks = []
    seen_geofences = set()
    
    print(f"Scanning {len(vis_files)} files...")
    
    for vis_path in vis_files:
        if len(selected_tasks) >= 20:
            break
            
        try:
            with open(vis_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Check verification status
            verification = data.get("agent_verification", "").upper().strip()
            if verification != "YES":
                continue
                
            # Check refined route complexity
            refined_route = data.get("agent_refined_route", "")
            if refined_route.count("->") > 1:
                continue
                
            # Check unique geofence
            geofence = data.get("geofence")
            if not geofence or geofence in seen_geofences:
                continue
                
            # Locate corresponding nav task
            nav_task_id = data.get("task_id")
            if not nav_task_id:
                print(f"Warning: No task_id in {vis_path.name}")
                continue
                
            nav_filename = f"{nav_task_id}.json"
            nav_path = source_dir / nav_filename
            
            if not nav_path.exists():
                # Try finding it in tasks_test potentially? Or just report missing
                # Based on user request, we assume it's available.
                # Let's check adjacent folders if not found, 
                # but for now assume it's in the same folder.
                print(f"Warning: Nav task {nav_filename} not found for {vis_path.name}")
                continue
                
            # If all checks pass
            seen_geofences.add(geofence)
            selected_tasks.append((vis_path, nav_path))
            
        except Exception as e:
            print(f"Error processing {vis_path.name}: {e}")
            continue

    print(f"Found {len(selected_tasks)} matching tasks.")
    
    if len(selected_tasks) < 20:
        print("Warning: Only found fewer than 20 tasks meeting the criteria.")
    
    for vis_src, nav_src in selected_tasks:
        print(f"Copying {vis_src.name} and {nav_src.name}")
        shutil.copy2(vis_src, target_dir / vis_src.name)
        shutil.copy2(nav_src, target_dir / nav_src.name)
        
    print("Done.")

if __name__ == "__main__":
    filter_and_copy_tasks()
