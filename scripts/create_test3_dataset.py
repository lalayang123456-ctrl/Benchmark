import os
import json
import shutil
import glob
import random
import re
from pathlib import Path

def create_dataset():
    tasks_dir = Path(r"c:\GitHub\StreetView\VLN_BENCHMARK\tasks")
    target_dir = Path(r"c:\GitHub\StreetView\VLN_BENCHMARK\tasks_test3")
    
    # Ensure target directory exists (if not already created)
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # Quotas
    quotas = {
        1: 12,
        2: 12,
        3: 12,
        '4_plus': 3
    }
    
    # Buckets
    buckets = {
        1: [],
        2: [],
        3: [],
        '4_plus': []
    }
    
    # helper regex to extract ID
    # Pattern: vis_0001_...
    id_pattern = re.compile(r"vis_(\d+)_")
    
    print("Scanning tasks...")
    vis_files = list(tasks_dir.glob("vis_*.json"))
    
    # Process files
    processed_count = 0
    valid_count = 0
    
    for vis_path in vis_files:
        processed_count += 1
        try:
            with open(vis_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if data.get("agent_verification") != "YES":
                continue
                
            # Count steps
            refined_route = data.get("agent_refined_route", "")
            if not refined_route:
                steps = 0 # Handle weird case
            else:
                steps = len([s for s in refined_route.split("->") if s.strip()])
                
            # Target Pano
            # In 'vis' files, target info might be in 'ground_truth' or implicit.
            # Assuming 'nav' file has the definitive 'ground_truth' -> 'target_pano_id'
            # But 'vis' file usually has 'target_pano_ids' list.
            target_panos = data.get("target_pano_ids", [])
            if not target_panos:
                # Fallback to ground truth if present
                gt = data.get("ground_truth", {})
                pid = gt.get("target_pano_id")
                if pid:
                    target_panos = [pid]
            
            if not target_panos:
                print(f"Skipping {vis_path.name}: No target pano found")
                continue
                
            target_pano_id = target_panos[0] # Use first one
            
            # Find companion NAV file
            match = id_pattern.match(vis_path.name)
            if not match:
                continue
            task_num_id = match.group(1)
            
            # Look for nav_{task_num_id}_*.json
            # Use glob to find specific match
            nav_candidates = list(tasks_dir.glob(f"nav_{task_num_id}_*.json"))
            if not nav_candidates:
                print(f"Skipping {vis_path.name}: No companion nav file found")
                continue
            
            nav_path = nav_candidates[0] # Take first match
            
            item = {
                'vis_path': vis_path,
                'nav_path': nav_path,
                'target_pano': target_pano_id,
                'steps': steps
            }
            
            if steps == 1:
                buckets[1].append(item)
            elif steps == 2:
                buckets[2].append(item)
            elif steps == 3:
                buckets[3].append(item)
            elif steps >= 4:
                buckets['4_plus'].append(item)
                
            valid_count += 1
            
        except Exception as e:
            print(f"Error processing {vis_path.name}: {e}")
            
    print(f"Processed {processed_count} files. Found {valid_count} valid 'YES' candidates.")
    for k, v in buckets.items():
        print(f"Bucket {k}: {len(v)} candidates")
        
    # Selection
    selected_items = []
    seen_target_panos = set()
    
    # Iterate through quotas
    for k, count_needed in quotas.items():
        candidates = buckets[k]
        random.shuffle(candidates)
        
        selected_for_bucket = 0
        for item in candidates:
            if selected_for_bucket >= count_needed:
                break
                
            if item['target_pano'] in seen_target_panos:
                continue
                
            # Select it
            selected_items.append(item)
            seen_target_panos.add(item['target_pano'])
            selected_for_bucket += 1
            
        if selected_for_bucket < count_needed:
            print(f"Warning: Could not fulfill quota for Steps {k}. Needed {count_needed}, got {selected_for_bucket}")
            
    print(f"\nSelected {len(selected_items)} task pairs.")
    
    # Perform Copy
    copied_count = 0
    for item in selected_items:
        vis_src = item['vis_path']
        nav_src = item['nav_path']
        
        vis_dst = target_dir / vis_src.name
        nav_dst = target_dir / nav_src.name
        
        try:
            shutil.copy2(vis_src, vis_dst)
            shutil.copy2(nav_src, nav_dst)
            copied_count += 2
        except Exception as e:
            print(f"Error copying files for {vis_src.name}: {e}")
            
    print(f"Successfully copied {copied_count} files to {target_dir}")

if __name__ == "__main__":
    create_dataset()
