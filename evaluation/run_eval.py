"""
Run Evaluation CLI

Usage:
    python -m evaluation.run_eval --all
    python -m evaluation.run_eval --session-id <session_id>
"""

import argparse
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluation.evaluator import Evaluator
from engine.session_manager import session_manager

def main():
    parser = argparse.ArgumentParser(description="Run evaluation on VLN sessions.")
    parser.add_argument("--session-id", type=str, help="Specific session ID to evaluate")
    parser.add_argument("--all", action="store_true", help="Evaluate all completed sessions")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file for results")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    # Get sessions
    sessions = []
    if args.session_id:
        session = session_manager.get_session(args.session_id)
        # If not in memory, try DB
        if not session:
             session = session_manager._load_session_from_db(args.session_id)
        if session:
            sessions.append(session)
        else:
            print(f"Session {args.session_id} not found.")
            return
    elif args.all:
        # Load all sessions from DB directly as getting all from memory might miss completed ones
        # For now, let's just use what SessionManager provides or implement a get_all_from_db method
        # But SessionManager.get_all_sessions only parses memory.
        # Let's inspect SessionManager to see if it has get_all.
        # It has get_all_sessions(status). But that's memory only.
        # We need a way to scan DB.
        # For this CLI, let's just use a simple DB scan if needed, or rely on what's available.
        # Ideally SessionManager should support listing all historic sessions.
        # Let's hack it by using get_all_sessions for now, assuming they are loaded or we extend it later.
        # Actually, let's query the DB directly here for robustness.
        from cache.cache_manager import cache_manager
        with cache_manager.get_connection() as conn:
            cursor = conn.execute("SELECT session_id FROM sessions WHERE status = 'completed' OR status = 'stopped' OR status = 'timeout' OR status = 'max_steps' ORDER BY updated_at DESC")
            rows = cursor.fetchall()
            for row in rows:
                s = session_manager._load_session_from_db(row['session_id'])
                if s: 
                    sessions.append(s)
            
            if not sessions:
                print("No completed sessions found in database.")
                return

    else:
        parser.print_help()
        return

    evaluator = Evaluator()
    results = []
    
    print(f"Evaluating {len(sessions)} sessions...")
    
    for session in sessions:
        # Convert to dict if it's a Session object
        sess_dict = session.to_dict()
        res = evaluator.evaluate_session(sess_dict)
        results.append(res)
    
    # Print Table
    table_data = []
    for r in results:
        table_data.append([
            r.session_id[:8] + "...",
            r.task_id,
            "✅" if r.success else "❌",
            f"{r.spl:.3f}",
            r.steps,
            f"{r.trajectory_length:.1f}m",
            f"{r.optimal_distance:.1f}m",
            f"{r.coverage*100:.1f}%"
        ])
    # Print Table (Custom implementation to avoid dependency)
    headers = ["Session", "Task", "Succ", "SPL", "Steps", "Len", "Opt Len", "Cov"]
    
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
        print(f"  Avg Steps: {agg.get('avg_steps', 0):.1f}")
        print(f"  Avg Traj Len: {agg.get('avg_trajectory_length', 0):.1f}m")
        print(f"  Avg Coverage: {agg.get('avg_coverage', 0)*100:.1f}%")

if __name__ == "__main__":
    main()
