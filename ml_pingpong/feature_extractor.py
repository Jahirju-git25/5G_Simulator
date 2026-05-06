"""
ML-Based Ping-Pong Detection — Feature Extraction Module
=========================================================

Extracts 5-dimensional feature vectors from UE handover history and RRC measurements.
These features feed into the ML model for P_pp (ping-pong probability) prediction.

Features extracted:
  1. f_HO:      Handover frequency (HOs/s)
  2. σ²_RSRP:   RSRP variance (dBm²)
  3. R_rev:     Cell revisit ratio
  4. D_flip:    Direction flip count
  5. Osc:       Oscillation score (A→B→A rate)

Reference: Technical Paper §4.1, §3.1, §3.2
"""

import math
import numpy as np
from collections import deque
from typing import Dict, List, Tuple, Optional


class FeatureExtractor:
    """
    Extracts multi-dimensional features from HO events and radio measurements.
    
    Window configuration:
    - T_w = 10 seconds (sliding window for feature extraction)
    - Evaluation interval = 0.5 seconds
    """
    
    T_W = 10.0          # 10-second sliding window for feature extraction
    EVAL_INTERVAL = 0.5 # Evaluate every 0.5 seconds
    
    def __init__(self, normalize=True):
        """
        Initialize feature extractor.
        
        Args:
            normalize: If True, normalize features to [0, 1] range
        """
        self.normalize = normalize
        
        # Network-wide statistics for normalization
        self.f_HO_max = 2.0        # max HOs/s = 2 (high mobility)
        self.rsrp_var_max = 100.0  # max RSRP variance = 100 dBm²
        self.d_flip_max = 10.0     # max direction flips per window
        
        # Per-UE historical data (will be populated externally)
        self.ue_ho_windows: Dict[str, deque] = {}  # {ue_id: deque of HO events}
        self.ue_rsrp_windows: Dict[str, deque] = {} # {ue_id: deque of RSRP values}
        self.ue_positions: Dict[str, Tuple[float, float]] = {}  # {ue_id: (x, y)}
        self.ue_last_rsrp: Dict[str, float] = {}    # {ue_id: last RSRP}
    
    # ─────────────────────────────────────────────────────────────────────────
    # Feature Computation
    # ─────────────────────────────────────────────────────────────────────────
    
    def extract_features_batch(self, ue_data: Dict) -> np.ndarray:
        """
        Extract 5-feature vector for a UE from event stream.
        
        Args:
            ue_data: {
                'id': str,
                'ho_history': list of {'target': gnb_id, 'rsrp': float, 'timestamp': float},
                'rsrp_samples': list of float,
                'x': float, 'y': float,
                'current_time': float
            }
        
        Returns:
            np.array([f_HO_norm, rsrp_var_norm, revisit_ratio, flip_norm, osc_score])
        """
        ue_id = ue_data.get('id', 'UE-unknown')
        ho_history = ue_data.get('ho_history', [])
        rsrp_samples = ue_data.get('rsrp_samples', [])
        current_time = ue_data.get('current_time', 0.0)
        x, y = ue_data.get('x', 0), ue_data.get('y', 0)
        
        # Ensure we have position tracking
        self.ue_positions[ue_id] = (x, y)
        
        if len(ho_history) < 2:
            return np.zeros(5)
        
        # Feature 1: HO Frequency
        f_HO_norm = self._compute_ho_frequency(ho_history, current_time)
        
        # Feature 2: RSRP Variance
        rsrp_var_norm = self._compute_rsrp_variance(rsrp_samples)
        
        # Feature 3: Cell Revisit Ratio
        revisit_ratio = self._compute_cell_revisit_ratio(ho_history)
        
        # Feature 4: Direction Flip Count
        flip_norm = self._compute_direction_flips(ho_history, ue_id)
        
        # Feature 5: Oscillation Score
        osc_score = self._compute_oscillation_score(ho_history)
        
        features = np.array([
            f_HO_norm,
            rsrp_var_norm,
            revisit_ratio,
            flip_norm,
            osc_score
        ])
        
        return features
    
    # ─────────────────────────────────────────────────────────────────────────
    # Individual Feature Calculations
    # ─────────────────────────────────────────────────────────────────────────
    
    def _compute_ho_frequency(self, ho_history: List[Dict], current_time: float) -> float:
        """
        Feature 1: f_HO(i) = count(HOs in T_w) / T_w [normalized to [0, 1]]
        
        HO frequency indicates how often the UE is handovering.
        High frequency in stable zone → possible ping-pong.
        """
        if not ho_history or len(ho_history) < 2:
            return 0.0
        
        # Find HOs within the last T_w seconds
        recent_count = sum(
            1 for ho in ho_history 
            if (current_time - ho.get('timestamp', 0.0)) <= self.T_W
        )
        
        f_HO = recent_count / self.T_W  # HOs/s
        
        # Normalize to [0, 1]
        f_HO_norm = min(f_HO / self.f_HO_max, 1.0)
        return f_HO_norm
    
    def _compute_rsrp_variance(self, rsrp_samples: List[float]) -> float:
        """
        Feature 2: σ²_RSRP(i) [normalized to [0, 1]]
        
        RSRP variance indicates signal instability.
        High variance → boundary-zone UE → higher ping-pong risk.
        """
        if len(rsrp_samples) < 2:
            return 0.0
        
        # Use last 20 RSRP samples for variance calculation
        rsrp_recent = rsrp_samples[-20:]
        rsrp_var = np.var(rsrp_recent) if len(rsrp_recent) > 1 else 0.0
        
        # Normalize: assume max variance ≈ 100 dBm² (very unstable)
        rsrp_var_norm = min(rsrp_var / self.rsrp_var_max, 1.0)
        return rsrp_var_norm
    
    def _compute_cell_revisit_ratio(self, ho_history: List[Dict]) -> float:
        """
        Feature 3: R_rev(i) ∈ [0, 1]
        
        Cell revisit ratio = fraction of HOs that return to a previously visited cell.
        R_rev = (# of A→...→A HOs) / (total HOs)
        
        Direct indicator of oscillation pattern.
        """
        if len(ho_history) < 3:
            return 0.0
        
        target_sequence = [ho.get('target', None) for ho in ho_history]
        
        # Count revisits: HOs that revisit a cell from 2 steps ago
        revisit_count = sum(
            1 for i in range(2, len(target_sequence))
            if target_sequence[i] == target_sequence[i - 2]
        )
        
        total_hops = max(len(target_sequence) - 2, 1)
        revisit_ratio = revisit_count / total_hops
        
        return min(revisit_ratio, 1.0)
    
    def _compute_direction_flips(self, ho_history: List[Dict], ue_id: str) -> float:
        """
        Feature 4: D_flip(i) [normalized to [0, 1]]
        
        Direction flip = number of significant direction changes in serving-cell sequence.
        In 2D space, a direction flip occurs when the UE→gNB angle reverses significantly.
        
        Simplified: count alternating target cells (not strictly 2D direction)
        """
        if len(ho_history) < 3:
            return 0.0
        
        target_sequence = [ho.get('target', None) for ho in ho_history]
        
        # Count direction flips: positions where target changes AND direction changes
        flip_count = 0
        for i in range(2, len(target_sequence)):
            # Simple: if targets alternate (A→B→A or similar pattern)
            if (target_sequence[i] != target_sequence[i-1] and
                target_sequence[i-1] != target_sequence[i-2]):
                flip_count += 1
        
        # Normalize
        flip_norm = min(flip_count / max(len(target_sequence) - 2, 1), 1.0)
        return flip_norm
    
    def _compute_oscillation_score(self, ho_history: List[Dict]) -> float:
        """
        Feature 5: Osc(i) ∈ [0, 1]
        
        Oscillation score from Eq. (2):
        Osc(i) = (1 / max(N_HO - 1, 1)) · Σ_{k=2}^{N_HO} I[cell(k) = cell(k-2)]
        
        Direct measure of A→B→A ping-pong pattern.
        Osc = 1 means every HO was a reversal (perfect ping-pong).
        Osc = 0 means no reversals.
        """
        if len(ho_history) < 3:
            return 0.0
        
        target_sequence = [ho.get('target', None) for ho in ho_history]
        
        # Count A→B→A patterns
        osc_count = sum(
            1 for i in range(2, len(target_sequence))
            if target_sequence[i] == target_sequence[i - 2]
        )
        
        # Normalize by total HO count (Eq. 2)
        total_hops = max(len(target_sequence) - 2, 1)
        osc_score = osc_count / total_hops
        
        return min(osc_score, 1.0)
    
    # ─────────────────────────────────────────────────────────────────────────
    # Utility Methods
    # ─────────────────────────────────────────────────────────────────────────
    
    def update_network_statistics(self, all_ues_data: List[Dict]) -> None:
        """
        Update network-wide statistics for normalization (min-max scaling).
        Called periodically to adapt to current network conditions.
        """
        if not all_ues_data:
            return
        
        # Collect all features to compute network max values
        all_f_HO = []
        all_rsrp_var = []
        all_d_flip = []
        
        for ue_data in all_ues_data:
            ho_history = ue_data.get('ho_history', [])
            rsrp_samples = ue_data.get('rsrp_samples', [])
            current_time = ue_data.get('current_time', 0.0)
            
            if len(ho_history) >= 2:
                f_HO = self._compute_ho_frequency(ho_history, current_time)
                all_f_HO.append(f_HO)
                
                rsrp_var = np.var(rsrp_samples[-20:]) if len(rsrp_samples) > 1 else 0
                all_rsrp_var.append(rsrp_var)
        
        # Update max values (with safety floor to prevent division by small values)
        if all_f_HO:
            self.f_HO_max = max(max(all_f_HO), 0.5)
        if all_rsrp_var:
            self.rsrp_var_max = max(max(all_rsrp_var), 10.0)
    
    def get_feature_names(self) -> List[str]:
        """Return human-readable feature names for logging/debugging."""
        return [
            'f_HO (HO Frequency)',
            'σ²_RSRP (RSRP Variance)',
            'R_rev (Cell Revisit Ratio)',
            'D_flip (Direction Flips)',
            'Osc (Oscillation Score)'
        ]


# ═════════════════════════════════════════════════════════════════════════════
# Example usage and validation
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Simple test case
    extractor = FeatureExtractor(normalize=True)
    
    # Simulate UE with handover pattern: A→B→A→B→A (clear ping-pong)
    test_ue = {
        'id': 'UE-1',
        'ho_history': [
            {'target': 'gNB-1', 'rsrp': -90, 'timestamp': 0.0},
            {'target': 'gNB-2', 'rsrp': -92, 'timestamp': 1.0},
            {'target': 'gNB-1', 'rsrp': -91, 'timestamp': 2.0},
            {'target': 'gNB-2', 'rsrp': -93, 'timestamp': 3.0},
            {'target': 'gNB-1', 'rsrp': -90, 'timestamp': 4.0},
        ],
        'rsrp_samples': [-90, -92, -91, -93, -90, -91, -92] * 3,
        'x': 400.0, 'y': 300.0,
        'current_time': 5.0
    }
    
    features = extractor.extract_features_batch(test_ue)
    print("Test UE Features:")
    for name, value in zip(extractor.get_feature_names(), features):
        print(f"  {name}: {value:.4f}")
