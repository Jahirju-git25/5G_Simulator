"""
ML-Based Ping-Pong Detection — DBSCAN Clustering Module
========================================================

Implements density-based spatial clustering for multi-UE ping-pong zone detection.

Algorithm:
  1. Filter UEs by P_pp(i) ≥ θ_ue (typically 0.6)
  2. Apply DBSCAN(eps=60px, min_samples=3) on UE positions
  3. Extract clusters (ignore noise label -1)
  4. Compute weighted centroids using time-decay weights
  5. Validate coverage radius constraint

Reference: Technical Paper §3.3, §3.6, §3.7
"""

import numpy as np
import math
from typing import Dict, List, Tuple, Optional, Set
from collections import defaultdict


class DBSCANClusterer:
    """
    DBSCAN clustering for ping-pong UE zone detection.
    
    Parameters:
      ε (epsilon):    Neighborhood radius in pixels
      MinPts:         Minimum cluster members
      λ:              Time-decay constant (s⁻¹)
      R_anchor:       Maximum allowed anchor coverage radius (pixels)
    """
    
    # DBSCAN parameters
    EPSILON = 60        # pixels (≈ 300 m at 1px=5m)
    MIN_PTS = 2         # minimum cluster members (lowered from 3 for testing)
    
    # Time decay parameters
    LAMBDA = 0.1        # decay constant; half-life ≈ 7 seconds
    
    # Anchor coverage radius
    R_ANCHOR = 60       # pixels (≈ 300 m, the -95 dBm RSRP contour)
    
    def __init__(self, epsilon: float = EPSILON, min_pts: int = MIN_PTS,
                 lambda_decay: float = LAMBDA, r_anchor: float = R_ANCHOR):
        """Initialize DBSCAN clusterer."""
        self.epsilon = epsilon
        self.min_pts = min_pts
        self.lambda_decay = lambda_decay
        self.r_anchor = r_anchor
    
    # ─────────────────────────────────────────────────────────────────────────
    # Main Clustering Method
    # ─────────────────────────────────────────────────────────────────────────
    
    def cluster_ping_pong_ues(self, candidates: List[Dict],
                              current_time: float) -> List[List[str]]:
        """
        Cluster high-P_pp UEs using DBSCAN.
        
        Args:
            candidates: List of UE dicts with:
                {
                    'id': str,
                    'x': float, 'y': float,
                    'p_pp': float,  # ping-pong probability from ML model
                    'last_pp_time': float  # timestamp of last ping-pong event
                }
            current_time: Current simulation time for time-decay calculation
        
        Returns:
            List of clusters, each cluster = list of UE IDs
        """
        if len(candidates) < self.min_pts:
            return []  # Not enough UEs to form a cluster
        
        # Extract positions and UE IDs
        positions = []
        ue_ids = []
        for candidate in candidates:
            positions.append((candidate['x'], candidate['y']))
            ue_ids.append(candidate['id'])
        
        positions = np.array(positions)
        
        # Run DBSCAN
        labels = self._dbscan_fit(positions)
        
        # Extract clusters (ignore noise = -1)
        clusters = defaultdict(list)
        for i, label in enumerate(labels):
            if label >= 0:  # Not noise
                clusters[label].append(ue_ids[i])
        
        return list(clusters.values())
    
    # ─────────────────────────────────────────────────────────────────────────
    # DBSCAN Core Algorithm
    # ─────────────────────────────────────────────────────────────────────────
    
    def _dbscan_fit(self, positions: np.ndarray) -> np.ndarray:
        """
        DBSCAN clustering algorithm.
        
        Args:
            positions: (n, 2) array of UE positions [x, y]
        
        Returns:
            labels: (n,) array of cluster IDs; -1 = noise
        """
        n = len(positions)
        labels = np.full(n, -1, dtype=int)  # -1 = unvisited/noise
        visited = np.zeros(n, dtype=bool)
        cluster_id = 0
        
        for i in range(n):
            if visited[i]:
                continue
            
            visited[i] = True
            
            # Find neighbors
            neighbors = self._get_neighbors(i, positions)
            
            if len(neighbors) < self.min_pts:
                # Point is noise (or border point, which will be claimed by core later)
                labels[i] = -1
                continue
            
            # Start a new cluster
            labels[i] = cluster_id
            
            # Expand cluster (BFS queue)
            queue = neighbors.copy()
            seed_idx = 0
            
            while seed_idx < len(queue):
                q = queue[seed_idx]
                seed_idx += 1
                
                if visited[q]:
                    continue
                
                visited[q] = True
                
                if labels[q] == -1:
                    # Point was noise; now it's part of cluster
                    labels[q] = cluster_id
                
                if labels[q] == -2:
                    # Point already has a label (border point); skip
                    continue
                
                if labels[q] >= 0:
                    # Point is already labeled; skip
                    continue
                
                labels[q] = cluster_id
                
                # Find neighbors of q
                q_neighbors = self._get_neighbors(q, positions)
                
                if len(q_neighbors) >= self.min_pts:
                    # q is a core point; expand
                    queue.extend(q_neighbors)
            
            cluster_id += 1
        
        return labels
    
    def _get_neighbors(self, point_idx: int, positions: np.ndarray) -> List[int]:
        """
        Find all neighbors of a point within epsilon radius.
        
        Args:
            point_idx: Index of query point
            positions: (n, 2) array of positions
        
        Returns:
            List of neighbor indices (including the point itself)
        """
        point = positions[point_idx]
        distances = np.linalg.norm(positions - point, axis=1)
        neighbors = np.where(distances <= self.epsilon)[0].tolist()
        return neighbors
    
    # ─────────────────────────────────────────────────────────────────────────
    # Cluster Analysis
    # ─────────────────────────────────────────────────────────────────────────
    
    def compute_weighted_centroid(self, cluster_ues: List[Dict],
                                  current_time: float) -> Optional[Tuple[float, float]]:
        """
        Compute time-decay weighted centroid of a cluster.
        
        w_i(t) = exp(-λ · Δt_i)
        
        where Δt_i = current_time - t_last_pp(i)
        
        Args:
            cluster_ues: List of UE dicts with 'x', 'y', 'last_pp_time'
            current_time: Current simulation time
        
        Returns:
            (x_centroid, y_centroid) or None if cluster is invalid
        """
        if not cluster_ues:
            return None
        
        total_weight = 0.0
        weighted_x = 0.0
        weighted_y = 0.0
        
        for ue in cluster_ues:
            # Time decay weight
            delta_t = current_time - ue.get('last_pp_time', current_time)
            weight = math.exp(-self.lambda_decay * delta_t)
            
            weighted_x += weight * ue['x']
            weighted_y += weight * ue['y']
            total_weight += weight
        
        if total_weight < 1e-9:
            return None
        
        centroid_x = weighted_x / total_weight
        centroid_y = weighted_y / total_weight
        
        return (centroid_x, centroid_y)
    
    def validate_coverage(self, centroid: Tuple[float, float],
                         cluster_ues: List[Dict]) -> bool:
        """
        Validate that all UEs in cluster are within anchor coverage radius.
        
        max_i d((x_i, y_i), (x*, y*)) ≤ R_anchor
        
        Args:
            centroid: (x*, y*) weighted centroid
            cluster_ues: List of UE dicts with 'x', 'y'
        
        Returns:
            True if coverage constraint is satisfied, False otherwise
        """
        if not cluster_ues or not centroid:
            return False
        
        cx, cy = centroid
        max_distance = 0.0
        
        for ue in cluster_ues:
            distance = math.sqrt((ue['x'] - cx)**2 + (ue['y'] - cy)**2)
            max_distance = max(max_distance, distance)
        
        return max_distance <= self.r_anchor
    
    def get_cluster_stats(self, cluster_ues: List[Dict],
                         centroid: Optional[Tuple[float, float]] = None) -> Dict:
        """
        Compute statistics for a cluster.
        
        Args:
            cluster_ues: List of UE dicts
            centroid: Weighted centroid if available
        
        Returns:
            Dict with cluster stats
        """
        if not cluster_ues:
            return {}
        
        cluster_size = len(cluster_ues)
        
        # Compute spread from centroid
        if centroid:
            distances = [
                math.sqrt((ue['x'] - centroid[0])**2 + (ue['y'] - centroid[1])**2)
                for ue in cluster_ues
            ]
            max_distance = max(distances)
            mean_distance = np.mean(distances)
        else:
            max_distance = 0.0
            mean_distance = 0.0
        
        # Average P_pp
        avg_p_pp = np.mean([ue.get('p_pp', 0.0) for ue in cluster_ues])
        
        return {
            'size': cluster_size,
            'centroid': centroid,
            'max_distance': max_distance,
            'mean_distance': mean_distance,
            'avg_p_pp': avg_p_pp,
            'ue_ids': [ue['id'] for ue in cluster_ues]
        }
    
    # ─────────────────────────────────────────────────────────────────────────
    # Configuration
    # ─────────────────────────────────────────────────────────────────────────
    
    def set_parameters(self, epsilon: Optional[float] = None,
                      min_pts: Optional[int] = None,
                      lambda_decay: Optional[float] = None,
                      r_anchor: Optional[float] = None) -> None:
        """Dynamically adjust DBSCAN parameters."""
        if epsilon is not None:
            self.epsilon = epsilon
        if min_pts is not None:
            self.min_pts = min_pts
        if lambda_decay is not None:
            self.lambda_decay = lambda_decay
        if r_anchor is not None:
            self.r_anchor = r_anchor
    
    def get_parameters(self) -> Dict:
        """Return current parameters."""
        return {
            'epsilon': self.epsilon,
            'min_pts': self.min_pts,
            'lambda_decay': self.lambda_decay,
            'r_anchor': self.r_anchor,
            'time_decay_half_life': math.log(2) / self.lambda_decay,
        }


# ═════════════════════════════════════════════════════════════════════════════
# Example usage
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Initialize clusterer
    clusterer = DBSCANClusterer()
    
    # Test with 3 UEs in close proximity
    current_time = 100.0
    candidates = [
        {'id': 'UE-1', 'x': 100.0, 'y': 100.0, 'p_pp': 0.8, 'last_pp_time': 99.0},
        {'id': 'UE-2', 'x': 110.0, 'y': 105.0, 'p_pp': 0.7, 'last_pp_time': 98.5},
        {'id': 'UE-3', 'x': 105.0, 'y': 115.0, 'p_pp': 0.75, 'last_pp_time': 99.5},
        {'id': 'UE-4', 'x': 500.0, 'y': 500.0, 'p_pp': 0.6, 'last_pp_time': 95.0},  # Outlier
    ]
    
    clusters = clusterer.cluster_ping_pong_ues(candidates, current_time)
    print(f"Found {len(clusters)} cluster(s):")
    for i, cluster in enumerate(clusters):
        print(f"  Cluster {i}: {cluster}")
        
        # Get cluster UEs
        cluster_ues = [c for c in candidates if c['id'] in cluster]
        centroid = clusterer.compute_weighted_centroid(cluster_ues, current_time)
        print(f"    Centroid: {centroid}")
        
        # Validate coverage
        valid = clusterer.validate_coverage(centroid, cluster_ues)
        print(f"    Coverage valid: {valid}")
        
        # Stats
        stats = clusterer.get_cluster_stats(cluster_ues, centroid)
        print(f"    Stats: {stats}")
    
    print("\nClustering Parameters:")
    for key, value in clusterer.get_parameters().items():
        print(f"  {key}: {value}")
