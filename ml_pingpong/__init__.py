"""
ML-Based Ping-Pong Detection Package
====================================

Sub-modules:
  - feature_extractor:  Extract 5-dimensional features from HO events
  - ml_predictor:       Logistic regression model for P_pp prediction
  - dbscan_clusterer:   DBSCAN spatial clustering of ping-pong UEs
  - cost_benefit:       Economic analysis for anchor deployment
  - detector:           Main detection orchestrator (integrates all modules)

Usage:
  from ml_pingpong.detector import MLPingPongDetector
  
  detector = MLPingPongDetector()
  decisions = detector.evaluate(all_ues, current_time)
"""

from .feature_extractor import FeatureExtractor
from .ml_predictor import MLPingPongPredictor
from .dbscan_clusterer import DBSCANClusterer
from .cost_benefit import CostBenefitOptimizer
from .detector import MLPingPongDetector

__all__ = [
    'FeatureExtractor',
    'MLPingPongPredictor',
    'DBSCANClusterer',
    'CostBenefitOptimizer',
    'MLPingPongDetector',
]

__version__ = '1.0.0'
