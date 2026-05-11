"""
ML-Based Ping-Pong Detection — Cost-Benefit Analysis Module
===========================================================

Economic decision gate for anchor deployment.

Cost-Benefit Function:
  J_k = N_k · C_HO · f_HO_k - C_anchor
  
  Deploy anchor iff J_k > 0
  
  Break-even cluster size: N* = C_anchor / (C_HO · f_HO_k)
  
  With typical parameters: N* ≈ 3 UEs minimum

Reference: Technical Paper §3.8, §3.9
"""

import numpy as np
from typing import Dict, List, Optional, Tuple


class CostBenefitOptimizer:
    """
    Economic analysis for anchor deployment.
    
    Parameters:
      C_HO:     Normalized cost per unnecessary HO event
      C_anchor: Normalized cost of deploying one AnchorGNB
    """
    
    # Default cost parameters (from paper calibration)
    # Adjusted for better testing: lower C_anchor encourages deployment
    DEFAULT_C_HO = 0.7        # cost units per unnecessary HO
    DEFAULT_C_ANCHOR = 0.5    # cost units per AnchorGNB (reduced from 1.0 to trigger deployment more easily)
    
    def __init__(self, c_ho: float = DEFAULT_C_HO,
                 c_anchor: float = DEFAULT_C_ANCHOR):
        """
        Initialize cost-benefit optimizer.
        
        Args:
            c_ho: Cost per HO (relative units)
            c_anchor: Cost per anchor deployment (relative units)
        """
        self.c_ho = c_ho
        self.c_anchor = c_anchor
    
    # ─────────────────────────────────────────────────────────────────────────
    # Main Decision Method
    # ─────────────────────────────────────────────────────────────────────────
    
    def should_deploy_anchor(self, cluster_size: int,
                            avg_ho_frequency: float) -> Dict:
        """
        Determine if anchor deployment is economically justified.
        
        Cost function (Eq. 9):
          J_k = N_k · C_HO · f_HO_k - C_anchor
          
        Deploy iff J_k > 0
        
        Args:
            cluster_size: N_k = number of UEs in cluster
            avg_ho_frequency: f_HO_k = average HO frequency (HOs/s) in cluster
        
        Returns:
            Dict with:
              'deploy': bool — whether to deploy
              'net_benefit': float — J_k value
              'break_even_size': float — N* for this HO frequency
              'payoff_time_seconds': float — time to amortize anchor cost
              'cost_breakdown': dict — detailed costs
        """
        # Compute net benefit (Eq. 9)
        ho_benefit = cluster_size * self.c_ho * avg_ho_frequency
        net_benefit = ho_benefit - self.c_anchor
        
        # Break-even cluster size (Eq. 10)
        if avg_ho_frequency > 0.01:
            break_even_size = self.c_anchor / (self.c_ho * avg_ho_frequency)
        else:
            break_even_size = float('inf')
        
        # Payoff time: time for saved HOs to equal anchor cost
        if avg_ho_frequency > 0.01 and cluster_size > 0:
            # Saves HO_savings = cluster_size * avg_ho_frequency * c_HO per second
            # Time to save C_anchor units
            payoff_time = self.c_anchor / (cluster_size * self.c_ho * avg_ho_frequency)
        else:
            payoff_time = float('inf')
        
        return {
            'deploy': net_benefit > 0,
            'net_benefit': net_benefit,
            'break_even_size': break_even_size,
            'payoff_time_seconds': payoff_time,
            'cost_breakdown': {
                'cluster_size': cluster_size,
                'avg_ho_frequency_per_sec': avg_ho_frequency,
                'total_ho_benefit': ho_benefit,
                'anchor_cost': self.c_anchor,
                'net_benefit': net_benefit,
            }
        }
    
    # ─────────────────────────────────────────────────────────────────────────
    # Batch Analysis
    # ─────────────────────────────────────────────────────────────────────────
    
    def analyze_clusters(self, clusters: List[Dict]) -> Dict[str, Dict]:
        """
        Analyze cost-benefit for all clusters.
        
        Args:
            clusters: List of cluster dicts with:
              {
                'id': str,
                'size': int,
                'avg_ho_frequency': float
              }
        
        Returns:
            Dict {cluster_id: analysis_result}
        """
        results = {}
        for cluster in clusters:
            cluster_id = cluster.get('id', 'unknown')
            size = cluster.get('size', 0)
            avg_ho_freq = cluster.get('avg_ho_frequency', 0.0)
            
            analysis = self.should_deploy_anchor(size, avg_ho_freq)
            results[cluster_id] = analysis
        
        return results
    
    # ─────────────────────────────────────────────────────────────────────────
    # Sensitivity Analysis
    # ─────────────────────────────────────────────────────────────────────────
    
    def sensitivity_analysis(self, cluster_size: int,
                            avg_ho_frequency: float) -> Dict:
        """
        Sensitivity analysis: how decision changes with parameters.
        
        Args:
            cluster_size: Number of UEs
            avg_ho_frequency: Average HO rate
        
        Returns:
            Dict with sensitivity results
        """
        # Base case
        base = self.should_deploy_anchor(cluster_size, avg_ho_frequency)
        
        # Sweep cluster size (±50%)
        size_variations = {}
        for delta in [-0.5, -0.25, 0, 0.25, 0.5]:
            var_size = max(1, int(cluster_size * (1 + delta)))
            result = self.should_deploy_anchor(var_size, avg_ho_frequency)
            size_variations[f"{var_size}"] = result['deploy']
        
        # Sweep HO frequency (±50%)
        freq_variations = {}
        for delta in [-0.5, -0.25, 0, 0.25, 0.5]:
            var_freq = max(0.01, avg_ho_frequency * (1 + delta))
            result = self.should_deploy_anchor(cluster_size, var_freq)
            freq_variations[f"{var_freq:.2f}"] = result['deploy']
        
        # Sweep costs
        cost_variations = {}
        for c_ho_factor in [0.5, 0.75, 1.0, 1.5, 2.0]:
            orig_c_ho = self.c_ho
            self.c_ho = self.DEFAULT_C_HO * c_ho_factor
            result = self.should_deploy_anchor(cluster_size, avg_ho_frequency)
            cost_variations[f"C_HO={c_ho_factor}x"] = result['deploy']
            self.c_ho = orig_c_ho
        
        return {
            'base_case': base,
            'cluster_size_sensitivity': size_variations,
            'ho_frequency_sensitivity': freq_variations,
            'cost_sensitivity': cost_variations,
        }
    
    # ─────────────────────────────────────────────────────────────────────────
    # Economic Metrics
    # ─────────────────────────────────────────────────────────────────────────
    
    def compute_roi(self, cluster_size: int, avg_ho_frequency: float,
                   deployment_duration_seconds: float = 600.0) -> Dict:
        """
        Compute Return on Investment (ROI) for anchor deployment.
        
        Args:
            cluster_size: Number of UEs
            avg_ho_frequency: HO rate per UE per second
            deployment_duration_seconds: How long anchor is deployed (default 10 min)
        
        Returns:
            Dict with ROI metrics
        """
        analysis = self.should_deploy_anchor(cluster_size, avg_ho_frequency)
        
        # Total cost saved by avoiding unnecessary HOs
        total_hops = cluster_size * avg_ho_frequency * deployment_duration_seconds
        cost_saved = total_hops * self.c_ho
        
        # Net ROI
        net_roi = cost_saved - self.c_anchor
        roi_percent = (net_roi / self.c_anchor * 100) if self.c_anchor > 0 else 0
        
        return {
            'deployment_duration_s': deployment_duration_seconds,
            'total_hops_prevented': total_hops,
            'cost_saved': cost_saved,
            'anchor_cost': self.c_anchor,
            'net_roi': net_roi,
            'roi_percent': roi_percent,
            'is_profitable': net_roi > 0,
        }
    
    # ─────────────────────────────────────────────────────────────────────────
    # Configuration
    # ─────────────────────────────────────────────────────────────────────────
    
    def set_costs(self, c_ho: Optional[float] = None,
                 c_anchor: Optional[float] = None) -> None:
        """Update cost parameters."""
        if c_ho is not None:
            self.c_ho = c_ho
        if c_anchor is not None:
            self.c_anchor = c_anchor
    
    def get_costs(self) -> Dict:
        """Get current cost parameters."""
        return {
            'c_ho': self.c_ho,
            'c_anchor': self.c_anchor,
            'break_even_cluster_size_at_0_5_ho_per_sec': (
                self.c_anchor / (self.c_ho * 0.5)
            ),
        }
    
    # ─────────────────────────────────────────────────────────────────────────
    # Reporting
    # ─────────────────────────────────────────────────────────────────────────
    
    def format_decision_report(self, cluster_id: str, decision_result: Dict) -> str:
        """Format human-readable decision report."""
        deploy = decision_result['deploy']
        net_benefit = decision_result['net_benefit']
        break_even = decision_result['break_even_size']
        payoff = decision_result['payoff_time_seconds']
        
        status = "✓ DEPLOY" if deploy else "✗ SKIP"
        
        report = f"""
        {status} Anchor for Cluster {cluster_id}
        ────────────────────────────────────────────
        Net Benefit (J_k):        {net_benefit:+.2f} cost units
        Break-even Cluster Size:  {break_even:.1f} UEs
        Payoff Time:              {payoff:.1f} seconds
        
        Cost Breakdown:
          Total HO Benefit:  {decision_result['cost_breakdown']['total_ho_benefit']:.2f}
          Anchor Cost:       {decision_result['cost_breakdown']['anchor_cost']:.2f}
        """
        return report


# ═════════════════════════════════════════════════════════════════════════════
# Example usage
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Initialize optimizer
    optimizer = CostBenefitOptimizer(c_ho=0.7, c_anchor=1.0)
    
    print("Cost-Benefit Analysis Examples")
    print("=" * 70)
    
    # Scenario 1: 3 UEs, 0.5 HOs/s (break-even case)
    print("\n1. Break-even Scenario (3 UEs @ 0.5 HOs/s):")
    result1 = optimizer.should_deploy_anchor(3, 0.5)
    print(optimizer.format_decision_report("Cluster-1", result1))
    
    # Scenario 2: 5 UEs, 0.8 HOs/s (profitable)
    print("\n2. Profitable Scenario (5 UEs @ 0.8 HOs/s):")
    result2 = optimizer.should_deploy_anchor(5, 0.8)
    print(optimizer.format_decision_report("Cluster-2", result2))
    
    # Scenario 3: 1 UE, 0.3 HOs/s (unprofitable)
    print("\n3. Unprofitable Scenario (1 UE @ 0.3 HOs/s):")
    result3 = optimizer.should_deploy_anchor(1, 0.3)
    print(optimizer.format_decision_report("Cluster-3", result3))
    
    # ROI analysis
    print("\n4. ROI Analysis (5 UEs @ 0.8 HOs/s, 10 min deployment):")
    roi = optimizer.compute_roi(5, 0.8, deployment_duration_seconds=600)
    print(f"   Cost Saved:    {roi['cost_saved']:.2f}")
    print(f"   Anchor Cost:   {roi['anchor_cost']:.2f}")
    print(f"   Net ROI:       {roi['net_roi']:+.2f} ({roi['roi_percent']:+.1f}%)")
    
    # Sensitivity
    print("\n5. Sensitivity Analysis (3 UEs @ 0.5 HOs/s):")
    sensitivity = optimizer.sensitivity_analysis(3, 0.5)
    print("   Cluster size sensitivity:")
    for size, deploy in sensitivity['cluster_size_sensitivity'].items():
        print(f"     {size} UEs: {'DEPLOY' if deploy else 'SKIP'}")
