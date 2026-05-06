"""
ML-Based Ping-Pong Detection — ML Predictor Module
===================================================

Implements logistic regression model for P_pp (ping-pong probability) prediction.

Model:
  P_pp(i) = σ(α·f̄_HO + β·σ̄²_RSRP + γ·R̄_rev + δ·D̄_flip + η·Osc)
  
  where σ(z) = 1 / (1 + exp(-z))  [sigmoid function]
  and α=0.30, β=0.20, γ=0.25, δ=0.15, η=0.10

Reference: Technical Paper §3.1, §4.2, §4.3
"""

import numpy as np
import math
from typing import Dict, List, Tuple, Optional
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import pickle
import os


class MLPingPongPredictor:
    """
    Logistic regression model for ping-pong probability prediction.
    
    Feature weights (from paper):
      α (f_HO):     0.30  — most important: HO frequency
      β (σ²_RSRP):  0.20  — RSRP variance
      γ (R_rev):    0.25  — cell revisit ratio
      δ (D_flip):   0.15  — direction flips
      η (Osc):      0.10  — oscillation score
    """
    
    # Default feature weights (can be overridden with trained model)
    DEFAULT_WEIGHTS = {
        'f_HO': 0.30,
        'rsrp_var': 0.20,
        'revisit': 0.25,
        'flip': 0.15,
        'osc': 0.10,
    }
    
    def __init__(self, model_path: Optional[str] = None, use_sklearn: bool = True):
        """
        Initialize predictor with optional pre-trained model.
        
        Args:
            model_path: Path to pickled sklearn LogisticRegression model
            use_sklearn: If True, use sklearn LogisticRegression; else use manual sigmoid
        """
        self.use_sklearn = use_sklearn
        self.model = None
        self.scaler = None
        self.weights = self.DEFAULT_WEIGHTS.copy()
        self.bias = 0.0
        
        if model_path and os.path.exists(model_path):
            self._load_model(model_path)
        else:
            if use_sklearn:
                # Initialize untrained sklearn model
                self.model = LogisticRegression(
                    C=1.0,
                    max_iter=100,
                    random_state=42,
                    n_jobs=-1
                )
                self.scaler = StandardScaler()
            else:
                # Use manual sigmoid with default weights
                self._init_manual_model()
    
    # ─────────────────────────────────────────────────────────────────────────
    # Prediction Methods
    # ─────────────────────────────────────────────────────────────────────────
    
    def predict_probability(self, features: np.ndarray) -> float:
        """
        Predict ping-pong probability for a UE from feature vector.
        
        Args:
            features: np.array([f_HO_norm, rsrp_var_norm, revisit_ratio, flip_norm, osc])
        
        Returns:
            P_pp ∈ [0, 1] — probability of ping-pong
        """
        if features is None or len(features) < 5:
            return 0.0
        
        if self.use_sklearn and self.model is not None:
            return self._predict_sklearn(features)
        else:
            return self._predict_manual_sigmoid(features)
    
    def predict_batch(self, features_list: List[np.ndarray]) -> List[float]:
        """
        Predict ping-pong probabilities for multiple UEs (vectorized).
        
        Args:
            features_list: List of feature vectors
        
        Returns:
            List of P_pp values
        """
        probabilities = []
        for features in features_list:
            probabilities.append(self.predict_probability(features))
        return probabilities
    
    def _predict_sklearn(self, features: np.ndarray) -> float:
        """Predict using sklearn LogisticRegression model."""
        try:
            # Reshape to 2D for sklearn
            X = features.reshape(1, -1)
            
            # Scale features if scaler is available
            if self.scaler is not None:
                try:
                    X = self.scaler.transform(X)
                except:
                    pass  # Scaler may not be fitted yet
            
            # Get probability of positive class
            p_pp = self.model.predict_proba(X)[0, 1]
            return float(np.clip(p_pp, 0.0, 1.0))
        except Exception as e:
            print(f"[WARNING] sklearn prediction failed: {e}; fallback to manual sigmoid")
            return self._predict_manual_sigmoid(features)
    
    def _predict_manual_sigmoid(self, features: np.ndarray) -> float:
        """
        Predict using manual sigmoid with weighted combination.
        
        P_pp = σ(Σ w_i · f_i + b)
        
        where σ(z) = 1 / (1 + exp(-z))
        """
        feature_names = ['f_HO', 'rsrp_var', 'revisit', 'flip', 'osc']
        
        # Compute weighted sum
        z = 0.0
        for i, name in enumerate(feature_names):
            if i < len(features):
                z += self.weights[name] * features[i]
        
        z += self.bias
        
        # Apply sigmoid
        p_pp = 1.0 / (1.0 + math.exp(-z))
        
        return float(np.clip(p_pp, 0.0, 1.0))
    
    # ─────────────────────────────────────────────────────────────────────────
    # Training Methods (for online learning)
    # ─────────────────────────────────────────────────────────────────────────
    
    def online_update(self, features_list: List[np.ndarray], labels: List[int],
                      sample_weights: Optional[List[float]] = None,
                      learning_rate: float = 0.001) -> None:
        """
        Online learning update with recent HO events.
        
        Called every 60 seconds with last ~1000 HO events.
        
        Args:
            features_list: List of feature vectors
            labels: List of binary labels (1 if HO led to ping-pong, else 0)
            sample_weights: Time-decay weights (recent events weighted higher)
            learning_rate: SGD learning rate
        """
        if len(features_list) < 10:
            return  # Need minimum samples for update
        
        X = np.array(features_list)
        y = np.array(labels)
        
        if sample_weights is None:
            sample_weights = np.ones(len(y))
        else:
            sample_weights = np.array(sample_weights)
        
        try:
            if self.use_sklearn and self.model is not None:
                # Scale features
                if self.scaler.n_features_in_ is None:
                    self.scaler.fit(X)
                X_scaled = self.scaler.transform(X)
                
                # Partial fit with time decay weights
                self.model.partial_fit(
                    X_scaled, y,
                    classes=[0, 1],
                    sample_weight=sample_weights
                )
                print(f"[ML] Online update: {len(y)} samples, learning_rate={learning_rate}")
            else:
                # Manual SGD on sigmoid weights
                self._update_manual_weights(X, y, sample_weights, learning_rate)
        except Exception as e:
            print(f"[WARNING] Online update failed: {e}")
    
    def _update_manual_weights(self, X: np.ndarray, y: np.ndarray,
                               weights_array: np.ndarray,
                               learning_rate: float) -> None:
        """Perform SGD on manual sigmoid weights."""
        feature_names = ['f_HO', 'rsrp_var', 'revisit', 'flip', 'osc']
        
        # Compute gradients using cross-entropy loss
        for epoch in range(3):  # 3 epochs for stability
            for i, (x, label, w) in enumerate(zip(X, y, weights_array)):
                # Predict
                z = sum(self.weights[feature_names[j]] * x[j] for j in range(len(feature_names)))
                z += self.bias
                p = 1.0 / (1.0 + math.exp(-z))
                
                # Gradient of cross-entropy loss
                grad = (p - label) * w
                
                # Update weights
                for j, name in enumerate(feature_names):
                    self.weights[name] -= learning_rate * grad * x[j]
                self.bias -= learning_rate * grad
    
    # ─────────────────────────────────────────────────────────────────────────
    # Model Persistence
    # ─────────────────────────────────────────────────────────────────────────
    
    def save_model(self, path: str) -> None:
        """Save model and scaler to disk."""
        data = {
            'model': self.model if self.use_sklearn else None,
            'scaler': self.scaler if self.use_sklearn else None,
            'weights': self.weights,
            'bias': self.bias,
            'use_sklearn': self.use_sklearn
        }
        with open(path, 'wb') as f:
            pickle.dump(data, f)
        print(f"[ML] Model saved to {path}")
    
    def _load_model(self, path: str) -> None:
        """Load model and scaler from disk."""
        try:
            with open(path, 'rb') as f:
                data = pickle.load(f)
            self.model = data.get('model')
            self.scaler = data.get('scaler')
            self.weights = data.get('weights', self.DEFAULT_WEIGHTS)
            self.bias = data.get('bias', 0.0)
            self.use_sklearn = data.get('use_sklearn', True)
            print(f"[ML] Model loaded from {path}")
        except Exception as e:
            print(f"[WARNING] Failed to load model: {e}")
    
    def _init_manual_model(self) -> None:
        """Initialize manual sigmoid model with default weights."""
        self.weights = self.DEFAULT_WEIGHTS.copy()
        self.bias = 0.0
    
    # ─────────────────────────────────────────────────────────────────────────
    # Model Information
    # ─────────────────────────────────────────────────────────────────────────
    
    def get_feature_weights(self) -> Dict[str, float]:
        """Get current feature weights for logging."""
        return self.weights.copy()
    
    def get_model_info(self) -> Dict:
        """Return model metadata."""
        info = {
            'model_type': 'sklearn.LogisticRegression' if self.use_sklearn else 'manual_sigmoid',
            'feature_weights': self.weights,
            'bias': self.bias,
            'trained': self.model is not None if self.use_sklearn else True,
        }
        if self.use_sklearn and self.model is not None:
            try:
                info['coefficients'] = self.model.coef_[0].tolist()
                info['intercept'] = float(self.model.intercept_[0])
            except:
                pass
        return info


# ═════════════════════════════════════════════════════════════════════════════
# Example usage
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Initialize predictor
    predictor = MLPingPongPredictor(use_sklearn=True)
    
    # Test feature vectors
    # High ping-pong case: all features elevated
    high_pp_features = np.array([0.8, 0.7, 0.8, 0.6, 0.9])
    
    # Low ping-pong case: all features low
    low_pp_features = np.array([0.1, 0.1, 0.05, 0.1, 0.0])
    
    # Intermediate case
    mid_pp_features = np.array([0.5, 0.4, 0.3, 0.2, 0.5])
    
    print("Testing ML Predictor:")
    print(f"High ping-pong features:  P_pp = {predictor.predict_probability(high_pp_features):.4f}")
    print(f"Low ping-pong features:   P_pp = {predictor.predict_probability(low_pp_features):.4f}")
    print(f"Mid ping-pong features:   P_pp = {predictor.predict_probability(mid_pp_features):.4f}")
    
    print("\nFeature Weights:")
    for name, weight in predictor.get_feature_weights().items():
        print(f"  {name}: {weight:.2f}")
