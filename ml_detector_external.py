#!/usr/bin/env python3
"""
ML-Based Ping-Pong Detection — External Detection Script
=========================================================

Standalone external script that:
  1. Connects to the 5G Simulator Flask backend via REST API
  2. Periodically fetches UE state and HO history
  3. Runs ML-based detection engine
  4. Makes anchor placement decisions
  5. Sends deployment commands back to simulator

This script runs as a separate process/container and communicates with the
simulator via HTTP REST endpoints.

Reference: Technical Paper §7 (Implementation in gNB-CU-CP)

Usage:
  python3 ml_detector_external.py --simulator-url http://localhost:5000 --interval 0.5
"""

import requests
import json
import time
import argparse
import sys
from typing import Dict, List, Optional
from datetime import datetime

# Import ML detector
from ml_pingpong.detector import MLPingPongDetector


class ExternalMLDetectorClient:
    """
    External client for ML-based ping-pong detection.
    
    Communicates with simulator via REST API:
      GET  /api/get_state            — Fetch all UEs and gNBs
      POST /api/add_anchor_gnb       — Deploy AnchorGNB
      POST /api/assign_dc            — Assign UE to DC
    """
    
    def __init__(self, simulator_url: str = "http://localhost:5000",
                 eval_interval: float = 0.5,
                 model_path: Optional[str] = None,
                 verbose: bool = False):
        """
        Initialize detector client.
        
        Args:
            simulator_url: Base URL of simulator Flask backend
            eval_interval: Evaluation interval (seconds)
            model_path: Optional path to pre-trained ML model
            verbose: Print verbose logs
        """
        self.simulator_url = simulator_url
        self.eval_interval = eval_interval
        self.verbose = verbose
        
        # Initialize ML detector
        self.detector = MLPingPongDetector(model_path=model_path)
        
        # Statistics
        self.eval_count = 0
        self.anchors_deployed = 0
        self.errors = 0
        self.last_eval_time = 0.0
    
    # ─────────────────────────────────────────────────────────────────────────
    # Main Loop
    # ─────────────────────────────────────────────────────────────────────────
    
    def run(self, duration_seconds: Optional[float] = None,
            max_iterations: Optional[int] = None) -> None:
        """
        Main execution loop.
        
        Args:
            duration_seconds: Run for this many seconds (None = forever)
            max_iterations: Run for this many evaluation cycles (None = forever)
        """
        start_time = time.time()
        iteration = 0
        
        print(f"[ML Detector] Starting external detection client")
        print(f"  Simulator URL: {self.simulator_url}")
        print(f"  Eval interval: {self.eval_interval} s")
        print(f"  Verbose: {self.verbose}")
        print("")
        
        try:
            while True:
                # Check termination conditions
                if duration_seconds and (time.time() - start_time) > duration_seconds:
                    print(f"[ML Detector] Duration limit reached ({duration_seconds}s)")
                    break
                
                if max_iterations and iteration >= max_iterations:
                    print(f"[ML Detector] Iteration limit reached ({max_iterations})")
                    break
                
                # Run detection cycle
                try:
                    self._eval_cycle()
                    iteration += 1
                except Exception as e:
                    self.errors += 1
                    print(f"[ERROR] Evaluation cycle failed: {e}")
                    if self.verbose:
                        import traceback
                        traceback.print_exc()
                
                # Sleep
                time.sleep(self.eval_interval)
        
        except KeyboardInterrupt:
            print(f"\n[ML Detector] Interrupted by user")
        
        # Print final statistics
        self._print_summary()
    
    def _eval_cycle(self) -> None:
        """Single evaluation cycle."""
        # Fetch simulator state
        state = self._fetch_state()
        if not state:
            return
        
        current_time = state.get('sim_time', 0.0)
        all_ues = state.get('ues', {})
        
        if not all_ues:
            return
        
        # Convert UE state to detector format
        ue_data = self._convert_ues_to_detector_format(all_ues)
        
        # Run detection
        decisions = self.detector.evaluate(ue_data, current_time)
        
        # Execute decisions
        for decision in decisions:
            if decision['action'] == 'deploy':
                self._deploy_anchor(decision)
        
        self.eval_count += 1
        
        if self.verbose:
            print(f"[{self.eval_count}] Cycle at t={current_time:.1f}s, "
                  f"UEs={len(all_ues)}, decisions={len(decisions)}")
    
    # ─────────────────────────────────────────────────────────────────────────
    # REST API Calls
    # ─────────────────────────────────────────────────────────────────────────
    
    def _fetch_state(self) -> Optional[Dict]:
        """Fetch current simulator state via REST."""
        try:
            url = f"{self.simulator_url}/api/get_state"
            resp = requests.get(url, timeout=5.0)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to fetch simulator state: {e}")
            self.errors += 1
            return None
    
    def _deploy_anchor(self, decision: Dict) -> None:
        """Deploy AnchorGNB via REST."""
        try:
            url = f"{self.simulator_url}/api/add_anchor_gnb"
            payload = {
                'x': decision['centroid'][0],
                'y': decision['centroid'][1],
                'tx_power': decision.get('tx_power_dbm', 50),
                'num_sectors': decision.get('num_sectors', 6),
            }
            
            resp = requests.post(url, json=payload, timeout=5.0)
            resp.raise_for_status()
            result = resp.json()
            
            anchor_gnb_id = result.get('gnb_id')
            
            if self.verbose:
                print(f"[ANCHOR DEPLOYED] {anchor_gnb_id}")
                print(f"  Cluster: {decision['cluster_id']}")
                print(f"  UEs: {decision['ue_ids']}")
                print(f"  Centroid: {decision['centroid']}")
                print(f"  Score: {decision['cluster_score']:.2f}")
            
            # Assign UEs to DC
            for ue_id in decision['ue_ids']:
                self._assign_dc(ue_id, anchor_gnb_id)
            
            self.anchors_deployed += 1
        
        except Exception as e:
            print(f"[ERROR] Failed to deploy anchor: {e}")
            self.errors += 1
    
    def _assign_dc(self, ue_id: str, anchor_gnb_id: str) -> None:
        """Assign UE to Dual Connectivity with anchor as MeNB."""
        try:
            url = f"{self.simulator_url}/api/assign_dc"
            payload = {
                'ue_id': ue_id,
                'anchor_gnb_id': anchor_gnb_id,
            }
            
            resp = requests.post(url, json=payload, timeout=5.0)
            resp.raise_for_status()
            
            if self.verbose:
                print(f"  → DC assigned: {ue_id} MeNB={anchor_gnb_id}")
        
        except Exception as e:
            if self.verbose:
                print(f"  [WARNING] Failed to assign DC to {ue_id}: {e}")
    
    # ─────────────────────────────────────────────────────────────────────────
    # Data Conversion
    # ─────────────────────────────────────────────────────────────────────────
    
    def _convert_ues_to_detector_format(self, ues_dict: Dict) -> Dict:
        """Convert simulator UE state to detector input format."""
        converted = {}
        
        for ue_id, ue in ues_dict.items():
            converted[ue_id] = {
                'id': ue_id,
                'x': ue.get('x', 0.0),
                'y': ue.get('y', 0.0),
                'rsrp': ue.get('rsrp', -120),
                'sinr': ue.get('sinr', -10),
                'handover_history': ue.get('handover_history', []),
                'handover_count': ue.get('handover_count', 0),
                'ping_pong_count': ue.get('ping_pong_count', 0),
            }
        
        return converted
    
    # ─────────────────────────────────────────────────────────────────────────
    # Reporting
    # ─────────────────────────────────────────────────────────────────────────
    
    def _print_summary(self) -> None:
        """Print final statistics."""
        print("\n" + "="*70)
        print("ML Ping-Pong Detector — Final Summary")
        print("="*70)
        
        detector_status = self.detector.get_status()
        
        print(f"Evaluation Cycles:        {self.eval_count}")
        print(f"Anchors Deployed:         {self.anchors_deployed}")
        print(f"API Errors:               {self.errors}")
        print("")
        print("Detector Statistics:")
        print(f"  Total evaluation steps: {detector_status['evaluation_steps']}")
        print(f"  Active anchors:         {len(detector_status['active_anchors'])}")
        print(f"  Cost-benefit rejections:{detector_status['cost_benefit_rejections']}")
        print(f"  False positives:        {detector_status['false_positives']}")
        print(f"  UEs tracked:            {detector_status['ue_count']}")
        print("")
        
        model_info = self.detector.get_model_info()
        print("Model Configuration:")
        print(f"  Predictor type: {model_info['predictor']['model_type']}")
        print(f"  Theta_UE threshold: {model_info['thresholds']['theta_ue']}")
        print(f"  Theta_score threshold: {model_info['thresholds']['theta_score']}")
        print("")
        
        print("Cost Parameters:")
        costs = model_info['costs']
        print(f"  C_HO: {costs['c_ho']}")
        print(f"  C_anchor: {costs['c_anchor']}")
        print(f"  Break-even cluster size: {costs['break_even_cluster_size_at_0_5_ho_per_sec']:.1f} UEs")
    
    def get_metrics(self) -> Dict:
        """Return client metrics."""
        return {
            'eval_count': self.eval_count,
            'anchors_deployed': self.anchors_deployed,
            'errors': self.errors,
            'detector_status': self.detector.get_status(),
        }


# ═════════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═════════════════════════════════════════════════════════════════════════════

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="ML-Based Ping-Pong Detection for 5G NR Simulator"
    )
    parser.add_argument(
        '--simulator-url',
        default='http://localhost:5000',
        help='Base URL of simulator Flask backend'
    )
    parser.add_argument(
        '--interval',
        type=float,
        default=0.5,
        help='Evaluation interval in seconds'
    )
    parser.add_argument(
        '--duration',
        type=float,
        default=None,
        help='Run for this many seconds (None = forever)'
    )
    parser.add_argument(
        '--max-iterations',
        type=int,
        default=None,
        help='Run for this many evaluation cycles'
    )
    parser.add_argument(
        '--model-path',
        default=None,
        help='Path to pre-trained ML model'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose logging'
    )
    
    args = parser.parse_args()
    
    # Create and run client
    client = ExternalMLDetectorClient(
        simulator_url=args.simulator_url,
        eval_interval=args.interval,
        model_path=args.model_path,
        verbose=args.verbose
    )
    
    client.run(
        duration_seconds=args.duration,
        max_iterations=args.max_iterations
    )


if __name__ == '__main__':
    main()
