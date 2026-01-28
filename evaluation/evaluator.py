"""
VLN Benchmark Evaluator

Calculates standard metrics for Visual Language Navigation tasks:
- Success Rate (SR)
- Success weighted by Path Length (SPL)
- Trajectory Length (TL)
- Steps Taken
- Search Coverage (for Exploration tasks)
"""

import math
import json
import logging
from typing import Dict, List, Optional, Tuple, Any, Set
from pathlib import Path
from dataclasses import dataclass

# Add parent directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from cache.metadata_cache import metadata_cache
from config.settings import TASKS_DIR

logger = logging.getLogger(__name__)

@dataclass
class EvaluationResult:
    """Result of evaluating a single session."""
    session_id: str
    task_id: str
    success: int  # 0 or 1
    spl: float
    trajectory_length: float
    steps: int
    move_steps: int
    rotate_steps: int
    total_steps: int
    optimal_distance: float
    error_margin: float  # Distance to target at end
    coverage: float  # 0.0 to 1.0 (for exploration)
    
    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "success": self.success,
            "spl": round(self.spl, 3),
            "trajectory_length": round(self.trajectory_length, 2),
            "steps": self.steps,
            "move_steps": self.move_steps,
            "rotate_steps": self.rotate_steps,
            "total_steps": self.total_steps,
            "optimal_distance": round(self.optimal_distance, 2),
            "error_margin": round(self.error_margin, 2),
            "coverage": round(self.coverage, 3)
        }

class Evaluator:
    """Calculates metrics for VLN sessions."""
    
    def __init__(self, success_threshold: float = 50.0):
        """
        Args:
            success_threshold: Distance in meters to consider 'arrival' (default 50m)
        """
        self.success_threshold = success_threshold
        self.geofence_configs = {}
        self._load_geofence_configs()
    
    def _load_geofence_configs(self):
        """Load geofence/whitelist configurations."""
        config_path = Path(__file__).parent.parent / "config" / "geofence_config.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    self.geofence_configs = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load geofence config: {e}")

    def evaluate_session(self, session: Dict) -> EvaluationResult:
        """
        Evaluate a single session dictionary.
        
        Args:
            session: Session dictionary (from Session.to_dict())
            
        Returns:
            EvaluationResult object
        """
        # Extract basic info
        session_id = session.get("session_id", "unknown")
        task_id = session.get("task_id", "unknown")
        trajectory = session.get("trajectory", [])
        
        # Calculate Steps Breakdown
        # We need access to the raw actions/events to count rotations vs moves.
        # If 'total_steps' is in session (from standard log), use it as base but we need breakdown.
        # If we have 'history' or 'actions' list in session, we use that.
        # Standard Session object doesn't always store full history in 'to_dict' unless we added it.
        # But let's check what's available.
        
        move_steps = 0
        rotate_steps = 0
        
        # Method 1: Infer from trajectory (Only moves)
        # This is what we had: len(trajectory) - 1. But this misses rotations.
        move_steps_traj = max(0, len(trajectory) - 1)
        
        # Method 2: Check for explicit 'history' or 'events' list if passed in session dict
        # (evaluate_logs logic might pass full object)
        history = session.get("history", [])
        events = session.get("events", []) # Custom field we might add if raw log
        
        if history:
            for item in history:
                action = item.get("action", {})
                a_type = action.get("type", "")
                if a_type == "move":
                    move_steps += 1
                elif a_type == "rotation":
                    rotate_steps += 1
        elif "total_steps" in session:
             # Fallback if we only have summary
             total = session["total_steps"]
             # We know moves approx = len(trajectory) - 1
             # So rotations approx = total - moves
             # This assumes total_steps count includes both? Yes standard logic usually does.
             move_steps = move_steps_traj
             rotate_steps = max(0, total - move_steps)
        else:
             # Worst case fallback
             move_steps = move_steps_traj
             rotate_steps = 0
             
        total_steps = move_steps + rotate_steps
        
        # Load task config for ground truth
        task_config = self._load_task_config(task_id) or session.get("task_config", {})
        
        ground_truth = task_config.get("ground_truth", {})
        target_panos = task_config.get("target_pano_ids", [])
        geofence_name = task_config.get("geofence")
        
        # 1. Navigation Error (Error Margin)
        final_pano_id = trajectory[-1] if trajectory else None
        min_dist_to_target = float("inf")
        
        if final_pano_id and target_panos:
            for target_id in target_panos:
                dist = self._get_pano_distance(final_pano_id, target_id)
                if dist is not None:
                    min_dist_to_target = min(min_dist_to_target, dist)
        
        if min_dist_to_target == float("inf"):
             min_dist_to_target = 0.0 # Should probably handle this better, but 0 implies success if unknown? No, assume fail. 
             # Actually if we can't calculate distance, we can't judge success.
             # Let's assume infinite if no target panos found.
             if not target_panos:
                 # Exploration task without fixed target? Or just assume 0 error?
                 # If ground_truth.target_pano_id is None (exploration negative), target panos is empty.
                 if ground_truth.get("answer") == "no":
                     min_dist_to_target = 0.0 # Correctly identified no target?
                 else:
                     min_dist_to_target = 9999.0
             else:
                 min_dist_to_target = 9999.0

        # 2. Success
        # Condition: Distance < Threshold AND (Explicit Stop OR reached_target logic)
        # For now, we use distance threshold.
        # Note: If it's a "No target" exploration task, success is agent answering "no" or stopping?
        # Assuming standard navigation or "find target" where target exists:
        success = 1 if min_dist_to_target <= self.success_threshold else 0
        
        # Special case for Exploration Negative (target doesn't exist)
        # If ground_truth.answer is "no", success depends on agent answer (if we had it)
        # For this implementation, we focus on spatial success.
        
        # 3. Trajectory Length (Actual Path Length)
        traj_length = 0.0
        for i in range(len(trajectory) - 1):
            dist = self._get_pano_distance(trajectory[i], trajectory[i+1])
            if dist:
                traj_length += dist
        
        # 4. SPL
        # SPL = Success * (Optimal_Dist / max(Actual_Dist, Optimal_Dist))
        optimal_dist = ground_truth.get("optimal_distance_meters", 0.0)
        
        spl = 0.0
        if success:
            if optimal_dist <= 0:
                # If no optimal distance known, fallback to Euclidean from start to target
                # (Evaluator doing its own "optimal" calc if missing)
                start_pano = trajectory[0] if trajectory else None
                if start_pano and target_panos:
                    optimal_dist = self._get_pano_distance(start_pano, target_panos[0]) or 0.0
            
            denom = max(traj_length, optimal_dist)
            if denom > 0:
                spl = float(success) * (optimal_dist / denom)
            else:
                spl = float(success) # Start = End and dist = 0
                
        # 5. Coverage
        coverage = 0.0
        if geofence_name and geofence_name in self.geofence_configs:
            whitelist = set(self.geofence_configs[geofence_name])
            if whitelist:
                visited_unique = set(trajectory)
                visited_in_whitelist = visited_unique.intersection(whitelist)
                coverage = len(visited_in_whitelist) / len(whitelist)
        
        return EvaluationResult(
            session_id=session_id,
            task_id=task_id,
            success=success,
            spl=spl,
            trajectory_length=traj_length,
            steps=move_steps, # Keep backward compatibility or just use move_steps
            move_steps=move_steps,
            rotate_steps=rotate_steps,
            total_steps=total_steps,
            optimal_distance=optimal_dist,
            error_margin=min_dist_to_target,
            coverage=coverage
        )

    def _get_pano_distance(self, pano1: str, pano2: str) -> Optional[float]:
        """Calculate Haversine distance between two panoramas via metadata."""
        if pano1 == pano2:
            return 0.0
            
        loc1 = metadata_cache.get_location(pano1)
        loc2 = metadata_cache.get_location(pano2)
        
        if not loc1 or not loc2:
            return None
            
        return self._haversine(loc1[0], loc1[1], loc2[0], loc2[1])

    def _haversine(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Haversine formula for distance in meters."""
        R = 6371000  # Earth radius in meters
        
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lng2 - lng1)
        
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c

    def _load_task_config(self, task_id: str) -> Optional[Dict]:
        """Load task config from file."""
        task_path = TASKS_DIR / f"{task_id}.json"
        if not task_path.exists():
            return None
        try:
            with open(task_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return None
            
    def aggregate_results(self, results: List[EvaluationResult]) -> Dict[str, float]:
        """Calculate average metrics for a list of results."""
        if not results:
            return {}
            
        count = len(results)
        return {
            "success_rate": sum(r.success for r in results) / count,
            "spl": sum(r.spl for r in results) / count,
            "avg_steps": sum(r.total_steps for r in results) / count,
            "avg_move_steps": sum(r.move_steps for r in results) / count,
            "avg_rotate_steps": sum(r.rotate_steps for r in results) / count,
            "avg_trajectory_length": sum(r.trajectory_length for r in results) / count,
            "avg_error_margin": sum(r.error_margin for r in results) / count,
            "avg_coverage": sum(r.coverage for r in results) / count,
            "count": count
        }
