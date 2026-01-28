"""
Evaluate Logs CLI

Usage:
    python -m evaluation.evaluate_logs --files logs/session_1.json logs/session_2.json
    python -m evaluation.evaluate_logs --dir logs/experiment_batch_1
"""

import argparse
import sys
import json
import logging
from pathlib import Path
from typing import List

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluation.evaluator import Evaluator

def main():
    parser = argparse.ArgumentParser(description="Evaluate specific VLM session log files.")
    parser.add_argument("--files", nargs="+", help="List of specific JSON log files to evaluate")
    parser.add_argument("--dir", type=str, help="Directory containing JSON log files to evaluate")
    
    args = parser.parse_args()
    
    if not args.files and not args.dir:
        parser.print_help()
        return

    logging.basicConfig(level=logging.INFO)
    
    # Collect files
    log_files = []
    if args.files:
        for f in args.files:
            path = Path(f)
            if path.exists():
                log_files.append(path)
            else:
                print(f"Warning: File not found: {f}")
    
    if args.dir:
        dir_path = Path(args.dir)
        if dir_path.exists() and dir_path.is_dir():
            # Support both json and jsonl
            log_files.extend(list(dir_path.glob("*.json")))
            log_files.extend(list(dir_path.glob("*.jsonl")))
        else:
            print(f"Warning: Directory not found: {args.dir}")
    
    if not log_files:
        print("No valid log files found.")
        return
        
    print(f"Loading {len(log_files)} logs...")
    
    sessions = []
    for log_file in log_files:
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                if log_file.suffix == '.jsonl':
                    # Parse JSON Lines (could be multiple sessions or one session stream)
                    events = []
                    for line in f:
                        if line.strip():
                            try:
                                event = json.loads(line)
                                events.append(event)
                            except json.JSONDecodeError:
                                pass
                    
                    # Detect if it's a stream of events for one session
                    # If lines have "event" field, it's likely a stream
                    if events and "event" in events[0]:
                        # Reconstruct session from events
                        # We look for "session_end" event which typically contains full summary
                        session_end = next((e for e in events if e.get("event") == "session_end"), None)
                        
                        if session_end:
                            # Use the summary from session_end
                            sessions.append(session_end)
                        else:
                            # Try to reconstruct from last state if incomplete
                            last_event = events[-1]
                            if "session_id" in last_event:
                                # Start with minimal structure
                                reconstructed = {
                                    "session_id": last_event.get("session_id"),
                                    "task_id": last_event.get("task_id", "unknown"),
                                    "status": "incomplete",
                                    "trajectory": [],
                                    "history": [] 
                                }
                                # Rebuild trajectory from steps
                                traj = []
                                history = []
                                for e in events:
                                    if e.get("event") == "session_start":
                                        state = e.get("initial_state", {})
                                        if "pano_id" in state:
                                            traj.append(state["pano_id"])
                                        # Also capture task_id if present
                                        if "task_id" in e:
                                            reconstructed["task_id"] = e["task_id"]
                                            
                                    elif e.get("event") == "action":
                                        state = e.get("state", {})
                                        if "pano_id" in state:
                                            # Avoid duplicates if state hasn't changed
                                            if not traj or traj[-1] != state["pano_id"]:
                                                traj.append(state["pano_id"])
                                        # Collect history for step counting
                                        history.append(e) # e contains 'action' field
                                
                                reconstructed["trajectory"] = traj
                                reconstructed["history"] = history
                                sessions.append(reconstructed)
                    else:
                         # Assume each line is a full session object (bulk export format)
                         sessions.extend(events)
                else:
                    # Parse standard JSON
                    data = json.load(f)
                    # Handle both single session dict and list of sessions
                    if isinstance(data, list):
                        sessions.extend(data)
                    elif isinstance(data, dict):
                        # Check if it's a valid session dict (has minimal fields)
                        if "session_id" in data:
                            sessions.append(data)
        except Exception as e:
            print(f"Error loading {log_file}: {e}")

    if not sessions:
        print("No valid session data found in files.")
        return

    evaluator = Evaluator()
    results = []
    
    print(f"Evaluating {len(sessions)} sessions...")
    
    for session in sessions:
        res = evaluator.evaluate_session(session)
        results.append(res)
    
    # Print Table (Custom implementation)
    headers = ["Session", "Task", "Succ", "SPL", "Move", "Rot", "All", "Len", "Opt Len", "Cov"]
    
    # Prepare data for table
    table_data = []
    for r in results:
        table_data.append([
            r.session_id[:8] + "...",
            r.task_id[:15] + "..." if len(r.task_id) > 15 else r.task_id,
            "✅" if r.success else "❌",
            f"{r.spl:.3f}",
            r.move_steps,
            r.rotate_steps,
            r.total_steps,
            f"{r.trajectory_length:.1f}m",
            f"{r.optimal_distance:.1f}m",
            f"{r.coverage*100:.1f}%"
        ])

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in table_data:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    
    # Add padding
    col_widths = [w + 2 for w in col_widths]
    
    # Print function
    def print_row(row_items):
        line = "|"
        for i, item in enumerate(row_items):
            line += f" {str(item):<{col_widths[i]-2}} |"
        print(line)
    
    def print_sep():
        line = "|"
        for w in col_widths:
            line += "-" * w + "|"
        print(line)
    
    print("\n")
    print_sep()
    print_row(headers)
    print_sep()
    for row in table_data:
        print_row(row)
    print_sep()
    
    # Aggregate
    agg = evaluator.aggregate_results(results)
    print("\nAggregate Results:")
    print(f"  Count: {agg.get('count', 0)}")
    if agg:
        print(f"  Success Rate: {agg.get('success_rate', 0)*100:.1f}%")
        print(f"  Avg SPL: {agg.get('spl', 0):.3f}")
        print(f"  Avg Total Steps: {agg.get('avg_steps', 0):.1f} (Move: {agg.get('avg_move_steps', 0):.1f}, Rot: {agg.get('avg_rotate_steps', 0):.1f})")
        print(f"  Avg Traj Len: {agg.get('avg_trajectory_length', 0):.1f}m")
        print(f"  Avg Coverage: {agg.get('avg_coverage', 0)*100:.1f}%")

if __name__ == "__main__":
    main()
