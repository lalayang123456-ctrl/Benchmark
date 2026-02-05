import argparse
import json
import math
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
TASKS_DIR = Path(__file__).parent.parent / "tasks_perception"
ANGLE_TOLERANCE_DEG = 30.0
DISTANCE_TOLERANCE_PCT = 0.15

def get_ground_truth(task_id: str) -> Optional[Dict]:
    """Load ground truth from the task file."""
    task_path = TASKS_DIR / f"{task_id}.json"
    if not task_path.exists():
        logger.warning(f"Task file not found: {task_path}")
        return None
    
    try:
        with open(task_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading task file {task_path}: {e}")
        return None

def parse_answer(answer_str: Union[str, int, float]) -> Optional[float]:7
    """Parse the answer string into a float."""
    if isinstance(answer_str, (int, float)):
        return float(answer_str)
    
    if not answer_str:
        return None
        
    # Remove non-numeric characters except dot and minus (simple cleanup)
    # This handles cases like "35m", "approx 35", "35 degrees"
    cleaned = ""
    for char in str(answer_str):
        if char.isdigit() or char in ['.', '-']:
            cleaned += char
        elif cleaned and char == ' ': # Allow leading number then space then units
            break
            
    try:
        return float(cleaned)
    except ValueError:
        return None

def calculate_angular_error(pred: float, truth: float) -> float:
    """Calculate the smallest difference between two angles (0-360)."""
    diff = abs(pred - truth) % 360
    return min(diff, 360 - diff)

def haversine(lat1, lon1, lat2, lon2):
    """Calculate the great circle distance in meters between two points."""
    R = 6371000  # radius of Earth in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2) 
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1) 
    
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R*c

def calculate_trajectory_metrics(events: List[Dict]) -> Tuple[int, float]:
    """Calculate steps and trajectory length from events."""
    steps = 0
    length = 0.0
    trajectory_points = []
    
    # Extract points from actions
    # events list might contain session_start (initial_state) and actions
    
    # Search for initial state
    for e in events:
        if e.get("event") == "session_start":
            state = e.get("initial_state", {})
            if "lat" in state and "lng" in state:
                trajectory_points.append((state["lat"], state["lng"]))
            break
            
    for e in events:
        if e.get("event") == "action":
            steps += 1
            state = e.get("state", {})
            if "lat" in state and "lng" in state:
                # check if different from last
                pt = (state["lat"], state["lng"])
                if not trajectory_points or trajectory_points[-1] != pt:
                    trajectory_points.append(pt)
                    
    # Calculate length
    for i in range(len(trajectory_points) - 1):
        p1 = trajectory_points[i]
        p2 = trajectory_points[i+1]
        length += haversine(p1[0], p1[1], p2[0], p2[1])
        
    return steps, length

def evaluate_session(session: Dict) -> Optional[Dict]:
    """Evaluate a single session."""
    task_id = session.get("task_id")
    if not task_id:
        return None

    ground_truth_data = get_ground_truth(task_id)
    if not ground_truth_data:
        return None
    
    task_type = ground_truth_data.get("task_type")
    ground_truth_values = ground_truth_data.get("ground_truth", {})
    
    # Extract events
    events = session.get("events", [])
    if not events and "history" in session:
         events = session["history"]
         
    # Calculate basic stats
    steps, length = calculate_trajectory_metrics(events)
    
    # Extract prediction
    answer = None
    stop_action = None
    for event in reversed(events):
        if event.get("event") == "action":
            action = event.get("action", {})
            if action.get("type") == "stop":
                stop_action = action
                break
    
    if stop_action:
        answer = parse_answer(stop_action.get("answer"))
    
    base_result = {
        "task_id": task_id,
        "task_type": task_type,
        "steps": steps,
        "length": length,
        "spl": 0.0, # Default
        "success": False
    }

    if answer is None:
        base_result["error_reason"] = "no_answer"
        base_result["prediction"] = None
        # Do not set error_val so it is not included in averages
        return base_result

    base_result["prediction"] = answer

    if "angle" in task_type:
        target_bearing = ground_truth_values.get("bearing_a_to_b_deg")
        if target_bearing is None:
             return None
             
        error = calculate_angular_error(answer, target_bearing)
        base_result["error_val"] = error
        
        if error <= ANGLE_TOLERANCE_DEG:
            base_result["success"] = True
            
    elif "distance" in task_type:
        target_dist = ground_truth_values.get("distance_between_pois_m")
        if target_dist is None:
             return None
             
        if target_dist == 0:
            error_pct = 0 if answer == 0 else float('inf')
        else:
            error_pct = abs(answer - target_dist) / target_dist
            
        base_result["error"] = error_pct # Keep for internal logic if needed
        base_result["error_val"] = abs(answer - target_dist) # Error in Meters for the table
        
        if error_pct <= DISTANCE_TOLERANCE_PCT:
             base_result["success"] = True
             
    else:
        return None
        
    return base_result

def load_sessions(files: List[Path]) -> List[Dict]:
    """Load sessions from file list (supports jsonl)."""
    sessions = []
    for log_file in files:
        if log_file.suffix == '.jsonl':
            # Accumulate events for a session
            current_session_events = []
            session_meta = {}
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                            
                            # Grab metadata from session_start
                            if event.get("event") == "session_start":
                                session_meta = event
                                current_session_events = [] # Start new
                                
                            current_session_events.append(event)
                            
                        except json.JSONDecodeError:
                            continue
                    
                # End of file, package the session
                # If we have multiple sessions in one file this logic isn't perfect
                # But typically one file = one session flow in these logs, 
                # or we just rely on the 'session_meta' and 'events' list.
                
                # Check if we have valid data
                if session_meta:
                    full_session = session_meta.copy()
                    full_session["events"] = current_session_events
                    sessions.append(full_session)
                elif current_session_events:
                     # Attempt to reconstruct metadata from first event if missing explicit start
                     first = current_session_events[0]
                     full_session = {
                         "task_id": first.get("task_id"),
                         "session_id": first.get("session_id"),
                         "events": current_session_events
                     }
                     if full_session["task_id"]:
                         sessions.append(full_session)
                         
            except Exception as e:
                logger.error(f"Error reading {log_file}: {e}")
        elif log_file.suffix == '.json':
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        sessions.extend(data)
                    elif isinstance(data, dict):
                         sessions.append(data)
            except Exception as e:
                logger.error(f"Error reading {log_file}: {e}")
                
    return sessions

def main():
    parser = argparse.ArgumentParser(description="Evaluate perception tasks.")
    parser.add_argument("--files", nargs="+", help="Log files")
    parser.add_argument("--dir", type=str, help="Log directory")
    
    args = parser.parse_args()
    
    files = []
    if args.files:
        for f in args.files:
            p = Path(f)
            if p.is_dir():
                files.extend(list(p.glob("*.jsonl")))
                files.extend(list(p.glob("*.json")))
            else:
                files.append(p)
    if args.dir:
        d = Path(args.dir)
        files.extend(list(d.glob("*.jsonl")))
        files.extend(list(d.glob("*.json"))) # Support .json too
        
    if not files:
        print("No files found.")
        return

    sessions = load_sessions(files)
    print(f"Loaded {len(sessions)} sessions.")

    # Results aggregation by agent and type
    agent_results = {} # {agent_id: {type: [results]}}

    for session in sessions:
        res = evaluate_session(session)
        if res:
            agent_id = session.get("agent_id", "unknown")
            task_type = "angle" if "angle" in res["task_type"] else ("dis" if "distance" in res["task_type"] else "other")
            
            if agent_id not in agent_results:
                agent_results[agent_id] = {}
            if task_type not in agent_results[agent_id]:
                agent_results[agent_id][task_type] = []
                
            agent_results[agent_id][task_type].append(res)
    
    # Print Table
    print("\n" + "="*110)
    headers = ["Agent", "Type", "Count", "SR (%)", "SPL", "Steps", "Len(m)", "Err"]
    # Adjust spacing
    # Agent: 30, Type: 8, Count: 6, SR: 8, SPL: 6, Steps: 8, Len: 8, Err: 10
    header_fmt = "{:<35} | {:<5} | {:<5} | {:<7} | {:<5} | {:<6} | {:<7} | {:<7}"
    print(header_fmt.format(*headers))
    print(header_fmt.format(*["-"*len(h) for h in headers])) # Not exact line but close enough

    # Sort agents
    sorted_agents = sorted(agent_results.keys())
    
    for agent in sorted_agents:
        for task_type in sorted(agent_results[agent].keys()):
            res_list = agent_results[agent][task_type]
            count = len(res_list)
            success_count = sum(1 for r in res_list if r["success"])
            sr = (success_count / count) * 100
            
            # SPL - For perception, optimal path length is not clearly defined or relevant for "answer" accuracy usually.
            # But if we strictly follow the format:
            spl = sum(r.get("spl", 0) for r in res_list) / count
            
            avg_steps = sum(r.get("steps", 0) for r in res_list) / count
            avg_len = sum(r.get("length", 0) for r in res_list) / count
            
            # Error
            # For angle: Err is degrees
            # For dis: Err is meters (abs_error)
            valid_errors = [r["error_val"] for r in res_list if "error_val" in r]
            avg_err_str = f"{sum(valid_errors) / len(valid_errors):.1f}" if valid_errors else "-"
            
            print(header_fmt.format(
                agent, 
                task_type, 
                str(count), 
                f"{sr:.1f}", 
                f"{spl:.3f}", 
                f"{avg_steps:.1f}", 
                f"{avg_len:.1f}", 
                avg_err_str
            ))
            
    print("-" * 110)
    print("\n")

if __name__ == "__main__":
    main()
