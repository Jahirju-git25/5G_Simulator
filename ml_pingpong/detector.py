"""
ML-Based Ping-Pong Detection — Main Detector Orchestrator
==========================================================

Integrates all ML modules (feature extraction, prediction, clustering, cost-benefit)
into a unified ping-pong detection engine.

Pipeline:
  1. Collect HO events and RRC measurements from UEs
  2. Extract 5-dimensional features per UE
  3. ML inference: compute P_pp (ping-pong probability)
  4. Filter candidates: P_pp ≥ θ_ue (threshold)
  5. DBSCAN spatial clustering
  6. Coverage radius validation
  7. Cluster score computation with time-decay
  8. Cost-benefit analysis
  9. Anchor deployment decision & anchor placement

Reference: Technical Paper §5 (Algorithm 1)
"""

import numpy as np
import math
import time
from typing import Dict, List, Optional, Tuple
from collections import deque

from .feature_extractor import FeatureExtractor
from .ml_predictor import MLPingPongPredictor
from .dbscan_clusterer import DBSCANClusterer
from .cost_benefit import CostBenefitOptimizer


class MLPingPongDetector:
    """
    Complete ML-based ping-pong detection engine.
    
    Thresholds and parameters:
      θ_ue:              P_pp threshold for candidate filtering (0.6)
      θ (theta):         Cluster score threshold for trigger (1.5)
      T_cool:            Cooldown period after anchor deployment (10 s)
      T_eval:            Feature evaluation interval (0.5 s)
      T_remove:          Anchor removal threshold when Score_k < θ/2 (30 s)
    """
    
    # Thresholds (from paper)
    THETA_UE = 0.6         # P_pp threshold for candidates
    THETA_SCORE = 1.5      # Cluster score threshold
    T_COOL = 10.0          # Cooldown period (seconds)
    T_EVAL = 0.5           # Evaluation interval (seconds)
    T_REMOVE = 30.0        # Anchor removal timeout (seconds)
    
    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize ML detector with all sub-modules.
        
        Args:
            model_path: Optional path to pre-trained ML model
        """
        # Sub-modules
        self.feature_extractor = FeatureExtractor(normalize=True)
        self.ml_predictor = MLPingPongPredictor(model_path=model_path, use_sklearn=True)
        self.clusterer = DBSCANClusterer()
        self.cost_benefit = CostBenefitOptimizer()
        
        # State management
        self.ue_data: Dict[str, Dict] = {}  # Per-UE state tracking
        self.cluster_cooldowns: Dict[str, float] = {}  # Cluster ID → cooldown timestamp
        self.deployed_anchors: Dict[str, Dict] = {}  # Anchor ID → anchor metadata
        
        # Metrics
        self.eval_step = 0
        self.anchor_count = 0
        self.deployments_skipped_cost_benefit = 0
        self.false_positive_count = 0
        
        # Logging
        self.detection_log: deque = deque(maxlen=1000)
        self.last_eval_time = 0.0
    
    # ─────────────────────────────────────────────────────────────────────────
    # Main Detection Pipeline
    # ─────────────────────────────────────────────────────────────────────────
    
    def evaluate(self, all_ues: Dict[str, Dict], current_time: float) -> List[Dict]:
        """
        Main evaluation method. Called periodically from external detector script.
        
        Args:
            all_ues: Dict of all UEs {ue_id: ue_dict with position, ho_history, etc.}
            current_time: Current simulation time
        
        Returns:
            List of anchor deployment decisions:
            [
              {
                'action': 'deploy',
                'cluster_id': str,
                'ue_ids': [str],
                'centroid': (float, float),
                'gnb_id': str (generated for new anchors)
              },
              ...
            ]
        """
        decisions = []
        
        # Throttle evaluation to T_EVAL interval
        if (current_time - self.last_eval_time) < self.T_EVAL:
            return decisions
        
        self.last_eval_time = current_time
        self.eval_step += 1
        
        # ─── STEP 1: Update UE data ─────────────────────────────────────────
        self._update_ue_data(all_ues, current_time)
        
        # ─── STEP 2: Extract features for all UEs ──────────────────────────
        ue_features: Dict[str, np.ndarray] = {}
        for ue_id, ue_info in self.ue_data.items():
            features = self.feature_extractor.extract_features_batch(ue_info)
            ue_features[ue_id] = features
        
        # ─── STEP 3: ML Inference (compute P_pp) ──────────────────────────
        ue_p_pp: Dict[str, float] = {}
        for ue_id, features in ue_features.items():
            p_pp = self.ml_predictor.predict_probability(features)
            ue_p_pp[ue_id] = p_pp
        
        # ─── STEP 4: Filter candidates (P_pp ≥ θ_ue) ─────────────────────
        candidates = []
        for ue_id, p_pp in ue_p_pp.items():
            if p_pp >= self.THETA_UE and ue_id in self.ue_data:
                ue_info = self.ue_data[ue_id]
                candidates.append({
                    'id': ue_id,
                    'x': ue_info['x'],
                    'y': ue_info['y'],
                    'p_pp': p_pp,
                    'last_pp_time': ue_info.get('last_pp_time', current_time),
                    'ho_frequency': ue_info.get('ho_frequency', 0.0)
                })
        
        if not candidates or len(candidates) < self.clusterer.MIN_PTS:
            return decisions  # Not enough ping-pong UEs
        
        # ─── STEP 5: DBSCAN Clustering ──────────────────────────────────
        clusters = self.clusterer.cluster_ping_pong_ues(candidates, current_time)
        
        if not clusters:
            return decisions  # No clusters formed
        
        # ─── STEP 6-10: Process each cluster ────────────────────────────
        for cluster_idx, cluster_ue_ids in enumerate(clusters):
            cluster_id = f"C{self.eval_step}_{cluster_idx}"
            
            # Check cooldown
            if self._is_in_cooldown(cluster_id, current_time):
                continue
            
            # Get UE info for cluster
            cluster_ues = [
                {**c, 'id': c['id']}
                for c in candidates if c['id'] in cluster_ue_ids
            ]
            
            if len(cluster_ues) < self.clusterer.MIN_PTS:
                continue  # Minimum cluster size
            
            # ─── STEP 7: Coverage Radius Check ──────────────────────────
            centroid = self.clusterer.compute_weighted_centroid(cluster_ues, current_time)
            if not centroid:
                continue
            
            if not self.clusterer.validate_coverage(centroid, cluster_ues):
                self._log("COVERAGE_FAILED", {
                    'cluster_id': cluster_id,
                    'cluster_size': len(cluster_ues),
                    'centroid': centroid
                })
                continue
            
            # ─── STEP 8: Cluster Score ──────────────────────────────────
            cluster_score = self._compute_cluster_score(cluster_ues, current_time, ue_p_pp)
            
            if cluster_score <= self.THETA_SCORE:
                continue
            
            # ─── STEP 9: Cost-Benefit Analysis ──────────────────────────
            avg_ho_freq = np.mean([u.get('ho_frequency', 0.0) for u in cluster_ues])
            cb_result = self.cost_benefit.should_deploy_anchor(
                len(cluster_ues), avg_ho_freq
            )
            
            if not cb_result['deploy']:
                self.deployments_skipped_cost_benefit += 1
                self._log("COST_BENEFIT_REJECTED", {
                    'cluster_id': cluster_id,
                    'cluster_size': len(cluster_ues),
                    'net_benefit': cb_result['net_benefit']
                })
                continue
            
            # ─── STEP 10: DEPLOY ANCHOR ────────────────────────────────
            anchor_decision = self._create_anchor_decision(
                cluster_id, cluster_ue_ids, centroid, cluster_score, current_time
            )
            
            decisions.append(anchor_decision)
            
            # Mark cooldown
            self._set_cooldown(cluster_id, current_time)
            
            self._log("ANCHOR_DEPLOYED", {
                'cluster_id': cluster_id,
                'ue_ids': cluster_ue_ids,
                'centroid': centroid,
                'cluster_score': cluster_score,
                'net_benefit': cb_result['net_benefit']
            })
        
        return decisions
    
    # ─────────────────────────────────────────────────────────────────────────
    # Helper Methods
    # ─────────────────────────────────────────────────────────────────────────
    
    def _update_ue_data(self, all_ues: Dict[str, Dict], current_time: float) -> None:
        """Update internal UE state tracking."""
        for ue_id, ue in all_ues.items():
            if ue_id not in self.ue_data:
                self.ue_data[ue_id] = {
                    'ho_history': deque(maxlen=100),
                    'rsrp_samples': deque(maxlen=200),
                }
            
            # Current position and measurements
            self.ue_data[ue_id]['x'] = ue.get('x', 0.0)
            self.ue_data[ue_id]['y'] = ue.get('y', 0.0)
            self.ue_data[ue_id]['current_time'] = current_time
            
            # Handover history
            ho_history = ue.get('handover_history', [])
            if ho_history:
                # Add recent HOs to deque
                for ho in ho_history:
                    self.ue_data[ue_id]['ho_history'].append({
                        'target': ho.get('target', ho.get('to')),
                        'rsrp': ho.get('rsrp', -100),
                        'timestamp': current_time - (len(ho_history) - ho_history.index(ho)) * 1.0
                    })
            
            # RSRP samples
            rsrp = ue.get('rsrp', -120)
            if rsrp:
                self.ue_data[ue_id]['rsrp_samples'].append(rsrp)
            
            # HO frequency
            self.ue_data[ue_id]['ho_frequency'] = len(self.ue_data[ue_id]['ho_history']) / 10.0
            
            # Last ping-pong time (infer from history)
            if len(self.ue_data[ue_id]['ho_history']) >= 3:
                ho_hist = list(self.ue_data[ue_id]['ho_history'])
                for i in range(len(ho_hist) - 2, -1, -1):
                    if ho_hist[i]['target'] == ho_hist[i + 2]['target']:
                        self.ue_data[ue_id]['last_pp_time'] = current_time - (len(ho_hist) - i - 1)
                        break
                else:
                    self.ue_data[ue_id]['last_pp_time'] = current_time - 999.0
            else:
                self.ue_data[ue_id]['last_pp_time'] = current_time - 999.0
            
            self.ue_data[ue_id]['id'] = ue_id
    
    def _compute_cluster_score(self, cluster_ues: List[Dict], current_time: float,
                              ue_p_pp: Dict[str, float]) -> float:
        """
        Compute cluster score with time-decay weighting.
        
        Score_k = Σ_{i ∈ C_k} w_i(t) · P_pp(i)
        
        where w_i(t) = exp(-λ · Δt_i)
        """
        score = 0.0
        
        for ue in cluster_ues:
            ue_id = ue['id']
            p_pp = ue_p_pp.get(ue_id, 0.0)
            
            delta_t = current_time - ue.get('last_pp_time', current_time)
            weight = math.exp(-self.clusterer.lambda_decay * delta_t)
            
            score += weight * p_pp
        
        return score
    
    def _create_anchor_decision(self, cluster_id: str, ue_ids: List[str],
                               centroid: Tuple[float, float],
                               cluster_score: float,
                               current_time: float) -> Dict:
        """Create anchor deployment decision record."""
        anchor_id = f"AnchorGNB-{self.anchor_count}"
        self.anchor_count += 1
        
        self.deployed_anchors[anchor_id] = {
            'id': anchor_id,
            'cluster_id': cluster_id,
            'ue_ids': ue_ids,
            'centroid': centroid,
            'cluster_score': cluster_score,
            'deployment_time': current_time,
            'status': 'active'
        }
        
        return {
            'action': 'deploy',
            'cluster_id': cluster_id,
            'ue_ids': ue_ids,
            'centroid': centroid,
            'gnb_id': anchor_id,
            'tx_power_dbm': 50,
            'num_sectors': 6,
            'cluster_score': cluster_score
        }
    
    def _is_in_cooldown(self, cluster_id: str, current_time: float) -> bool:
        """Check if cluster is in cooldown period."""
        if cluster_id not in self.cluster_cooldowns:
            return False
        
        cooldown_until = self.cluster_cooldowns[cluster_id]
        return current_time < cooldown_until
    
    def _set_cooldown(self, cluster_id: str, current_time: float) -> None:
        """Set cooldown for cluster."""
        self.cluster_cooldowns[cluster_id] = current_time + self.T_COOL
    
    def _log(self, event_type: str, details: Dict) -> None:
        """Log detection event."""
        entry = {
            'step': self.eval_step,
            'type': event_type,
            'timestamp': time.time(),
            'details': details
        }
        self.detection_log.append(entry)
    
    # ─────────────────────────────────────────────────────────────────────────
    # Status and Metrics
    # ─────────────────────────────────────────────────────────────────────────
    
    def get_status(self) -> Dict:
        """Get detector status and metrics."""
        return {
            'evaluation_steps': self.eval_step,
            'anchors_deployed': len(self.deployed_anchors),
            'cost_benefit_rejections': self.deployments_skipped_cost_benefit,
            'false_positives': self.false_positive_count,
            'active_anchors': {
                aid: a for aid, a in self.deployed_anchors.items()
                if a['status'] == 'active'
            },
            'ue_count': len(self.ue_data),
        }
    
    def get_model_info(self) -> Dict:
        """Get ML model information."""
        return {
            'predictor': self.ml_predictor.get_model_info(),
            'feature_extractor': {
                'window_size_s': self.feature_extractor.T_W,
                'eval_interval_s': self.feature_extractor.EVAL_INTERVAL,
            },
            'clustering': self.clusterer.get_parameters(),
            'costs': self.cost_benefit.get_costs(),
            'thresholds': {
                'theta_ue': self.THETA_UE,
                'theta_score': self.THETA_SCORE,
                'cooldown_s': self.T_COOL,
            }
        }


# ═════════════════════════════════════════════════════════════════════════════
# Example usage
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Initialize detector
    detector = MLPingPongDetector()
    
    # Simulate UE data
    all_ues = {
        'UE-1': {
            'x': 100.0, 'y': 100.0,
            'rsrp': -90,
            'handover_history': [
                {'to': 'gNB-1', 'rsrp': -90},
                {'to': 'gNB-2', 'rsrp': -92},
                {'to': 'gNB-1', 'rsrp': -91},
                {'to': 'gNB-2', 'rsrp': -93},
            ]
        },
        'UE-2': {
            'x': 110.0, 'y': 105.0,
            'rsrp': -89,
            'handover_history': [
                {'to': 'gNB-2', 'rsrp': -88},
                {'to': 'gNB-1', 'rsrp': -91},
                {'to': 'gNB-2', 'rsrp': -90},
            ]
        },
    }
    
    # Run detection
    decisions = detector.evaluate(all_ues, current_time=100.0)
    print(f"Anchor deployment decisions: {len(decisions)}")
    for decision in decisions:
        print(f"  - Deploy {decision['gnb_id']} for cluster {decision['cluster_id']}")
        print(f"    UEs: {decision['ue_ids']}, Centroid: {decision['centroid']}")
    
    # Show status
    print("\nDetector Status:")
    status = detector.get_status()
    for key, value in status.items():
        print(f"  {key}: {value}")
