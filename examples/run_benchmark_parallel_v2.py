import os
import sys
import json
import time
import concurrent.futures
from datetime import datetime
from pathlib import Path
import threading
import argparse

# Add project root to path to allow imports
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.insert(0, str(project_root))

from examples.vln_agent import VLNAgent, AgentConfig
from engine.session_manager import session_manager

# Configuration
AGENTS = [
    "gpt-5.2-pro",
    "claude-opus-4-5-20251101-thinking",
    "gemini-3-pro-preview",
    "glm-4.6v",
    "qwen3-vl-235b-a22b-thinking",
    "doubao-seed-1-8-251228-thinking"
]

# We will set LOGS_DIR based on timestamp
LOGS_DIR = project_root / "logs"

# Global state for progress tracking
print_lock = threading.Lock()
progress_lock = threading.Lock()
completed_count = 0
total_tasks_count = 0

def get_tasks(source_dir: Path):
    """Get all vis tasks from source directory."""
    tasks = list(source_dir.rglob("vis_*.json"))
    tasks = sorted(tasks)
    
    if not tasks:
        with print_lock:
            print(f"No tasks found in {source_dir}!")
        return []
    
    return tasks

def run_single_task(agent_name: str, task_path: Path):
    """Run a single task with specific agent."""
    task_id = task_path.stem

    with print_lock:
        print(f"[{agent_name}] Starting task: {task_id}")
    
    # Configure agent
    config = AgentConfig.from_env()
    config.model_name = agent_name
    if not config.benchmark_url:
        config.benchmark_url = "http://localhost:8000"
        
    try:
        # 1. Load Task Data and Modify Description
        try:
            with open(task_path, 'r', encoding='utf-8') as f:
                task_data = json.load(f)
                
            # Construct modified description
            target_name = task_data.get("ground_truth", {}).get("target_name", "")
            agent_refined_route = task_data.get("agent_refined_route", "")
            
            # The core requirement: Navigate to "target_name". "agent_refined_route"
            modified_description = f'Navigate to "{target_name}". "{agent_refined_route}"'
            
            # Update description in task config
            task_data['description'] = modified_description
            
            # Inject into SessionManager
            # This ensures that when agent.run -> create_session is called, 
            # it uses this modified configuration instead of loading from default TASKS_DIR
            session_manager._task_configs[task_id] = task_data
            
            task_max_steps = task_data.get("max_steps", 30)

        except Exception as e:
            with print_lock:
                print(f"[{agent_name}] Failed to prepare task data for {task_id}: {e}")
            return False

        # 2. Run Agent
        agent = VLNAgent(config)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        agent_run_id = f"{agent_name}_{timestamp}"
        
        result = agent.run(
            task_id=task_id,
            max_steps=task_max_steps,
            agent_id=agent_run_id
        )
        
        # 3. Save log
        # Ensure subdirectory exists
        run_logs_dir = LOGS_DIR / f"log_v2_{timestamp.split('_')[0]}" # Group loosely by date or keep flat? 
        # Original script put it in a specific timestamped folder created in main.
        # We will use the global LOGS_DIR set in main.
        
        log_filename = f"{agent_name}_{task_id}_{timestamp}.jsonl"
        log_path = LOGS_DIR / log_filename
        
        with open(log_path, 'w', encoding='utf-8') as f:
            # Write session_start event
            initial_state = {}
            if result["trajectory"]:
                 first_state = result["trajectory"][0].get("state", {})
                 initial_state = first_state
            
            session_start_event = {
                "event": "session_start",
                "session_id": result.get("session_id", agent_run_id),
                "agent_id": agent_name,
                "task_id": task_id,
                "mode": "agent",
                "timestamp": timestamp,
                "initial_state": initial_state,
                "task_description": modified_description # Use the modified description
            }
                
            f.write(json.dumps(session_start_event, ensure_ascii=False) + "\n")
            
            # Write action events
            for step_data in result["trajectory"]:
                raw_action = step_data.get("action", {})
                action_clean = raw_action.copy()
                reason = action_clean.pop("reason", None)
                duration = action_clean.pop("agent_vlm_duration_seconds", None)
                
                action_event = {
                    "event": "action",
                    "session_id": result.get("session_id", agent_run_id),
                    "timestamp": step_data.get("timestamp", ""),
                    "step": step_data.get("step"),
                    "state": step_data.get("state"),
                    "action": action_clean,
                    "available_moves": step_data.get("available_moves"),
                    "image_path": step_data.get("image_path", ""),
                    "agent_type": "agent",
                    "agent_vlm_duration_seconds": duration,
                    "reason": reason
                }
                
                f.write(json.dumps(action_event, ensure_ascii=False) + "\n")
            
        global completed_count
        with progress_lock:
            completed_count += 1
            current_progress = completed_count
            
        with print_lock:
             print(f"[{current_progress}/{total_tasks_count}] [{agent_name}] Finished {task_id}. Log: {log_filename}")
        return True
        
    except Exception as e:
        with print_lock:
            print(f"[{agent_name}] Error running {task_id}: {e}")
            import traceback
            traceback.print_exc()
        return False

def main():
    global total_tasks_count, LOGS_DIR
    
    parser = argparse.ArgumentParser(description="Run benchmark parallel v2 (Custom Description)")
    parser.add_argument("source_dir", type=str, help="Directory containing vis tasks (recursive search)")
    args = parser.parse_args()
    
    source_dir = Path(args.source_dir)
    if not source_dir.exists():
        print(f"Error: Source directory {source_dir} does not exist.")
        return

    # Create timestamped log directory for this run
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOGS_DIR = project_root / "logs" / f"log_v2_{current_time}"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    print("Starting Parallel Benchmark Runner V2...")
    print(f"Source Dir: {source_dir}")
    print(f"Agents: {AGENTS}")
    print(f"Logs will be saved to: {LOGS_DIR}")
    
    tasks = get_tasks(source_dir)
    print(f"Found {len(tasks)} vis tasks.")
    
    if not tasks:
        return
    
    # Create work items
    work_items = []
    for agent in AGENTS:
        for task_path in tasks:
            work_items.append((agent, task_path))
            
    total_tasks_count = len(work_items)
    print(f"Total runs: {total_tasks_count}")
    
    # Run in parallel
    # Increasing workers might help if tasks are IO bound (network), 
    # but be careful with API limits.
    with concurrent.futures.ThreadPoolExecutor(max_workers=120) as executor:
        futures = {
            executor.submit(run_single_task, agent, task) : (agent, task) 
            for agent, task in work_items
        }
        
        for future in concurrent.futures.as_completed(futures):
            pass
                
    print("\nAll tasks completed.")

if __name__ == "__main__":
    main()
