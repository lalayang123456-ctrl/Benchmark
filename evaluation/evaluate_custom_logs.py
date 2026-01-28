"""
Evaluate Custom Logs (JSON format)
Usage: python -m evaluation.evaluate_custom_logs --dir logs/log_20260125_015609
"""

import argparse
import sys
import json
import statistics
import math
from pathlib import Path
from collections import defaultdict

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cache.metadata_cache import metadata_cache

# Try to match tasks_test first as per runner script
TASKS_TEST_DIR = Path(__file__).parent.parent / "tasks_test"
TASKS_DIR = Path(__file__).parent.parent / "tasks"

SUCCESS_THRESHOLD_METERS = 30.0

def load_task_config(task_id):
    # Try tasks_test first
    p1 = TASKS_TEST_DIR / f"{task_id}.json"
    if p1.exists():
        with open(p1, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    # Try standard tasks folder
    p2 = TASKS_DIR / f"{task_id}.json"
    if p2.exists():
        with open(p2, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    return None

def haversine(lat1, lng1, lat2, lng2):
    R = 6371000  # meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def get_distance(pano1, pano2, local_cache=None):
    if pano1 == pano2:
        return 0.0
    
    # Try local cache first (from logs)
    loc1 = local_cache.get(pano1) if local_cache else None
    loc2 = local_cache.get(pano2) if local_cache else None
    
    # Fallback to DB
    if not loc1:
        loc1 = metadata_cache.get_location(pano1)
    if not loc2:
        loc2 = metadata_cache.get_location(pano2)
        
    if not loc1 or not loc2:
        return float('inf')
    return haversine(loc1[0], loc1[1], loc2[0], loc2[1])

def calculate_trajectory_length(trajectory):
    """Estimate length based on available_moves distances recorded in trajectory steps."""
    total_len = 0.0
    # Trajectory is a list of steps.
    for item in trajectory:
        action = item.get("action", {})
        if action.get("type") == "move":
            move_id = action.get("move_id")
            moves = item.get("available_moves", [])
            chosen_move = next((m for m in moves if m.get("id") == move_id), None)
            if chosen_move:
                dist = chosen_move.get("distance", 0.0)
                if dist:
                    total_len += dist
    return total_len

def evaluate_session(data):
    agent = data.get("agent", "Unknown")
    task_id = data.get("task_id", "Unknown")
    # log_success = data.get("success", False) # Ignored now
    total_steps = data.get("total_steps", 0)
    trajectory = data.get("trajectory", []) # List of steps, need to extract pano ids?
    # Trajectory format in log: [{"step":0, "action":...}, ...]
    # We need the ACTUAL path taken. 
    # vln_agent.py log: trajectory.append({"step":..., "available_moves":...})
    # It does NOT explicitly store the current PanoID in the trajectory step dict in vln_agent.py output!
    # Wait, vln_agent.py:474 trajectory.append(...)
    # It stores observation["available_moves"].
    # BUT the "session_id" relates to a session which usually stores state?
    # NO, we only have the log file.
    # The log file format I reviewed earlier (Step 140) shows "trajectory": [ {step, action, available_moves}...]
    # It DOES NOT store the Pano ID of the location.
    # We can infer it? 
    # Step 0: Start Pano (Need task config start_pano_id)
    # Step 1: Moved to X.
    # We must RECONSTRUCT the path or find the final pano ID.
    # Wait, the `session_end` event in .jsonl usually had it.
    # BUT we disabled .jsonl.
    # And `vln_agent.py` output doesn't seem to verify current Pano ID in the log dump?
    # Let's check api/routes.py or vln_agent.py observation.
    # Observation usually DOES NOT contain Pano ID (to prevent cheating?).
    # BUT `vln_agent.py` uses `session_manager` which tracks state.
    # I should have logged the final Pano ID in the result dict in `vln_agent.py`.
    
    # CRITICAL: `vln_agent.py` returns result dict with `success` from `execute_action`.
    # `ActionExecutor` returns `success` (execution status) and `done`.
    # It DOES NOT return the final Pano ID in the `run()` return value explicitly in the top level.
    # Wait, `vln_agent.py` line 498: `observation = result["observation"]`
    # But `run()` returns matching structure.
    
    # I NEED TO FIX `vln_agent.py` to include `final_pano_id` in the returned result.
    # Otherwise I cannot evaluate based on log unless I infer from move sequence + graph cache.
    # Inferring is possible:
    #   Start at Task.start_pano_id.
    #   Step 1: Action move_id=X. Look at available_moves[X]. It might NOT represent pano_id if not revealed.
    #   But in Step 140 log: `available_moves` has `heading`, `distance`, `direction`. NO PANO ID.
    #   This is by design (agent doesn't see pano ID).
    #   BUT for evaluation we need it.
    
    # SOLUTION: I must modify `vln_agent.py` to return the `final_pano_id` in the summary log.
    # Since the user already has logs generated, those logs are MISSING the Pano ID information needed for spatial evaluation (unless I re-simulate them which is hard/slow).
    # actually, I can re-simulate if I have the full graph.
    
    # WAIT! `logs` directory content check Step 140:
    # "session_id": "..."
    # "trajectory": ...
    # No final_pano_id field.
    
    # HOWEVER, I can modify `vln_agent.py` NOW to include it for FUTURE runs (the user is running "Nav" tasks now).
    # For EXISTING logs... I cannot evaluate them spatially accurately without re-simulation.
    # But wait! I commented out `session_logger` which WOULD have saved it.
    # We might have `session_id` in the log. `session_manager` might still have the session in memory? No, script ends.
    
    # Strategy:
    # 1. Update `vln_agent.py` to return `final_pano_id` in the result.
    # 2. Update `run_benchmark_parallel.py` to save `final_pano_id` to the json.
    # 3. Update `evaluate_custom_logs.py` to use `final_pano_id`.
    
    # Can I recover for existing logs? 
    # Only if I use `action.move_id` + `task.start_pano_id` + `metadata_cache` (Look up links).
    # `metadata_cache.get(pano_id)['links']` gives neighbors. I can simulate the walk.
    
    # Let's implement the simulation in `evaluate_custom_logs.py`!
    # It's robust.
    
    pass

# ... (I will implement the simulation logic below)

def reconstruct_path(trajectory, start_pano_id=None):
    """Reconstruct path using available state or infer from start."""
    path = [start_pano_id]
    current_pano = start_pano_id
    
    # Check if trajectory records state directly (New JSONL format)
    # If the first step has 'state' with 'pano_id', we can just extract the path.
    # Note: Trajectory in reconstructed session is a list of steps.
    # Step 0 usually corresponds to the first action?
    # Actually, the 'initial_state' in session_start should be the first point.
    # But here we pass 'trajectory' list.
    
    # Try simple extraction first
    extracted_path = []
    
    # Check if we have state info in the steps
    has_state_info = False
    for step in trajectory:
        state = step.get("state", {})
        if state and state.get("pano_id"):
            has_state_info = True
            break
            
    if has_state_info:
        # Use logged state
        # But we need to be careful: trajectory records the state AFTER the move?
        # In vln_agent.py: 
        #   action = decide_action()
        #   trajectory.append({state: current_obs_state}) -> This is state BEFORE move?
        #   execute_action()
        # Wait, let's check vln_agent.py again.
        # Line 577: trajectory.append(...) with current observation.
        # Line 587: execute_action(action)
        # So trajectory step records the state *at which the action was taken*.
        # So step[0] state is the start state (or step 1 state).
        # We need the sequence of visited panos.
        # So we collect state['pano_id'] from each step.
        # And finally we need the result of the LAST action?
        # vln_agent.py returns 'trajectory' including the last step's action?
        # No, the loop runs while step < max.
        # Does it record the final state after the last move?
        # The loop records state, does action, then repeats.
        # If it stops, it returns.
        # So we have P0, P1, ... P_last-1.
        # We assume the move success updates the state for the NEXT loop.
        # The log file only contains the "events".
        # If the last event is an action "stop", the state in that event is the final location.
        # If the last event is "move", and it succeeded, the agent ended up at the target of that move.
        # BUT vln_agent.py does NOT log a separate "final state" event unless we look at session_end.
        # However, my previous edit adds pano_id to the OBSERVATION of the result of execute_action...
        # BUT that result is not logged as a separate event in the stream until the next loop?
        # Wait! In run_benchmark_parallel:
        # for step_data in result["trajectory"]: ...
        # The trajectory is collected in the loop.
        # vln_agent.py:582 result = execute_action()
        # If done, returns.
        # It does NOT append the final state to trajectory after the last move if it terminates immediately!
        # Unless the last action was "stop".
        # If last action was "move" and it hit max steps?
        # Then we miss the final location in the trajectory log if we rely only on "state before action".
        
        # However, for "stop", the state in that step is the location where stop was called. So that's valid.
        
        # For "move", we verify if it succeeded.
        # If we trust the log state:
        path = []
        for step in trajectory:
            state = step.get("state", {})
            pid = state.get("pano_id")
            if pid:
                # Avoid sequential duplicates
                if not path or path[-1] != pid:
                    path.append(pid)
                    
        # If the log has explicit start state (processed in loop before), we might have it.
        # Just return the extracted path.
        if path:
             # Ensure start_pano is first if missing?
             if start_pano_id and path[0] != start_pano_id:
                 path.insert(0, start_pano_id)
             return path

    # Fallback to inference (Old logic)
    for step in trajectory:
        action = step.get("action", {})
        if action.get("type") == "move":
            move_id = action.get("move_id")
            
            # 1. Get neighbors from metadata of current_pano
            metadata = metadata_cache.get(current_pano)
            if not metadata:
                break
            links = metadata.get('links', [])
            
            moves_in_log = step.get("available_moves", [])
            chosen_move_log = next((m for m in moves_in_log if m.get("id") == move_id), None)
            
            if chosen_move_log:
                target_heading = chosen_move_log.get("heading")
                best_link = None
                min_diff = 360
                
                for link in links:
                    link_heading = link.get("heading")
                    if link_heading is not None and target_heading is not None:
                        diff = abs(link_heading - target_heading)
                        if diff > 180: diff = 360 - diff
                        if diff < min_diff and diff < 1.0: # Tolerance
                            min_diff = diff
                            best_link = link
                
                if best_link:
                    next_pano = best_link.get("panoId")
                    if next_pano:
                        current_pano = next_pano
                        path.append(current_pano)
    return path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=str, required=True, help="Path to log directory")
    args = parser.parse_args()
    
    log_dir = Path(args.dir)
    if not log_dir.exists():
        print(f"Directory not found: {log_dir}")
        return
        
    log_files = sorted(list(log_dir.glob("*.json"))) + sorted(list(log_dir.glob("*.jsonl")))
    if not log_files:
        print(f"No .json or .jsonl log files found in {log_dir}")
        return
        
    print(f"Found {len(log_files)} logs in {log_dir}")
    
    # Storage structure
    results = defaultdict(lambda: defaultdict(list))
    
    for log_file in log_files:
        try:
            data = {}
            if log_file.suffix == '.jsonl':
                # Parse JSONL
                events = []
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            try:
                                events.append(json.loads(line))
                            except: pass
                
                if not events:
                    continue
                    
                # Reconstruct session from events
                # session_start has static info
                start_event = next((e for e in events if e.get("event") == "session_start"), None)
                if not start_event and events:
                    start_event = events[0] # Fallback
                
                # Check for session end event
                end_event = next((e for e in events if e.get("event") == "session_end"), {})
                
                # Reconstruct trajectory
                # Trajectory in log format: action events
                traj = []
                for e in events:
                    if e.get("event") == "action":
                        # We need to construct a step-like object
                        # run_benchmark_parallel.py writes cleaner action events where action is flattened or cleaned.
                        # But we need to match the structure expected by evaluate_custom_logs
                        
                        # We need 'action' object, 'available_moves'
                        # For path reconstruction, we needpano_id.
                        # My fix in vln_agent.py puts 'state' with 'pano_id' in the log event.
                        
                        step_obj = {
                            "step": e.get("step"),
                            "action": e.get("action", {}),
                            "available_moves": e.get("available_moves", []),
                            "state": e.get("state", {}) 
                        }
                        traj.append(step_obj)
                
                data = {
                    "agent": start_event.get("agent_id", "Unknown"),
                    "task_id": start_event.get("task_id", "Unknown"),
                    "total_steps": len(traj),
                    "trajectory": traj,
                    # If we have explicit success in end event
                    "success": end_event.get("success", False) 
                }
            else:
                with open(log_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
            agent = data.get("agent", "Unknown")
            task_id = data.get("task_id", "Unknown")
            total_steps = data.get("total_steps", 0)
            trajectory = data.get("trajectory", [])
            
            # Determine task type
            if "vis_" in task_id:
                task_type = "vis"
            elif "nav_" in task_id:
                task_type = "nav"
            else:
                task_type = "other"
            
            # Load task config
            task_config = load_task_config(task_id)
            
            # Calculate REAL Success
            real_success = False
            optimal_dist = 0.0
            error_margin = float('inf')
            
            if task_config:
                start_pano = task_config.get("start_pano_id") or task_config.get("spawn_point")
                target_panos = task_config.get("target_pano_ids", [])
                
                # Build local coordinate cache from log
                local_coords = {}
                for step in trajectory:
                    state = step.get("state", {})
                    pid = state.get("pano_id")
                    lat = state.get("lat")
                    lng = state.get("lng")
                    if pid and lat is not None and lng is not None:
                        local_coords[pid] = (lat, lng)

                # Reconstruct path to find final position
                # We can proceed even if start_pano is missing if the log has the path
                path = reconstruct_path(trajectory, start_pano)
                
                final_pano = None
                if path:
                     final_pano = path[-1]
                elif start_pano:
                     final_pano = start_pano
                     
                if final_pano and target_panos:
                    # Check distance to targets
                    for t_id in target_panos:
                        d = get_distance(final_pano, t_id, local_coords)
                        if d < error_margin:
                            error_margin = d
                    
                    if error_margin <= SUCCESS_THRESHOLD_METERS:
                        real_success = True
                
                optimal_dist = task_config.get("ground_truth", {}).get("optimal_distance_meters", 0.0)

            # Derived Metrics
            traj_len = calculate_trajectory_length(trajectory)
            
            # SPL
            spl = 0.0
            if real_success and optimal_dist > 0:
                denom = max(traj_len, optimal_dist)
                spl = optimal_dist / denom
            elif real_success and optimal_dist == 0:
                 spl = 1.0 # Optimal 0 means start=end?
            
            results[agent][task_type].append({
                "success": 1 if real_success else 0,
                "steps": total_steps,
                "length": traj_len,
                "spl": spl,
                "optimal": optimal_dist,
                "error": error_margin if error_margin != float('inf') else -1,
                "task_id": task_id
            })
            
        except Exception as e:
            print(f"Error reading {log_file.name}: {e}")
            
    # Print Table
    print("\n" + "="*100)
    print(f"{'Agent':<35} | {'Type':<5} | {'Count':<5} | {'SR (%)':<6} | {'SPL':<5} | {'Steps':<5} | {'Len(m)':<6} | {'Err(m)':<6}")
    print("-" * 100)
    
    for agent in sorted(results.keys()):
        for t_type in sorted(results[agent].keys()):
            items = results[agent][t_type]
            
            count = len(items)
            sr = (sum(i["success"] for i in items) / count) * 100
            avg_spl = sum(i["spl"] for i in items) / count
            avg_steps = sum(i["steps"] for i in items) / count
            avg_len = sum(i["length"] for i in items) / count
            avg_err = sum(i["error"] for i in items if i["error"] >= 0)
            avg_err = avg_err / len([i for i in items if i["error"] >= 0]) if [i for i in items if i["error"] >= 0] else -1
            
            print(f"{agent:<35} | {t_type:<5} | {count:<5} | {sr:<6.1f} | {avg_spl:<5.3f} | {avg_steps:<5.1f} | {avg_len:<6.1f} | {avg_err:<6.1f}")
            
    print("-" * 100)
    
    # Print Successful Task IDs
    print("\nCorrect Task IDs (Success):")
    print("-" * 100)
    for agent in sorted(results.keys()):
        for t_type in sorted(results[agent].keys()):
            items = results[agent][t_type]
            success_ids = []
            for i in items:
                if i["success"] == 1:
                    tid = i.get("task_id", "")
                    # Extract ID number (e.g. nav_0001_... -> 0001)
                    parts = tid.split('_')
                    if len(parts) > 1 and parts[1].isdigit():
                        success_ids.append(parts[1])
                    else:
                        success_ids.append(tid) # Fallback
            
            if success_ids:
                # Sort for better readability
                success_ids.sort()
                print(f"Agent: {agent} | Type: {t_type}")
                print(f"IDs: {', '.join(success_ids)}")
                print("-" * 50)

    print("Metrics Legend:")
    print(f"  SR: Success Rate (Final Distance < {SUCCESS_THRESHOLD_METERS}m)")
    print("  SPL: Success weighted by Path Length")
    print("  Len: Estimated Trajectory Length")
    print("  Err: Average Distance to Target (Error Margin)")
    print("=" * 100 + "\n")

if __name__ == "__main__":
    main()
