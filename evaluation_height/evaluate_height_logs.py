"""
Evaluate Height Estimation Logs (JSONL format)

Evaluates building height estimation tasks.
Success: Agent's answer is within ±20% of the ground truth height.

Usage: python -m evaluation_height.evaluate_height_logs --dir logs/log_20260127_142419
       python -m evaluation_height.evaluate_height_logs --dir logs/log_20260127_142419 --tasks-dir tasks_height
"""

import argparse
import sys
import json
import re
from pathlib import Path
from collections import defaultdict

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Default tasks directories
TASKS_HEIGHT_DIR = Path(__file__).parent.parent / "tasks_height"
TASKS_DIR = Path(__file__).parent.parent / "tasks"

# Evaluation threshold: ±20% tolerance
TOLERANCE_PERCENT = 0.05


def load_task_config(task_id: str, tasks_dir: Path = None):
    """Load task config from file."""
    # Try specified tasks_dir first
    if tasks_dir:
        p = tasks_dir / f"{task_id}.json"
        if p.exists():
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
    
    # Try tasks_height folder
    p1 = TASKS_HEIGHT_DIR / f"{task_id}.json"
    if p1.exists():
        with open(p1, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    # Try general tasks folder
    p2 = TASKS_DIR / f"{task_id}.json"
    if p2.exists():
        with open(p2, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    return None


def extract_number(answer_str: str) -> float:
    """Extract the first number from an answer string."""
    if not answer_str:
        return None
    
    # Try to parse as a direct number first
    try:
        return float(answer_str.strip())
    except ValueError:
        pass
    
    # Use regex to find numbers (handles "25 meters", "~30m", "approximately 25.5", etc.)
    pattern = r'[-+]?\d*\.?\d+'
    matches = re.findall(pattern, str(answer_str))
    
    if matches:
        try:
            return float(matches[0])
        except ValueError:
            pass
    
    return None


def is_within_tolerance(predicted: float, ground_truth: float, tolerance: float = TOLERANCE_PERCENT) -> bool:
    """Check if predicted value is within ±tolerance of ground truth."""
    if ground_truth == 0:
        return predicted == 0
    
    lower_bound = ground_truth * (1 - tolerance)
    upper_bound = ground_truth * (1 + tolerance)
    
    return lower_bound <= predicted <= upper_bound


def evaluate_height_session(log_file: Path, tasks_dir: Path = None) -> dict:
    """Evaluate a single height estimation session from JSONL log."""
    
    result = {
        "file": log_file.name,
        "agent": "Unknown",
        "task_id": "Unknown",
        "ground_truth": None,
        "predicted": None,
        "success": 0,
        "error": None,
        "error_percent": None,
        "steps": 0,
        "reason": None
    }
    
    try:
        events = []
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        
        if not events:
            result["error"] = "No events in log"
            return result
        
        # Extract session info
        start_event = next((e for e in events if e.get("event") == "session_start"), None)
        if start_event:
            result["agent"] = start_event.get("agent_id", "Unknown")
            result["task_id"] = start_event.get("task_id", "Unknown")
        elif events:
            # Fallback: try to extract from first event
            result["agent"] = events[0].get("agent_id", "Unknown")
            result["task_id"] = events[0].get("task_id", "Unknown")
        
        # Find the stop action with the answer
        stop_action = None
        action_count = 0
        for e in events:
            if e.get("event") == "action":
                action_count += 1
                action = e.get("action", {})
                if action.get("type") == "stop":
                    stop_action = action
                    result["reason"] = e.get("reason")
        
        result["steps"] = action_count
        
        if not stop_action:
            result["error"] = "No stop action found in log"
            return result
        
        # Extract predicted answer
        answer_str = stop_action.get("answer", "")
        predicted = extract_number(answer_str)
        
        if predicted is None:
            result["error"] = f"Could not parse answer: {answer_str}"
            return result
        
        result["predicted"] = predicted
        
        # Load task config for ground truth
        task_config = load_task_config(result["task_id"], tasks_dir)
        
        if not task_config:
            result["error"] = f"Task config not found: {result['task_id']}"
            return result
        
        # Get ground truth height
        ground_truth_data = task_config.get("ground_truth", {})
        ground_truth = ground_truth_data.get("height_meters")
        
        # Alternative: check target_building.height
        if ground_truth is None:
            target_building = task_config.get("target_building", {})
            ground_truth = target_building.get("height")
        
        if ground_truth is None:
            result["error"] = "No ground truth height in task config"
            return result
        
        result["ground_truth"] = ground_truth
        
        # Calculate absolute and percentage error
        absolute_error = abs(predicted - ground_truth)
        percentage_error = (absolute_error / ground_truth) * 100 if ground_truth != 0 else float('inf')
        
        result["error"] = round(absolute_error, 2)
        result["error_percent"] = round(percentage_error, 2)
        
        # Success: within ±20%
        if is_within_tolerance(predicted, ground_truth, TOLERANCE_PERCENT):
            result["success"] = 1
        
        return result
        
    except Exception as e:
        result["error"] = str(e)
        return result


def main():
    parser = argparse.ArgumentParser(description="Evaluate height estimation logs")
    parser.add_argument("--dir", type=str, required=True, help="Path to log directory")
    parser.add_argument("--tasks-dir", type=str, default=None, help="Path to tasks directory (default: tasks_height)")
    parser.add_argument("--tolerance", type=float, default=5.0, help="Tolerance percentage (default: 20)")
    args = parser.parse_args()
    
    log_dir = Path(args.dir)
    if not log_dir.exists():
        print(f"Directory not found: {log_dir}")
        return
    
    tasks_dir = Path(args.tasks_dir) if args.tasks_dir else None
    
    global TOLERANCE_PERCENT
    TOLERANCE_PERCENT = args.tolerance / 100.0
    
    # Find height-related log files
    log_files = sorted([f for f in log_dir.glob("*.jsonl") if "height" in f.name.lower()])
    log_files += sorted([f for f in log_dir.glob("*.json") if "height" in f.name.lower()])
    
    if not log_files:
        print(f"No height log files found in {log_dir}")
        # Try all files if no height-specific ones found
        log_files = sorted(log_dir.glob("*.jsonl")) + sorted(log_dir.glob("*.json"))
        print(f"Trying all {len(log_files)} log files...")
    
    print(f"Found {len(log_files)} height logs in {log_dir}")
    print(f"Tolerance: ±{args.tolerance}%")
    print()
    
    # Storage structure: agent -> list of results
    results_by_agent = defaultdict(list)
    all_results = []
    
    for log_file in log_files:
        result = evaluate_height_session(log_file, tasks_dir)
        all_results.append(result)
        results_by_agent[result["agent"]].append(result)
    
    # Print summary table
    print("=" * 120)
    print(f"{'Agent':<45} | {'Count':<6} | {'SR (%)':<7} | {'MAE(m)':<8} | {'MAPE(%)':<8} | {'Correct':<8}")
    print("-" * 120)
    
    for agent in sorted(results_by_agent.keys()):
        items = results_by_agent[agent]
        count = len(items)
        successes = sum(1 for i in items if i["success"] == 1)
        sr = (successes / count) * 100 if count > 0 else 0
        
        # Mean Absolute Error (MAE) - only for valid predictions
        valid_items = [i for i in items if i["ground_truth"] is not None and i["predicted"] is not None]
        mae = sum(abs(i["predicted"] - i["ground_truth"]) for i in valid_items) / len(valid_items) if valid_items else 0
        
        # Mean Absolute Percentage Error (MAPE)
        mape_items = [i for i in valid_items if i["ground_truth"] != 0]
        mape = sum(abs(i["predicted"] - i["ground_truth"]) / i["ground_truth"] * 100 for i in mape_items) / len(mape_items) if mape_items else 0
        
        print(f"{agent:<45} | {count:<6} | {sr:<7.1f} | {mae:<8.2f} | {mape:<8.2f} | {successes}/{count}")
    
    print("-" * 120)
    
    # Overall summary
    total = len(all_results)
    total_success = sum(1 for r in all_results if r["success"] == 1)
    overall_sr = (total_success / total) * 100 if total > 0 else 0
    
    print(f"{'OVERALL':<45} | {total:<6} | {overall_sr:<7.1f} |")
    print("=" * 120)
    
    # Print detailed results
    print("\nDetailed Results:")
    print("-" * 120)
    print(f"{'Task ID':<45} | {'GT(m)':<8} | {'Pred(m)':<8} | {'Err(%)':<8} | {'Success':<8} | {'Agent':<30}")
    print("-" * 120)
    
    for r in sorted(all_results, key=lambda x: x["task_id"]):
        gt = f"{r['ground_truth']:.2f}" if r['ground_truth'] is not None else "N/A"
        pred = f"{r['predicted']:.2f}" if r['predicted'] is not None else "N/A"
        err = f"{r['error_percent']:.1f}" if r['error_percent'] is not None else "N/A"
        success = "Y" if r["success"] == 1 else "N"
        agent_short = r["agent"][:30] if r["agent"] else "Unknown"
        
        # print(f"{r['task_id']:<45} | {gt:<8} | {pred:<8} | {err:<8} | {success:<8} | {agent_short:<30}")
    
    print("-" * 120)
    
    # Print successful task IDs
    print("\nSuccessful Task IDs:")
    print("-" * 60)
    for agent in sorted(results_by_agent.keys()):
        success_ids = [r["task_id"] for r in results_by_agent[agent] if r["success"] == 1]
        if success_ids:
            # Extract ID numbers
            id_nums = []
            for tid in success_ids:
                parts = tid.split('_')
                if len(parts) > 1 and parts[1].isdigit():
                    id_nums.append(parts[1])
                else:
                    id_nums.append(tid)
            id_nums.sort()
            print(f"Agent: {agent}")
            print(f"IDs: {', '.join(id_nums)}")
            print("-" * 30)
    
    # Print failed tasks with reasons
    print("\nFailed Tasks Analysis:")
    print("-" * 120)
    failed = [r for r in all_results if r["success"] == 0 and r["ground_truth"] is not None and r["predicted"] is not None]
    # for r in sorted(failed, key=lambda x: abs(x.get("error_percent", 0) or 0), reverse=True):
    #     print(f"Task: {r['task_id']}")
    #     print(f"  Ground Truth: {r['ground_truth']:.2f}m, Predicted: {r['predicted']:.2f}m, Error: {r['error_percent']:.1f}%")
    #     if r.get("reason"):
    #         print(f"  Reason: {r['reason'][:100]}...")
    #     print()
    
    print("\nMetrics Legend:")
    print(f"  SR: Success Rate (Answer within ±{args.tolerance}% of ground truth)")
    print("  MAE: Mean Absolute Error (meters)")
    print("  MAPE: Mean Absolute Percentage Error")
    print("=" * 120)


if __name__ == "__main__":
    main()
